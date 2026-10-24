"""Secure installation of uploaded module ZIP archives and module directory removal."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import secrets
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import UploadFile

from ..config import settings

logger = logging.getLogger(__name__)


def _close_quietly(handle: object) -> None:
    try:
        handle.close()  # type: ignore[attr-defined]
    except Exception:
        logger.debug("关闭模块上传临时文件失败", exc_info=True)
from ..module_loader import (
    MODULE_KEY_PATTERN,
    ModuleConfig,
    ModuleConfigError,
    parse_config_file,
    validate_module_key,
)

MAX_FILES = 500
MAX_TOTAL_UNCOMPRESSED = 64 * 1024 * 1024
MAX_SINGLE_UNCOMPRESSED = 24 * 1024 * 1024


class ModuleUploadError(ValueError):
    pass


def _sanitize_key(raw: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "-", raw.strip()).strip("-_").lower()
    candidate = candidate[:70].strip("-_")
    if not candidate:
        candidate = "module-" + secrets.token_hex(4)
    if not candidate[0].isalnum():
        candidate = "m-" + candidate
    if not MODULE_KEY_PATTERN.fullmatch(candidate):
        raise ModuleUploadError("无法从压缩包推断合法的模块标识，请在上传时手动填写模块标识")
    return candidate


def _safe_rel_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    if "\x00" in normalized:
        raise ModuleUploadError("压缩包中包含非法文件名")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise ModuleUploadError(f"压缩包中包含非法路径：{name}")
    if path.parts and re.match(r"^[A-Za-z]:", path.parts[0]):
        raise ModuleUploadError(f"压缩包中包含绝对路径：{name}")
    return path


def _validate_archive(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    infos = zf.infolist()
    if len(infos) > MAX_FILES:
        raise ModuleUploadError(f"压缩包文件数量超过限制（最多 {MAX_FILES} 个）")

    files: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    total_size = 0
    for info in infos:
        raw_name = info.filename
        if raw_name.endswith("/") or info.is_dir():
            continue
        name = raw_name.replace("\\", "/")
        if name.startswith("__MACOSX/") or name.endswith("/.DS_Store") or name == ".DS_Store":
            continue
        path = _safe_rel_path(name)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ModuleUploadError(f"压缩包中不允许包含符号链接：{name}")
        if info.file_size > MAX_SINGLE_UNCOMPRESSED:
            raise ModuleUploadError(f"压缩包中单个文件过大：{name}")
        total_size += info.file_size
        if total_size > MAX_TOTAL_UNCOMPRESSED:
            raise ModuleUploadError("压缩包解压后总大小超过 64 MB 限制")
        files.append((info, path))

    if not files:
        raise ModuleUploadError("压缩包为空或只包含目录")

    config_candidates = [item for item in files if item[1].name == "config.json"]
    if not config_candidates:
        raise ModuleUploadError("压缩包中缺少 config.json")
    if len(config_candidates) > 1:
        raise ModuleUploadError("一个压缩包只能包含一个签到模块（检测到多个 config.json）")
    config_info, config_path = config_candidates[0]
    prefix_parts = config_path.parent.parts
    if len(prefix_parts) > 1:
        raise ModuleUploadError("config.json 必须位于压缩包根目录或一级子目录中")

    main_rel = PurePosixPath(*prefix_parts, "main.py")
    if not any(path == main_rel for _, path in files):
        raise ModuleUploadError("模块根目录中缺少 main.py")

    return files


def _install_zip_sync(
    zip_path: Path,
    zip_filename: str,
    requested_name: str | None,
    overwrite: bool,
    directory_name: str | None = None,
) -> tuple[str, ModuleConfig]:
    modules_dir = settings.modules_dir.resolve()
    modules_dir.mkdir(parents=True, exist_ok=True)

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ModuleUploadError("上传的文件不是有效的 ZIP 压缩包") from exc

    temp_root: Path | None = None
    backup_path: Path | None = None
    target: Path = modules_dir
    try:
        with zf:
            files = _validate_archive(zf)
            config_entry = next(item for item in files if item[1].name == "config.json")
            prefix_parts = config_entry[1].parent.parts

            if requested_name and requested_name.strip():
                key = validate_module_key(requested_name.strip())
            elif prefix_parts:
                key = _sanitize_key(prefix_parts[-1])
            else:
                stem = Path(zip_filename).stem
                key = _sanitize_key(stem)

            physical_directory = validate_module_key(directory_name or key)
            target = modules_dir / physical_directory
            key_directory = modules_dir / key
            if physical_directory != key and key_directory.exists():
                if not target.exists():
                    raise ModuleUploadError(
                        f"检测到 key 目录 modules/{key} 仍存在，但物理目录 "
                        f"modules/{physical_directory} 不存在；请先清理残留目录"
                    )
                raise ModuleUploadError(
                    f"模块标识「{key}」与物理目录「{physical_directory}」同时存在，"
                    "请先清理冲突目录"
                )
            if target.exists() and not overwrite:
                raise ModuleUploadError(
                    f"模块标识「{key}」已存在。如需覆盖，请勾选“覆盖同名模块”。"
                )

            temp_root = Path(
                tempfile.mkdtemp(prefix=".upload-", dir=str(modules_dir))
            )
            extracted_total = 0
            for info, path in files:
                if path.parts[: len(prefix_parts)] != prefix_parts:
                    continue
                relative_parts = path.parts[len(prefix_parts) :]
                if not relative_parts:
                    continue
                destination = (temp_root / Path(*relative_parts)).resolve()
                if temp_root.resolve() not in destination.parents:
                    raise ModuleUploadError("压缩包路径校验失败")
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with zf.open(info) as source, destination.open("wb") as output:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            extracted_total += len(chunk)
                            if extracted_total > MAX_TOTAL_UNCOMPRESSED:
                                raise ModuleUploadError(
                                    "压缩包解压后总大小超过 64 MB 限制"
                                )
                            output.write(chunk)
                except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
                    raise ModuleUploadError(f"解压文件失败：{info.filename}（{exc}）") from exc

        if temp_root is None or target is None:
            raise ModuleUploadError("模块解压目录未就绪")
        if not (temp_root / "config.json").is_file():
            raise ModuleUploadError("解压后未找到 config.json")
        if not (temp_root / "main.py").is_file():
            raise ModuleUploadError("解压后未找到 main.py")
        config = parse_config_file(temp_root / "config.json")

        if target.exists():
            backup = modules_dir / f".backup-{physical_directory}-{secrets.token_hex(4)}"
            backup_path = backup
            os.replace(target, backup)
        try:
            os.replace(temp_root, target)
            temp_root = None
        except OSError:
            if backup_path is not None and backup_path.exists() and not target.exists():
                os.replace(backup_path, target)
                backup_path = None
            raise
        if backup_path is not None and backup_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
            backup_path = None
        return key, config
    finally:
        if temp_root is not None and temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        if backup_path is not None and backup_path.exists() and target is not None:
            if not target.exists():
                os.replace(backup_path, target)


async def install_module_upload(
    upload: UploadFile,
    requested_name: str | None,
    overwrite: bool,
    directory_name: str | None = None,
) -> tuple[str, ModuleConfig]:
    filename = upload.filename or "module.zip"
    if not filename.lower().endswith(".zip"):
        raise ModuleUploadError("目前仅支持上传 .zip 格式的模块压缩包")

    max_bytes = settings.upload_max_mb * 1024 * 1024
    temp_file = tempfile.NamedTemporaryFile(
        prefix="module-upload-", suffix=".zip", dir=str(settings.data_dir), delete=False
    )
    temp_path = Path(temp_file.name)
    total = 0
    try:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ModuleUploadError(
                    f"压缩包超过 {settings.upload_max_mb} MB 上传限制"
                )
            temp_file.write(chunk)
        temp_file.close()
        if total == 0:
            raise ModuleUploadError("上传的文件为空")
        return await asyncio.to_thread(
            _install_zip_sync,
            temp_path,
            filename,
            requested_name,
            overwrite,
            directory_name,
        )
    finally:
        _close_quietly(temp_file)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def remove_module_directory(key: str) -> bool:
    key = validate_module_key(key)
    modules_dir = settings.modules_dir.resolve()
    target = (modules_dir / key).resolve()
    if target.parent != modules_dir:
        raise ModuleUploadError("模块路径非法，拒绝删除")
    original = modules_dir / key
    if original.is_symlink():
        original.unlink()
        return True
    if not target.exists():
        return False
    if not target.is_dir():
        raise ModuleUploadError("目标路径不是模块目录，拒绝删除")
    shutil.rmtree(target)
    return True


def module_directory_exists(key: str) -> bool:
    try:
        validate_module_key(key)
    except ModuleConfigError:
        return False
    return (settings.modules_dir / key).is_dir()
