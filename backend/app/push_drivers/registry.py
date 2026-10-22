"""Custom push-driver discovery, hot reload, rollback and invocation."""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
from types import ModuleType
import shutil
import threading
import uuid
import zipfile
from pathlib import Path

from ..config import settings
from .base import DriverLoadError, DriverRecord, DriverValidationError
from .validation import (
    validate_driver_directory,
    validate_driver_source,
    validate_manifest,
    validate_zip_member,
)

logger = logging.getLogger(__name__)


def version_sort_key(version: str) -> tuple:
    """Numeric SemVer-like key; never compare versions lexicographically."""
    parts: list[object] = []
    for piece in version.replace("-", ".").replace("_", ".").split("."):
        parts.append((0, int(piece)) if piece.isdigit() else (1, piece))
    return tuple(parts)


class DriverRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._modules: dict[str, ModuleType] = {}
        self._records: dict[str, DriverRecord] = {}
        self._root = Path(__file__).resolve().parent / "custom"
        self._root.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- discovery
    def _driver_dir(self, key: str) -> Path:
        return self._root / key

    def _versions(self, key: str) -> list[str]:
        base = self._driver_dir(key)
        if not base.is_dir():
            return []
        versions = [
            item.name
            for item in base.iterdir()
            if item.is_dir() and (item / "driver.py").is_file()
        ]
        return sorted(versions, key=version_sort_key, reverse=True)

    def _active_version(self, key: str) -> str | None:
        base = self._driver_dir(key)
        try:
            data = json.loads((base / "active.json").read_text(encoding="utf-8"))
            version = str(data.get("version") or "")
        except (OSError, json.JSONDecodeError):
            return None
        return version if version in self._versions(key) else None

    def _write_active(self, key: str, version: str) -> None:
        base = self._driver_dir(key)
        (base / "active.json").write_text(
            json.dumps({"version": version}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_module(self, key: str, version: str) -> ModuleType:
        directory = self._driver_dir(key) / version
        manifest = validate_driver_directory(directory)
        if manifest["key"] != key:
            raise DriverLoadError("manifest.key 与目录名不一致")
        module_name = f"custom_push_driver_{key}_{version}_{uuid.uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(module_name, directory / "driver.py")
        if spec is None or spec.loader is None:
            raise DriverLoadError("无法创建驱动模块")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise DriverLoadError(f"驱动导入失败：{type(exc).__name__}: {exc}") from exc
        send = getattr(module, "send", None)
        if not callable(send):
            raise DriverLoadError("driver.py 必须定义 send(config, title, body)")
        return module

    def _read_record(self, key: str) -> DriverRecord | None:
        version = self._active_version(key)
        if version is None:
            return None
        try:
            manifest = validate_driver_directory(self._driver_dir(key) / version)
        except DriverValidationError:
            return None
        return DriverRecord(
            key=key,
            name=manifest["name"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            version=version,
            description=manifest["description"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            fields=manifest["fields"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            builtin=False,
            active_version=version,
            versions=self._versions(key),
        )

    def builtin_records(self) -> list[DriverRecord]:
        from .builtin_specs import CHANNEL_SPECS

        return [
            DriverRecord(
                key=spec["channel"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                name=spec["label"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                version="builtin",
                description="内置驱动",
                fields=spec["fields"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                builtin=True,
                active_version="builtin",
                versions=["builtin"],
            )
            for spec in CHANNEL_SPECS
            if spec["channel"] != "none"
        ]

    def list_drivers(self) -> list[dict[str, object]]:
        with self._lock:
            records = [record.public() for record in self.builtin_records()]
            for key in sorted(self._versions_set()):
                record = self._read_record(key)
                if record is not None:
                    records.append(record.public())
            return records

    def _versions_set(self) -> set[str]:
        if not self._root.is_dir():
            return set()
        return {
            item.name
            for item in self._root.iterdir()
            if item.is_dir() and not item.name.startswith(".")
        }

    def fields_for(self, key: str) -> dict[str, dict[str, object]]:
        record = self._read_record(key)
        if record is None:
            return {}
        return {field["key"]: field for field in record.fields}  # type: ignore[misc]  # TODO(v1.0.3): fix typing

    # ------------------------------------------------------------- installation
    def _make_staging(self) -> Path:
        staging = self._root / f".staging-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        return staging

    def _extract_zip(self, data: bytes, staging: Path) -> dict[str, object]:
        try:
            archive = zipfile.ZipFile(__import__("io").BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise DriverValidationError("上传文件不是有效 ZIP") from exc
        total = 0
        with archive:
            for info in archive.infolist():
                safe = validate_zip_member(info.filename)
                if info.is_dir():
                    continue
                if safe not in {"manifest.json", "driver.py"}:
                    raise DriverValidationError("ZIP 只能包含 manifest.json 与 driver.py")
                if info.file_size > 512_000 or info.compress_size > 512_000:
                    raise DriverValidationError("ZIP 内文件过大")
                total += info.file_size
                if total > 1_000_000:
                    raise DriverValidationError("ZIP 解压后体积过大")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise DriverValidationError("ZIP 不允许符号链接")
                target = staging / safe
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        manifest = validate_driver_directory(staging)
        return manifest

    def _write_py_driver(
        self,
        data: bytes,
        staging: Path,
        key: str | None,
        name: str | None,
        version: str | None,
    ) -> dict[str, object]:
        source = data.decode("utf-8", errors="strict")
        validate_driver_source(source)
        key = (key or "").strip()
        version = (version or "1.0.0").strip()
        manifest = validate_manifest(
            {
                "key": key,
                "name": (name or key).strip(),
                "version": version,
                "entry": "driver.py",
                "fields": [],
            }
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (staging / "driver.py").write_text(source, encoding="utf-8")
        validate_driver_directory(staging)
        return manifest

    def install(
        self,
        data: bytes,
        *,
        filename: str,
        key: str | None = None,
        name: str | None = None,
        version: str | None = None,
    ) -> DriverRecord:
        if not data:
            raise DriverValidationError("上传文件为空")
        if len(data) > settings.upload_max_mb * 1024 * 1024:
            raise DriverValidationError(f"驱动文件不能超过 {settings.upload_max_mb}MB")
        with self._lock:
            staging = self._make_staging()
            try:
                if filename.lower().endswith(".zip") or data[:2] == b"PK":
                    manifest = self._extract_zip(data, staging)
                elif filename.lower().endswith(".py"):
                    manifest = self._write_py_driver(
                        data, staging, key, name, version
                    )
                else:
                    raise DriverValidationError("只支持 .py 或 .zip 驱动包")
                driver_key = manifest["key"]
                driver_version = manifest["version"]
                target = self._driver_dir(driver_key) / driver_version  # type: ignore[arg-type, operator]  # TODO(v1.0.3): fix typing
                if target.exists():
                    raise DriverValidationError(
                        f"驱动 {driver_key} 版本 {driver_version} 已存在"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(staging, target)
            finally:
                shutil.rmtree(staging, ignore_errors=True)

            old_version = self._active_version(driver_key)  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            try:
                module = self._load_module(driver_key, driver_version)  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                if old_version:
                    self._load_module(driver_key, old_version)  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                raise
            self._modules[driver_key] = module  # type: ignore[index]  # TODO(v1.0.3): fix typing
            self._write_active(driver_key, driver_version)  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            self._records[driver_key] = self._read_record(driver_key) or DriverRecord(  # type: ignore[arg-type, index]  # TODO(v1.0.3): fix typing
                key=driver_key,  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                name=manifest["name"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                version=driver_version,  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                description=manifest["description"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                fields=manifest["fields"],  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                builtin=False,
                active_version=driver_version,  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
                versions=self._versions(driver_key),  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            )
            self._prune_versions(driver_key, keep=settings.push_driver_max_versions)  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            logger.info("自定义推送驱动已加载：%s@%s", driver_key, driver_version)
            return self._records[driver_key]  # type: ignore[index]  # TODO(v1.0.3): fix typing

    def _prune_versions(self, key: str, keep: int) -> None:
        versions = self._versions(key)
        active = self._active_version(key)
        removable = [
            version for version in reversed(versions) if version != active
        ]
        for version in removable[: max(0, len(versions) - keep)]:
            shutil.rmtree(self._driver_dir(key) / version, ignore_errors=True)

    def rollback(self, key: str, version: str | None = None) -> DriverRecord:
        with self._lock:
            versions = self._versions(key)
            current = self._active_version(key)
            candidates = [item for item in versions if item != current]
            if version:
                if version not in versions:
                    raise DriverLoadError("目标版本不存在")
                target = version
            elif candidates:
                target = candidates[0]
            else:
                raise DriverLoadError("没有可回滚的历史版本")
            module = self._load_module(key, target)
            self._modules[key] = module
            self._write_active(key, target)
            record = self._read_record(key)
            if record is None:
                raise DriverLoadError("回滚后的 manifest 无法读取")
            logger.info("自定义推送驱动已回滚：%s -> %s", key, target)
            return record

    def delete(self, key: str) -> None:
        with self._lock:
            self._modules.pop(key, None)
            self._records.pop(key, None)
            shutil.rmtree(self._driver_dir(key), ignore_errors=True)
            logger.info("自定义推送驱动已删除：%s", key)

    # ---------------------------------------------------------------- dispatch
    async def send(
        self, key: str, config: dict[str, object], title: str, body: str
    ) -> dict[str, object]:
        with self._lock:
            module = self._modules.get(key)
            if module is None:
                version = self._active_version(key)
                if version is None:
                    raise DriverLoadError(f"推送驱动不存在：{key}")
                module = self._load_module(key, version)
                self._modules[key] = module
        try:
            result = module.send(config, title, body)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise DriverLoadError(
                f"自定义驱动发送失败：{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(result, dict):
            raise DriverLoadError("自定义驱动 send() 必须返回 dict")
        return result


driver_registry = DriverRegistry()
