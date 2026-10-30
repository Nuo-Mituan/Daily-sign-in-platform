"""Synchronous icon loading/decoding, executed in a worker thread."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_ICON_BYTES = 64 * 1024
MAX_ICON_PIXELS = 1024 * 1024
# Path-based icons: declared suffix must match the detected file signature.
ICON_FORMAT_BY_SUFFIX = {
    ".ico": "ICO",
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".svg": "SVG",
}

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
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise ModuleIconInvalid() from exc


def _detect_icon_format(data: bytes) -> str | None:
    """Detect the real format from magic bytes; never trust the suffix."""
    if data[:4] == b"\x00\x00\x01\x00":
        return "ICO"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "WEBP"
    try:
        text = data.decode("utf-8", errors="strict").lstrip("\ufeff \t\r\n")
    except UnicodeDecodeError:
        return None
    lowered = text.lower()
    if not (text.startswith("<?xml") or text.startswith("<svg")):
        return None
    if any(token in lowered for token in (
        "<!doctype", "<!entity", "<script", "javascript:"
    )):
        return None
    return "SVG"


def load_icon(candidate: Path) -> tuple[bytes, str, int]:
    """Return (bytes, media_type, mtime_ns); all filesystem work happens here."""
    declared = ICON_FORMAT_BY_SUFFIX.get(candidate.suffix.lower())
    if declared is None:
        raise ModuleIconInvalid()
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

    actual = _detect_icon_format(data)
    if actual is None or actual != declared:
        raise ModuleIconInvalid()

    if actual == "ICO":
        if len(data) < 22 or data[2:4] != b"\x01\x00":
            raise ModuleIconInvalid()
        count = int.from_bytes(data[4:6], "little")
        if count <= 0:
            raise ModuleIconInvalid()
        width = data[6] or 256
        height = data[7] or 256
        if not (0 < width <= 256 and 0 < height <= 256):
            raise ModuleIconInvalid()
    if actual in {"ICO", "PNG", "JPEG", "WEBP"}:
        # Raster icons are normalized to PNG so the response MIME always
        # matches the actual bytes, including JPEG/WebP inputs.
        return _decode_pillow(data, actual), "image/png", stat.st_mtime_ns
    return data, "image/svg+xml", stat.st_mtime_ns
