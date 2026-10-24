"""Synchronous icon loading/decoding, executed in a worker thread."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_ICON_BYTES = 64 * 1024
MAX_ICON_PIXELS = 1024 * 1024


class ModuleIconError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ModuleIconNotFound(ModuleIconError):
    def __init__(self) -> None:
        super().__init__(404, "图标不存在")


class ModuleIconTooLarge(ModuleIconError):
    def __init__(self) -> None:
        super().__init__(413, "图标文件过大")


class ModuleIconInvalid(ModuleIconError):
    def __init__(self) -> None:
        super().__init__(415, "图标格式不合法")


def _decode_pillow(data: bytes, fmt: str) -> bytes:
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != fmt:
                raise UnidentifiedImageError("format mismatch")
            if image.width <= 0 or image.height <= 0:
                raise ValueError("invalid dimensions")
            if image.width * image.height > MAX_ICON_PIXELS:
                raise ValueError("icon dimensions too large")
            rgba = image.convert("RGBA")
            if rgba.width * rgba.height > MAX_ICON_PIXELS:
                raise ValueError("decoded icon dimensions too large")
            output = BytesIO()
            rgba.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ModuleIconInvalid() from exc


def load_icon(candidate: Path) -> tuple[bytes, str, int]:
    """Return (bytes, media_type, mtime_ns); all filesystem work happens here."""
    try:
        stat = candidate.stat()
        if stat.st_size > MAX_ICON_BYTES:
            raise ModuleIconTooLarge()
        data = candidate.read_bytes()
    except ModuleIconError:
        raise
    except (OSError, ValueError) as exc:
        raise ModuleIconNotFound() from exc
    if len(data) > MAX_ICON_BYTES:
        raise ModuleIconTooLarge()

    if data[:4] == b"\x00\x00\x01\x00":
        return _decode_pillow(data, "ICO"), "image/png", stat.st_mtime_ns
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _decode_pillow(data, "PNG"), "image/png", stat.st_mtime_ns

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ModuleIconInvalid() from exc
    text = text.lstrip("\ufeff \t\r\n")
    lowered = text.lower()
    if not (text.startswith("<?xml") or text.startswith("<svg")):
        raise ModuleIconInvalid()
    if any(token in lowered for token in ("<!doctype", "<!entity", "<script", "javascript:")):
        raise ModuleIconInvalid()
    return data, "image/svg+xml", stat.st_mtime_ns
