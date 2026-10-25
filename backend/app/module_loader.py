"""Module discovery, config validation, parameter validation and hot loading.

A module is a directory inside MODULES_DIR containing:

    config.json   metadata + parameter schema + default schedule window
    main.py       an async ``run(params) -> dict`` entry point
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import os
import json
import logging
import math
import re
import sys
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event as sa_event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Module
from .scheduling import (
    LEGACY_CYCLE_MAP,
    ScheduleError,
    normalize_legacy_cycle,
    validate_schedule,
)

logger = logging.getLogger(__name__)

MODULE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def get_module_physical_path(module: Module) -> Path:
    """Resolve a module's physical directory, independent of its API key."""
    directory = module.directory_name or module.key
    if not MODULE_KEY_PATTERN.fullmatch(directory):
        raise ModuleConfigError(
            f"模块 {module.key} 的 directory_name={directory!r} 不合法"
        )
    root = settings.modules_dir.resolve()
    target = (root / directory).resolve()
    if not target.is_relative_to(root):
        raise ModuleConfigError("模块物理目录越界")
    return target
PARAM_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
SUPPORTED_PARAM_TYPES = {"text", "textarea", "password", "select", "switch", "number"}
MAX_PARAMS = 60
MAX_ACCOUNTS = 50


_MODULE_LOADER_DEFAULTS: dict[str, float] = {
    "CONCURRENT_RETRY_DELAY": 0.05,
}
def _safe_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(
            "环境变量 %s=%r 非法，使用默认值 %s", name, raw, default
        )
        return default


_CONCURRENT_RETRY_DELAY = _safe_float_env(
    "CONCURRENT_RETRY_DELAY",
    _MODULE_LOADER_DEFAULTS["CONCURRENT_RETRY_DELAY"],
)


class ModuleError(Exception):
    """Raised when a module cannot be created or reconciled safely."""


class ModuleSessionError(ModuleError):
    """Raised when a DB session cannot continue after a sync conflict."""


class DatabaseUnavailableError(ModuleError):
    """Raised when both the original and retry DB sessions are unusable."""


class ModuleConfigError(ModuleError, ValueError):
    """Raised for invalid module folders or config files."""


