"""Module discovery, config validation, parameter validation and hot loading.

A module is a directory inside MODULES_DIR containing:

    config.json   metadata + parameter schema + default schedule window
    main.py       an async ``run(params) -> dict`` entry point
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import re
import sys
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
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


class ModuleConfigError(ValueError):
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


def _apply_field_values(module: Module, values: dict[str, Any]) -> None:
    """Apply config fields; None legacy_key/directory_name are skipped.

    Other None values intentionally clear the DB field (config is source of
    truth). This preserves manually mapped directory/legacy credentials.
    """
    for field, value in values.items():
        if value is None and field in {"legacy_key", "directory_name"}:
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


async def sync_modules(db: AsyncSession) -> SyncResult:
    """Reconcile modules directory with DB; soft-mark missing directories.

    Directory scanning is a point-in-time operation. Do not manually edit
    module configuration during a scan; run another scan after changes.
    """
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
        row = await _find_existing_module(db, item.key, config)
        if row is None:
            row = _create_module_from_config(db, item.key, config)
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