class ModuleParam(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str = Field(min_length=1, max_length=64, pattern=PARAM_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "textarea", "password", "select", "switch", "number"] = "text"
    required: bool = False
    default: Any = None
    placeholder: str | None = None
    help: str | None = None
    options: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    rows: int | None = None
    account_label: bool = False
    sensitive: bool = False

    @model_validator(mode="after")
    def validate_specific_type(self) -> "ModuleParam":
        if self.type == "select":
            if not self.options:
                raise ValueError("select 类型参数必须提供非空 options 数组")
            normalized_values: list[str] = []
            for option in self.options:
                if isinstance(option, dict):
                    if "value" not in option:
                        raise ValueError("select 的 options 对象必须包含 value 字段")
                    value = option["value"]
                elif isinstance(option, (str, int, float, bool)):
                    value = option
                else:
                    raise ValueError("select 的 options 只能是字符串/数字或 {label,value} 对象")
                normalized_values.append(str(value))
            if len(normalized_values) != len(set(normalized_values)):
                raise ValueError("select 的 options 值不能重复")
        if self.type == "number":
            if self.min is not None and self.max is not None and self.min > self.max:
                raise ValueError("number 参数的 min 不能大于 max")
            if self.default is not None and not isinstance(self.default, (int, float)):
                raise ValueError("number 参数的 default 必须是数字")
        if self.type == "switch" and self.default is not None and not isinstance(
            self.default, bool
        ):
            raise ValueError("switch 参数的 default 必须是 true/false")
        if self.rows is not None:
            self.rows = max(2, min(20, int(self.rows)))
        key = self.key.lower()
        if (
            self.type == "password"
            or key in {
                "password",
                "passwd",
                "pwd",
                "cookie",
                "token",
                "secret",
                "key",
                "api_key",
                "access_token",
                "refresh_token",
                "authorization",
            }
            or key.endswith("_token")
            or key.endswith("_secret")
            or key.endswith("_key")
        ):
            self.sensitive = True
        return self


class ModuleConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    author: str = Field(default="", max_length=120)
    version: str = Field(default="1.0.0", max_length=40)
    icon: str = Field(default="🧩", max_length=65536)
    icon_source: Literal["url", "base64", "local"] = "url"
    icon_data: str | None = Field(default=None, max_length=65536)
    directory_name: str | None = Field(default=None, max_length=80)
    # Explicit opt-in for preserving an old API key after a directory rename.
    legacy_key: str | None = Field(default=None, max_length=80)
    # Legacy field accepted for old modules; new modules should use the fields below.
    default_cron: str | None = Field(default=None, max_length=100)
    default_start_time: str = Field(default="08:00", max_length=5)
    default_end_time: str = Field(default="10:00", max_length=5)
    default_repeat_cycle: str = Field(default="daily", max_length=20)
    default_repeat_sub_value: str = Field(default="", max_length=10)
    multi_account: bool = False
    params: list[ModuleParam] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_config(self) -> "ModuleConfig":
        if len(self.params) > MAX_PARAMS:
            raise ValueError(f"参数数量不能超过 {MAX_PARAMS} 个")
        seen: set[str] = set()
        for param in self.params:
            if param.key in seen:
                raise ValueError(f"参数 key 重复：{param.key}")
            seen.add(param.key)

        data_uri = self.icon_data
        if self.directory_name is not None:
            self.directory_name = self.directory_name.strip() or None
            if self.directory_name is not None and not MODULE_KEY_PATTERN.fullmatch(
                self.directory_name
            ):
                raise ValueError("directory_name 只能包含字母、数字、下划线和短横线")
        if self.legacy_key is not None:
            self.legacy_key = self.legacy_key.strip() or None
            if self.legacy_key is not None and not MODULE_KEY_PATTERN.fullmatch(
                self.legacy_key
            ):
                raise ValueError("legacy_key 只能包含字母、数字、下划线和短横线")
        if self.icon.startswith("data:"):
            data_uri = self.icon
        if data_uri is not None:
            if len(data_uri.encode("utf-8")) > 65536:
                raise ValueError("Base64 图标不能超过 64KB")
            import re
            if not re.fullmatch(
                r"data:image/(x-icon|png|svg\+xml);base64,[A-Za-z0-9+/=]+",
                data_uri,
            ):
                raise ValueError("图标不是合法的 Base64 图片 Data URI")
        elif self.icon_source == "base64":
            raise ValueError("icon_source=base64 时必须提供 icon_data")

        # Backward compatibility: derive a reasonable daily window from a simple
        # legacy cron expression when the new fields were not supplied.
        fields_set = self.model_fields_set
        if self.default_cron and (
            "default_start_time" not in fields_set
            or "default_end_time" not in fields_set
        ):
            derived = _derive_window_from_cron(self.default_cron)
            if derived:
                if "default_start_time" not in fields_set:
                    self.default_start_time = derived[0]
                if "default_end_time" not in fields_set:
                    self.default_end_time = derived[1]

        legacy_cycle = self.default_repeat_cycle.strip().lower()
        if legacy_cycle in LEGACY_CYCLE_MAP:
            logger.warning(
                "模块 %s 使用了已移除的周期 %s，已自动降级为每月 1 日",
                self.name,
                legacy_cycle,
            )
        try:
            (
                self.default_start_time,
                self.default_end_time,
                self.default_repeat_cycle,
                self.default_repeat_sub_value,
            ) = validate_schedule(
                self.default_start_time,
                self.default_end_time,
                self.default_repeat_cycle,
                self.default_repeat_sub_value,
            )
        except ScheduleError as exc:
            raise ValueError(str(exc)) from exc

        self.name = self.name.strip() or "未命名模块"
        self.description = self.description.strip()
        return self


@dataclass
class ScannedModule:
    key: str
    path: Path
    config: ModuleConfig | None = None
    error: str | None = None


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    total: int = 0
    invalid: list[tuple[str, str]] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    session_rebuilt: bool = False


def format_validation_error(exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors()[:8]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = error.get("msg", "校验失败")
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        messages.append(f"{location}：{message}" if location else message)
    return "；".join(messages) or "配置格式不正确"


def parse_config_file(path: Path) -> ModuleConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModuleConfigError(f"无法读取 config.json：{exc}") from exc
    except UnicodeDecodeError as exc:
        raise ModuleConfigError("config.json 必须使用 UTF-8 编码") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModuleConfigError(
            f"config.json 不是合法 JSON（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}"
        ) from exc
    if not isinstance(raw, dict):
        raise ModuleConfigError("config.json 顶层必须是一个对象")
    try:
        return ModuleConfig.model_validate(raw)
    except ValidationError as exc:
        raise ModuleConfigError(f"config.json 校验失败：{format_validation_error(exc)}") from exc


def validate_module_key(key: str) -> str:
    key = (key or "").strip()
    if not MODULE_KEY_PATTERN.fullmatch(key):
        raise ModuleConfigError(
            "模块标识只能包含字母、数字、下划线和短横线，长度 1-80，且必须以字母或数字开头"
        )
    return key


def scan_modules() -> list[ScannedModule]:
    modules_dir = settings.modules_dir
    modules_dir.mkdir(parents=True, exist_ok=True)
    scanned: list[ScannedModule] = []
    for entry in sorted(modules_dir.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        config_path = entry / "config.json"
        main_path = entry / "main.py"
        if not config_path.is_file() and not main_path.is_file():
            continue
        key = entry.name
        try:
            if not MODULE_KEY_PATTERN.fullmatch(key):
                raise ModuleConfigError(
                    "模块目录名只能包含字母、数字、下划线和短横线，且必须以字母或数字开头"
                )
            if not config_path.is_file():
                raise ModuleConfigError("缺少 config.json")
            if not main_path.is_file():
                raise ModuleConfigError("缺少 main.py")
            config = parse_config_file(config_path)
            scanned.append(ScannedModule(key=key, path=entry, config=config))
        except Exception as exc:
            scanned.append(
                ScannedModule(
                    key=key,
                    path=entry,
                    error=str(exc) or exc.__class__.__name__,
                )
            )
    return scanned


def _module_field_values(config: ModuleConfig) -> dict[str, Any]:
    """Return config-derived fields shared by create and update paths.

    directory_name is populated here but callers explicitly override it:
    create uses config.directory_name or the physical key; update preserves
    an existing manual mapping when config does not declare one.
    """
    return {
        "directory_name": config.directory_name,
        "legacy_key": config.legacy_key,
        "name": config.name,
        "description": config.description,
        "author": config.author,
        "version": config.version,
        "icon": config.icon or "🧩",
        "icon_source": config.icon_source,
        "icon_data": config.icon_data,
        "default_start_time": config.default_start_time,
        "default_end_time": config.default_end_time,
        "default_repeat_cycle": config.default_repeat_cycle,
        "default_repeat_sub_value": config.default_repeat_sub_value,
        "multi_account": config.multi_account,
    }


async def _find_existing_module(
    db: AsyncSession,
    key: str,
    config: ModuleConfig,
) -> Module | None:
    """Find a row by scanned key, then by explicit legacy_key.

    ``config`` comes from the scanned physical directory's config.json.
    The legacy lookup only accepts a row whose directory_name is still NULL,
    so a mapped directory is never silently rebound.

    Concurrency notes:
        This function assumes the caller holds a database transaction with
        at least READ COMMITTED isolation. Concurrent module uploads that
        modify directory_name during a sync_modules scan may cause transient
        conflicts; the calling code's directory_name unique index will catch
        duplicates at the DB level.
    """
    row = await db.scalar(select(Module).where(Module.key == key))
    if row is None and config.directory_name and config.legacy_key:
        # Only reject self-reference here. Other scanned directories are
        # protected by the DB unique directory index and conflict checks.
        if config.legacy_key == key:
            return None
        row = await db.scalar(
            select(Module).where(
                Module.key == config.legacy_key,
                Module.directory_name.is_(None),
            )
        )
    return row


# Fields whose None value means "keep the database value". Adding a new
# nullable identity/mapping field requires adding it here and updating tests.
_SKIP_NONE_FIELDS = frozenset({"legacy_key", "directory_name"})


def _apply_field_values(module: Module, values: dict[str, Any]) -> None:
    """Apply config fields; None legacy_key/directory_name are skipped.

    Other None values intentionally clear the DB field (config is source of
    truth). This preserves manually mapped directory/legacy credentials.
    """
    for field, value in values.items():
        if value is None and field in _SKIP_NONE_FIELDS:
            continue
        setattr(module, field, value)


def _create_module_from_config(
    db: AsyncSession, key: str, config: ModuleConfig
) -> Module:
    schema = [param.model_dump(mode="json") for param in config.params]
    field_values = _module_field_values(config)
    # Creation always has a physical directory: explicit config or the key.
    field_values.pop("directory_name", None)
    field_values["directory_name"] = config.directory_name or key
    row = Module(
        key=key,
        **{
            **field_values,
            "default_cron": config.default_cron or "0 8 * * *",
            "cron": config.default_cron or "0 8 * * *",
            "start_time": config.default_start_time,
            "end_time": config.default_end_time,
            "repeat_cycle": config.default_repeat_cycle,
            "repeat_sub_value": config.default_repeat_sub_value,
            "push_enabled": False,
            "push_independent": False,
            "push_unified": False,
            "enabled": False,
            "param_schema": schema,
            "load_error": None,
        },
    )
    db.add(row)
    return row


async def _create_or_get_module(
    db: AsyncSession, key: str, config: ModuleConfig
) -> Module:
    """Create or get a module idempotently using a SAVEPOINT.

    The SAVEPOINT isolates the failed insert from the outer transaction.
    If the post-conflict lookup also fails (e.g. SQLite pending rollback),
    ModuleError is raised without touching the outer transaction.
    """
    existing = await db.scalar(select(Module).where(Module.key == key))
    if existing is not None:
        return existing

    row = _create_module_from_config(db, key, config)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        logger.warning("模块 %s 并发创建冲突，尝试复用已有记录", key)
        await asyncio.sleep(_CONCURRENT_RETRY_DELAY)
        try:
            row = await db.scalar(select(Module).where(Module.key == key))
        except Exception as lookup_exc:
            logger.error(
                "模块 %s 冲突后查询失败，外层事务可能已损坏: %s",
                key, lookup_exc,
            )
            raise ModuleError(
                f"模块 {key} 并发冲突后无法确认状态，请重试"
            ) from lookup_exc
        if row is None:
            raise ModuleError(
                f"模块 {key} 并发创建冲突，请重新扫描或重试上传"
            ) from None
    return row


def _update_module_from_config(
    module: Module, config: ModuleConfig
) -> str | None:
    _apply_field_values(module, _module_field_values(config))
    # Preserve a manually mapped directory unless config explicitly overrides.
    if config.directory_name is not None:
        module.directory_name = config.directory_name
    elif not module.directory_name:
        module.directory_name = module.key
    module.default_cron = config.default_cron or module.default_cron or "0 8 * * *"
    if not module.start_time:
        module.start_time = config.default_start_time
    if not module.end_time:
        module.end_time = config.default_end_time
    if not module.repeat_cycle:
        module.repeat_cycle = config.default_repeat_cycle
    try:
        cycle, sub_value = normalize_legacy_cycle(
            module.repeat_cycle, module.repeat_sub_value
        )
    except ScheduleError as exc:
        module.load_error = f"重复周期无效：{exc}"
        return module.load_error
    module.repeat_cycle = cycle
    if not module.repeat_sub_value:
        module.repeat_sub_value = sub_value
    module.param_schema = [
        param.model_dump(mode="json") for param in config.params
    ]
    module.load_error = None
    return None


async def _mark_missing_modules(
    db: AsyncSession, seen: set[str], result: SyncResult
) -> None:
    all_keys = (await db.execute(select(Module.key))).scalars().all()
    missing_keys = set(all_keys) - seen
    if not missing_keys:
        return
    rows = await db.execute(select(Module).where(Module.key.in_(missing_keys)))
    for row in rows.scalars():
        row.load_error = "模块目录不存在或已被移除"
        result.invalid.append((row.key, row.load_error))


# Striped locks: fixed memory, small chance of harmless hash collisions.
_LOCK_STRIPES = 64
_KEY_LOCKS: list[asyncio.Lock] = [asyncio.Lock() for _ in range(_LOCK_STRIPES)]
_STRIPE_WAIT_COUNTS: list[float] = [0.0] * _LOCK_STRIPES
_STRIPE_GUARD = threading.Lock()
_STRIPE_LAST_DECAY = time.monotonic()
_DECAY_INTERVAL_SECONDS: float = _safe_float_env(
    "STRIPE_DECAY_INTERVAL_SECONDS", 60.0
)
DECAY_ZERO_THRESHOLD: float = _safe_float_env(
    "STRIPE_DECAY_ZERO_THRESHOLD", 0.1
)
_DECAY_HIGH_WATERMARK: float = _safe_float_env(
    "STRIPE_DECAY_HIGH_WATERMARK", 100.0
)
_DECAY_AGGRESSIVE_FACTOR: float = _safe_float_env(
    "STRIPE_DECAY_AGGRESSIVE_FACTOR", 0.25
)
_DECAY_LOW_WATERMARK: float = _safe_float_env(
    "STRIPE_DECAY_LOW_WATERMARK", 10.0
)
_DECAY_NORMAL_FACTOR: float = 0.5


def _calculate_decay_factor(current: float) -> float:
    if current <= _DECAY_LOW_WATERMARK:
        return _DECAY_NORMAL_FACTOR
    if current >= _DECAY_HIGH_WATERMARK:
        return _DECAY_AGGRESSIVE_FACTOR
    ratio = (current - _DECAY_LOW_WATERMARK) / (
        _DECAY_HIGH_WATERMARK - _DECAY_LOW_WATERMARK
    )
    return _DECAY_NORMAL_FACTOR + ratio * (
        _DECAY_AGGRESSIVE_FACTOR - _DECAY_NORMAL_FACTOR
    )
_decay_params_cache: tuple[float, float, str, str, int] | None = None
_decay_params_version: int = 0


def _get_decay_params() -> tuple[float, float, int]:
    """Read decay threshold and interval atomically from env values."""
    global _decay_params_cache, _decay_params_version
    raw_threshold = os.environ.get("STRIPE_DECAY_ZERO_THRESHOLD", "0.1")
    raw_interval = os.environ.get("STRIPE_DECAY_INTERVAL_SECONDS", "60.0")
    if (
        _decay_params_cache is not None
        and _decay_params_cache[2] == raw_threshold
        and _decay_params_cache[3] == raw_interval
    ):
        return (
            _decay_params_cache[0],
            _decay_params_cache[1],
            _decay_params_cache[4],
        )
    try:
        threshold = float(raw_threshold)
    except ValueError:
        threshold = 0.1
    try:
        interval = float(raw_interval)
    except ValueError:
        interval = 60.0
    _decay_params_version += 1
    _decay_params_cache = (
        threshold,
        interval,
        raw_threshold,
        raw_interval,
        _decay_params_version,
    )
    return threshold, interval, _decay_params_version


def _decay_if_needed() -> None:
    global _STRIPE_LAST_DECAY
    with _STRIPE_GUARD:
        now = time.monotonic()
        zero_threshold, base_interval, _ = _get_decay_params()
        max_count = max(_STRIPE_WAIT_COUNTS) if _STRIPE_WAIT_COUNTS else 0.0
        effective_interval = (
            max(5.0, base_interval / 4.0)
            if max_count > _DECAY_HIGH_WATERMARK
            else base_interval
        )
        if now - _STRIPE_LAST_DECAY < effective_interval:
            return
        for index in range(_LOCK_STRIPES):
            current = _STRIPE_WAIT_COUNTS[index]
            factor = _calculate_decay_factor(current)
            value = current * factor
            _STRIPE_WAIT_COUNTS[index] = (
                0.0 if value < zero_threshold else value
            )
        _STRIPE_LAST_DECAY = now
    _save_decay_state()


_DECAY_STATE_FILE = Path(
    os.environ.get("STRIPE_DECAY_STATE_FILE", "/tmp/stripe_decay_state.json")
)
_DECAY_STATE_LAST_SAVE = 0.0
_DECAY_STATE_MIN_WRITE_INTERVAL: float = 30.0


_DECAY_STATE_WRITABLE: bool = True
_DECAY_FLUSH_IN_PROGRESS: bool = False


def flush_decay_state_on_shutdown() -> None:
    """Force decay state persistence with a bounded daemon thread."""
    global _DECAY_STATE_LAST_SAVE, _DECAY_FLUSH_IN_PROGRESS
    if _DECAY_FLUSH_IN_PROGRESS:
        logger.debug("Decay state flush already in progress, skipping")
        return
    _DECAY_FLUSH_IN_PROGRESS = True
    try:
        _DECAY_STATE_LAST_SAVE = 0.0
        thread = threading.Thread(
            target=_save_decay_state,
            daemon=True,
            name="decay-flush",
        )
        thread.start()
        thread.join(timeout=2.0)
        if thread.is_alive():
            logger.warning(
                "Decay state flush timed out after 2s during shutdown"
            )
    except Exception:
        logger.warning("Shutdown decay state flush failed", exc_info=True)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically with parent directory auto-creation."""
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(
            f"Cannot create directory {parent}: {exc}"
        ) from exc
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _save_decay_state() -> None:
    """Persist decay state atomically, with write throttling."""
    global _DECAY_STATE_LAST_SAVE, _DECAY_STATE_WRITABLE
    if not _DECAY_STATE_WRITABLE:
        return
    now = time.monotonic()
    if now - _DECAY_STATE_LAST_SAVE < _DECAY_STATE_MIN_WRITE_INTERVAL:
        return
    try:
        with _STRIPE_GUARD:
            state = {
                "wait_counts": list(_STRIPE_WAIT_COUNTS),
                "last_decay_wall": time.time(),
                "writable": _DECAY_STATE_WRITABLE,
            }
        _atomic_write_json(_DECAY_STATE_FILE, state)
        _DECAY_STATE_LAST_SAVE = now
    except PermissionError:
        _DECAY_STATE_WRITABLE = False
        logger.error(
            "Decay state directory became read-only. Persistence disabled."
        )
        # Directory is confirmed read-only: do not retry a futile write.
    except FileNotFoundError:
        _DECAY_STATE_WRITABLE = False
        logger.error(
            "Decay state directory was deleted. Persistence disabled."
        )
    except Exception:
        logger.warning("Failed to save decay state", exc_info=True)


def _ensure_decay_state_dir() -> None:
    """Ensure parent directory exists and is writable."""
    global _DECAY_STATE_WRITABLE
    try:
        parent = _DECAY_STATE_FILE.parent
        parent.mkdir(parents=True, exist_ok=True)
        test_file = parent / ".write_test_tmp"
        test_file.touch()
        test_file.unlink()
        _DECAY_STATE_WRITABLE = True
    except PermissionError:
        _DECAY_STATE_WRITABLE = False
        logger.error(
            "Decay state directory is not writable: %s. "
            "Persistence will be disabled.",
            _DECAY_STATE_FILE.parent,
        )
    except Exception:
        _DECAY_STATE_WRITABLE = False
        logger.warning(
            "Failed to prepare decay state directory: %s",
            _DECAY_STATE_FILE.parent,
            exc_info=True,
        )


def _load_decay_state() -> None:
    """Restore decay state best-effort on startup."""
    global _STRIPE_LAST_DECAY, _DECAY_STATE_WRITABLE
    try:
        if not _DECAY_STATE_FILE.exists():
            return
        data = json.loads(_DECAY_STATE_FILE.read_text())
        with _STRIPE_GUARD:
            counts = data.get("wait_counts", [])
            if len(counts) == _LOCK_STRIPES:
                _STRIPE_WAIT_COUNTS[:] = [float(c) for c in counts]
            _DECAY_STATE_WRITABLE = bool(data.get("writable", True))
            wall_ts = float(data.get("last_decay_wall", 0.0))
            if wall_ts > 0:
                elapsed = time.time() - wall_ts
                _STRIPE_LAST_DECAY = time.monotonic() - max(0.0, elapsed)
            else:
                _STRIPE_LAST_DECAY = 0.0
        _DECAY_STATE_LAST_SAVE = time.monotonic()
    except Exception:
        pass


async def _get_key_lock(key: str) -> asyncio.Lock:
    index = hash(key) % _LOCK_STRIPES
    lock = _KEY_LOCKS[index]
    if lock.locked():
        _decay_if_needed()
        with _STRIPE_GUARD:
            _STRIPE_WAIT_COUNTS[index] += 1
    return lock


# All mutations must hold _POOL_EVENT_LOCK; the lock protects both dict
# structure and the read-modify-write of integer counters.
_POOL_EVENT_COUNTERS: dict[str, int] = {
    "connect": 0,
    "checkout": 0,
    "checkin": 0,
    "disconnect": 0,
    "error": 0,
    "invalidate": 0,
}
_POOL_EVENT_LOCK = threading.Lock()


_POOL_EVENTS_REGISTERED: bool = False
_REGISTERED_POOL_ID: int = 0
_REGISTERED_POOL_EVENT_KEYS: set[tuple[int, str]] = set()
_POOL_EVENTS_FULLY_REGISTERED: bool = False
_POOL_REGISTRATION_LOCK = threading.RLock()


def _is_current_pool(record: object) -> bool:
    pool = getattr(record, "pool", None)
    return pool is None or id(pool) == _REGISTERED_POOL_ID


def _on_connect(*args, **kwargs):
    try:
        if len(args) > 1 and not _is_current_pool(args[1]):
            return
        with _POOL_EVENT_LOCK:
            _POOL_EVENT_COUNTERS["connect"] += 1
    except Exception:
        logger.debug("Pool connect probe failed", exc_info=True)


def _on_checkout(*args, **kwargs):
    try:
        if len(args) > 1 and not _is_current_pool(args[1]):
            return
        with _POOL_EVENT_LOCK:
            _POOL_EVENT_COUNTERS["checkout"] += 1
    except Exception:
        logger.debug("Pool checkout probe failed", exc_info=True)


def _on_checkin(*args, **kwargs):
    try:
        if len(args) > 1 and not _is_current_pool(args[1]):
            return
        with _POOL_EVENT_LOCK:
            _POOL_EVENT_COUNTERS["checkin"] += 1
    except Exception:
        logger.debug("Pool checkin probe failed", exc_info=True)


def _on_disconnect(*args, **kwargs):
    try:
        if len(args) > 1 and not _is_current_pool(args[1]):
            return
        with _POOL_EVENT_LOCK:
            _POOL_EVENT_COUNTERS["disconnect"] += 1
    except Exception:
        logger.debug("Pool disconnect probe failed", exc_info=True)


def _on_error(*args, **kwargs):
    try:
        if len(args) > 1 and not _is_current_pool(args[1]):
            return
        with _POOL_EVENT_LOCK:
            _POOL_EVENT_COUNTERS["error"] += 1
    except Exception:
        logger.debug("Pool error probe failed", exc_info=True)


def _on_invalidate(*args, **kwargs):
    try:
        if len(args) > 1 and not _is_current_pool(args[1]):
            return
        with _POOL_EVENT_LOCK:
            _POOL_EVENT_COUNTERS["invalidate"] += 1
    except Exception:
        logger.debug("Pool invalidate probe failed", exc_info=True)


def _register_pool_events() -> None:
    # Double-checked locking: the common fully-registered path avoids locking.
    if _POOL_EVENTS_FULLY_REGISTERED:
        try:
            from .database import engine
            if _REGISTERED_POOL_ID == id(engine.pool):
                return
        except Exception:
            pass
    with _POOL_REGISTRATION_LOCK:
        _register_pool_events_locked()


POOL_METRIC_KEYS = frozenset({
    "pool_connect", "pool_checkout", "pool_checkin",
    "pool_disconnect", "pool_error", "pool_invalidate",
})


def get_pool_metrics_snapshot() -> dict[str, int]:
    """Return a thread-safe, type-validated pool counter snapshot.

    Keys are ``pool_<event>`` where event is one of connect, checkout,
    checkin, disconnect, error, invalidate. Values are int; invalid values
    are logged and coerced to 0. Mutating the returned dict never affects
    internal counters.
    """
    with _POOL_EVENT_LOCK:
        result: dict[str, int] = {}
        for pool_key in POOL_METRIC_KEYS:
            raw_key = pool_key.removeprefix("pool_")
            value = _POOL_EVENT_COUNTERS.get(raw_key, 0)
            try:
                result[pool_key] = int(value)
            except (TypeError, ValueError):
                result[pool_key] = 0
                logger.warning(
                    "Invalid pool metric %s=%r; using 0", raw_key, value
                )
        return result


def _reset_pool_metrics() -> None:
    """Reset cumulative pool counters when a new Pool is bound."""
    with _POOL_EVENT_LOCK:
        for key in _POOL_EVENT_COUNTERS:
            _POOL_EVENT_COUNTERS[key] = 0


def _register_pool_events_locked() -> None:
    global _POOL_EVENTS_REGISTERED, _REGISTERED_POOL_ID
    global _POOL_EVENTS_FULLY_REGISTERED
    try:
        from .database import engine
        pool = engine.pool
        current_pool_id = id(pool)
    except Exception:
        logger.warning("无法获取连接池，跳过事件探针注册", exc_info=True)
        _POOL_EVENTS_REGISTERED = False
        return

    if (
        _POOL_EVENTS_FULLY_REGISTERED
        and _REGISTERED_POOL_ID == current_pool_id
    ):
        return

    if _POOL_EVENTS_REGISTERED and _REGISTERED_POOL_ID != current_pool_id:
        _REGISTERED_POOL_EVENT_KEYS.clear()
        _POOL_EVENTS_FULLY_REGISTERED = False
        _reset_pool_metrics()

    _POOL_EVENTS_REGISTERED = True
    _REGISTERED_POOL_ID = current_pool_id

    events = [
        ("connect", _on_connect),
        ("checkout", _on_checkout),
        ("checkin", _on_checkin),
        ("disconnect", _on_disconnect),
        ("error", _on_error),
        ("invalidate", _on_invalidate),
    ]
    all_success = True
    for event_name, listener in events:
        key = (current_pool_id, event_name)
        if key in _REGISTERED_POOL_EVENT_KEYS:
            continue
        try:
            sa_event.listens_for(pool, event_name)(listener)
            _REGISTERED_POOL_EVENT_KEYS.add(key)
        except Exception:
            logger.warning(
                "连接池事件注册失败: %s", event_name, exc_info=True
            )
            all_success = False
    _POOL_EVENTS_FULLY_REGISTERED = all_success


_register_pool_events()

_POOL_METRICS_CACHE: dict[str, int] = {}
_POOL_METRICS_TS: float = 0.0
_POOL_METRICS_TTL: float = 5.0
_POOL_METRICS_REFRESH_CALLBACKS: list[Callable[[dict[str, int]], None]] = []


def register_pool_metrics_refresh_callback(
    cb: Callable[[dict[str, int]], None],
) -> None:
    """Register a callback invoked after pool metrics are re-read.

    Do not call get_stripe_contention_stats() from the callback.
    """
    with _STRIPE_GUARD:
        _POOL_METRICS_REFRESH_CALLBACKS.append(cb)


def _get_pool_metrics() -> dict[str, int]:
    global _POOL_METRICS_CACHE, _POOL_METRICS_TS
    now = time.monotonic()
    with _STRIPE_GUARD:
        if now - _POOL_METRICS_TS < _POOL_METRICS_TTL and _POOL_METRICS_CACHE:
            return dict(_POOL_METRICS_CACHE)
        from .database import engine
        pool = engine.pool
        metrics = {
            "pool_size": int(getattr(pool, "size", lambda: 0)()),
            "pool_checked_in": int(getattr(pool, "checkedin", lambda: 0)()),
            "pool_checked_out": int(getattr(pool, "checkedout", lambda: 0)()),
            "pool_overflow": int(getattr(pool, "overflow", lambda: 0)()),
        }
        _POOL_METRICS_CACHE = metrics
        _POOL_METRICS_TS = now
        callbacks = list(_POOL_METRICS_REFRESH_CALLBACKS)
    for cb in callbacks:
        try:
            cb(dict(metrics))
        except Exception:
            logger.exception("Pool metrics refresh callback failed")
    return metrics


def invalidate_pool_metrics_cache() -> None:
    """Force pool metrics to be re-read on next access."""
    global _POOL_METRICS_TS
    with _STRIPE_GUARD:
        _POOL_METRICS_TS = 0.0


_POOL_INSTANT_CACHE_TTL: float = 5.0
_pool_instant_cache: dict[str, int | float] = {}
_pool_instant_cache_ts: float = 0.0


def _get_pool_instant_metrics() -> dict[str, int | float]:
    global _pool_instant_cache, _pool_instant_cache_ts
    now = time.monotonic()
    if now - _pool_instant_cache_ts < _POOL_INSTANT_CACHE_TTL:
        return dict(_pool_instant_cache)
    try:
        from .database import engine
        pool = engine.pool
        current_out = pool.checkedout() if hasattr(pool, "checkedout") else 0
        current_size = pool.size() if hasattr(pool, "size") else 0
    except Exception:
        current_out = 0
        current_size = 0
    result = {
        "pool_current_checked_out": int(current_out),
        "pool_current_size": int(current_size),
        "pool_utilization": (
            current_out / current_size if current_size > 0 else 0.0
        ),
    }
    _pool_instant_cache = result
    _pool_instant_cache_ts = now
    return result


def get_stripe_contention_stats() -> dict[str, int | float]:
    """Return contention stats, or zeros when the sample is stale.

    Call invalidate_pool_metrics_cache() after migrations/pool changes to
    force an immediate refresh instead of waiting for the 5-second TTL.

    All accesses to _STRIPE_LAST_DECAY are protected by _STRIPE_GUARD for
    thread safety.
    """
    _, interval, decay_version = _get_decay_params()
    with _STRIPE_GUARD:
        stale = (
            time.monotonic() - _STRIPE_LAST_DECAY
            >= interval
        )
        counts = [] if stale else [
            int(count) for count in _STRIPE_WAIT_COUNTS
        ]
    metrics: dict[str, int | float] = {}
    metrics.update(_get_pool_metrics())
    metrics["decay_config_version"] = decay_version
    pool_snapshot = get_pool_metrics_snapshot()
    metrics.update({
        "pool_total_connects": pool_snapshot["pool_connect"],
        "pool_total_checkouts": pool_snapshot["pool_checkout"],
        "pool_total_checkins": pool_snapshot["pool_checkin"],
        "pool_total_disconnects": pool_snapshot["pool_disconnect"],
        "pool_total_errors": pool_snapshot["pool_error"],
        "pool_total_invalidations": pool_snapshot["pool_invalidate"],
    })
    metrics.update(_get_pool_instant_metrics())
    from .main import get_db_log_suppression_stats
    metrics.update(get_db_log_suppression_stats())
    metrics["decay_state_writable"] = _DECAY_STATE_WRITABLE
    if stale:
        return {
            "max_wait": 0,
            "avg_wait": 0,
            "hot_stripes": 0,
            **metrics,
        }
    non_zero = [count for count in counts if count > 0]
    return {
        "max_wait": max(counts),
        "avg_wait": sum(non_zero) // len(non_zero) if non_zero else 0,
        "hot_stripes": sum(1 for count in counts if count > 10),
        **metrics,
    }


async def sync_modules(db: AsyncSession) -> SyncResult:
    """Reconcile modules directory with DB; soft-mark missing directories.

    Different module keys may proceed concurrently via striped locks. If the
    provided session becomes unusable, a fresh session is created and committed
    internally. The caller should not attempt to commit the original session
    after a successful return. After return with session_rebuilt=True, the
    original db parameter MUST be treated as invalid and closed by the caller.
    """
    try:
        return await _sync_modules_locked(db)
    except ModuleSessionError:
        logger.warning("扫描 Session 已损坏，使用新 Session 重试整批一次")
        from .database import SessionLocal

        try:
            async with SessionLocal() as fresh_db:
                result = await _sync_modules_locked(fresh_db)
                # Defensive commit: _sync_modules_locked already commits
                # internally, but this preserves durability if it changes.
                await fresh_db.commit()
                result.session_rebuilt = True
                return result
        except ModuleSessionError as retry_exc:
            logger.error("重试批次 Session 再次损坏，数据库可能不可用")
            raise DatabaseUnavailableError(
                "数据库连接异常，模块扫描已中止"
            ) from retry_exc


async def _sync_modules_locked(db: AsyncSession) -> SyncResult:
    scanned = scan_modules()
    scanned_keys = {item.key for item in scanned}
    result = SyncResult()
    seen: set[str] = set()
    for item in scanned:
        seen.add(item.key)
        if item.config is None:
            result.invalid.append((item.key, item.error or "模块配置无效"))
            continue
        config = item.config
        if config.directory_name and config.directory_name != item.key and not config.legacy_key:
            result.invalid.append((
                item.key,
                f"目录名与 key 不一致，请补 legacy_key={item.key} "
                f"或执行 python -m app.migrate_modules --map {item.key}={config.directory_name}",
            ))
        lock = await _get_key_lock(item.key)
        async with lock:
            row = await _find_existing_module(db, item.key, config)
            if row is None:
                try:
                    row = await _create_or_get_module(db, item.key, config)
                except ModuleError as exc:
                    logger.error("模块 %s 同步创建失败：%s", item.key, exc)
                    result.invalid.append((item.key, str(exc)))
                    try:
                        await db.execute(text("SELECT 1"))
                    except Exception as health_exc:
                        raise ModuleSessionError(
                            f"模块 {item.key} 冲突后 Session 不可用"
                        ) from health_exc
                    continue
                result.added += 1
            else:
                error = _update_module_from_config(row, config)
                if error:
                    result.invalid.append((item.key, error))
                    continue
                result.updated += 1
            seen.add(row.key)
            result.modules.append(row)
    await _mark_missing_modules(db, seen, result)
    await db.commit()
    for row in result.modules:
        await db.refresh(row)
    result.total = len(seen)
    return result


def select_option_values(param: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for option in param.get("options") or []:
        if isinstance(option, dict):
            values.append(option.get("value"))
        else:
            values.append(option)
    return values


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _derive_window_from_cron(cron: str) -> tuple[str, str] | None:
    """Best-effort migration from simple legacy cron to a one-hour window."""
    parts = (cron or "").split()
    if len(parts) != 5:
        return None
    minute, hour = parts[0], parts[1]
    if not minute.isdigit() or not hour.isdigit():
        return None
    minute_i, hour_i = int(minute), int(hour)
    if not (0 <= minute_i <= 59 and 0 <= hour_i <= 23):
        return None
    start_minutes = hour_i * 60 + minute_i
    end_minutes = min(23 * 60 + 59, start_minutes + 60)
    if end_minutes <= start_minutes:
        start_minutes = max(0, end_minutes - 1)
    return (
        f"{start_minutes // 60:02d}:{start_minutes % 60:02d}",
        f"{end_minutes // 60:02d}:{end_minutes % 60:02d}",
    )


def _mask_account_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未提供"
    if "@" in text:
        local, domain = text.split("@", 1)
        return f"{local[:2]}***@{domain}"
    if "=" in text:
        first = text.split(";", 1)[0].strip()
        key, _, cookie_value = first.partition("=")
        cookie_value = cookie_value.strip()
        masked = (
            cookie_value[:4] + "***" + cookie_value[-2:]
            if len(cookie_value) > 8
            else cookie_value[:2] + "***"
        )
        return f"{key}={masked}"
    if len(text) <= 6:
        return text[:2] + "***"
    return f"{text[:4]}***{text[-2:]}"


def account_identity(config: ModuleConfig, params: dict[str, Any]) -> str:
    """Masked identifier used in logs and push messages."""
    labelled = [param for param in config.params if param.account_label]
    candidates = labelled + [
        param
        for param in config.params
        if not param.account_label
        and param.key.lower() in {"account", "username", "email", "cookie", "token"}
    ]
    for param in candidates:
        value = params.get(param.key)
        if value not in (None, ""):
            return _mask_account_value(value)
    return "未提供账号标识"


def account_display(config: ModuleConfig, entry: dict[str, Any]) -> str:
    label = str(entry.get("label") or "").strip()
    if label:
        return label[:80]
    return account_identity(config, entry.get("params") or {})


def normalize_accounts(
    config: ModuleConfig,
    raw_accounts: Any,
    *,
    require_at_least_one: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(raw_accounts, list):
        raise ModuleConfigError("账号列表必须是数组")
    if len(raw_accounts) > MAX_ACCOUNTS:
        raise ModuleConfigError(f"账号数量不能超过 {MAX_ACCOUNTS} 个")
    if require_at_least_one and not raw_accounts:
        raise ModuleConfigError("请至少添加一个账号")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_accounts, start=1):
        if not isinstance(item, dict):
            raise ModuleConfigError(f"第 {index} 个账号格式无效")
        params_raw = item.get("params")
        if params_raw is None:
            # Accept a bare parameter object for API convenience.
            params_raw = {
                key: value
                for key, value in item.items()
                if key not in {"id", "label", "params"}
            }
        if not isinstance(params_raw, dict):
            raise ModuleConfigError(f"第 {index} 个账号的参数必须是对象")
        try:
            params = validate_and_normalize_params(config, params_raw)
        except ModuleConfigError as exc:
            raise ModuleConfigError(f"第 {index} 个账号：{exc}") from exc

        account_id = str(item.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account_id) or account_id in seen_ids:
            account_id = uuid.uuid4().hex
        seen_ids.add(account_id)
        label = str(item.get("label") or "").strip()[:80]
        normalized.append({"id": account_id, "label": label, "params": params})
    return normalized


def validate_and_normalize_params(
    config: ModuleConfig, raw: dict[str, Any] | None
) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ModuleConfigError("参数必须是一个 JSON 对象")

    normalized: dict[str, Any] = {}
    missing: list[str] = []

    for param in config.params:
        value = raw.get(param.key)
        spec = param.model_dump(mode="json")

        if param.type == "switch":
            if _is_empty(value):
                value = param.default if isinstance(param.default, bool) else False
            elif isinstance(value, bool):
                pass
            elif isinstance(value, str) and value.lower() in {"true", "1", "on", "yes"}:
                value = True
            elif isinstance(value, str) and value.lower() in {"false", "0", "off", "no"}:
                value = False
            elif isinstance(value, (int, float)) and value in (0, 1):
                value = bool(value)
            else:
                raise ModuleConfigError(f"参数「{param.label}」必须是开关值")
            normalized[param.key] = value
            continue

        if param.type == "number":
            if _is_empty(value):
                value = param.default
            if _is_empty(value):
                if param.required:
                    missing.append(param.label)
                normalized[param.key] = None
                continue
            if isinstance(value, bool):
                raise ModuleConfigError(f"参数「{param.label}」必须是数字")
            try:
                number = float(value)  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            except (TypeError, ValueError):
                raise ModuleConfigError(f"参数「{param.label}」必须是数字") from None
            if not math.isfinite(number):
                raise ModuleConfigError(f"参数「{param.label}」必须是有限数字")
            if param.min is not None and number < param.min:
                raise ModuleConfigError(f"参数「{param.label}」不能小于 {param.min:g}")
            if param.max is not None and number > param.max:
                raise ModuleConfigError(f"参数「{param.label}」不能大于 {param.max:g}")
            normalized[param.key] = int(number) if number.is_integer() else number
            continue

        if param.type == "select":
            if _is_empty(value):
                value = param.default
            if _is_empty(value):
                if param.required:
                    missing.append(param.label)
                normalized[param.key] = None
                continue
            matched = next(
                (
                    option
                    for option in select_option_values(spec)
                    if option == value or str(option) == str(value)
                ),
                None,
            )
            if matched is None:
                raise ModuleConfigError(f"参数「{param.label}」的值不在可选范围内")
            normalized[param.key] = matched
            continue

        if _is_empty(value):
            value = param.default
        if _is_empty(value):
            if param.required:
                missing.append(param.label)
            normalized[param.key] = ""
            continue
        if isinstance(value, (dict, list)):
            raise ModuleConfigError(f"参数「{param.label}」必须是文本")
        normalized[param.key] = str(value)

    if missing:
        raise ModuleConfigError("请填写必填参数：" + "、".join(missing))
    return normalized


def missing_required_params(config: ModuleConfig, params: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for param in config.params:
        if not param.required:
            continue
        value = params.get(param.key)
        if param.type == "switch":
            continue
        if _is_empty(value):
            missing.append(param.label)
    return missing


@dataclass
class LoadedRunner:
    name: str
    module_dir: Path
    module: ModuleType
    run: Any
    inserted_sys_path: bool = False


def load_runner(key: str, directory_name: str | None = None) -> LoadedRunner:
    key = validate_module_key(key)
    directory = validate_module_key(directory_name or key)
    base_dir = settings.modules_dir.resolve()
    module_dir = (base_dir / directory).resolve()
    if module_dir.parent != base_dir:
        raise ModuleConfigError("模块路径非法")
    if not module_dir.is_dir():
        raise ModuleConfigError("模块目录不存在")
    main_path = module_dir / "main.py"
    if not main_path.is_file():
        raise ModuleConfigError("模块缺少 main.py")

    package_name = f"_checkin_pkg_{re.sub(r'[^A-Za-z0-9_]', '_', key)}_{uuid.uuid4().hex}"
    inserted_sys_path = str(module_dir) not in sys.path
    if inserted_sys_path:
        sys.path.insert(0, str(module_dir))

    try:
        spec = importlib.util.spec_from_file_location(
            package_name,
            main_path,
            submodule_search_locations=[str(module_dir)],
        )
        if spec is None or spec.loader is None:
            raise ModuleConfigError("无法加载 main.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)
        run = getattr(module, "run", None)
        if not callable(run):
            raise ModuleConfigError(
                "main.py 必须定义入口函数：async def run(params: dict) -> dict"
            )
        return LoadedRunner(
            name=package_name,
            module_dir=module_dir,
            module=module,
            run=run,
            inserted_sys_path=inserted_sys_path,
        )
    except Exception:
        for loaded_name in list(sys.modules):
            if loaded_name == package_name or loaded_name.startswith(package_name + "."):
                sys.modules.pop(loaded_name, None)
        if inserted_sys_path:
            try:
                sys.path.remove(str(module_dir))
            except ValueError:
                pass
        raise


def unload_runner(runner: LoadedRunner) -> None:
    for name in list(sys.modules):
        if name == runner.name or name.startswith(runner.name + "."):
            sys.modules.pop(name, None)
    if runner.inserted_sys_path:
        try:
            sys.path.remove(str(runner.module_dir))
        except ValueError:
            pass


def describe_runner_import_error(exc: BaseException) -> str:
    detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return detail or exc.__class__.__name__
