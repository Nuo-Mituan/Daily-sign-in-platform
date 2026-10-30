"""Synchronous icon loading/decoding, executed in a worker thread."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

from PIL import Image, UnidentifiedImageError

try:  # Optional SVG rasterizer; not installed by default.
    import cairosvg as _cairosvg
except ImportError:  # pragma: no cover - depends on deployment extras
    _cairosvg = None

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
                raise ModuleIconTooLarge()
            rgba = image.convert("RGBA")
            if rgba.width * rgba.height > MAX_ICON_PIXELS:
                raise ModuleIconTooLarge()
            output = BytesIO()
            rgba.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except ModuleIconError:
        raise
    except Image.DecompressionBombError as exc:
        raise ModuleIconTooLarge() from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ModuleIconInvalid() from exc


def _detect_icon_format(data: bytes) -> str | None:
    """Identify the real format from magic bytes; never trust the suffix."""
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
    # Skip XML declarations and comments before the root <svg> element.
    while text.startswith("<?xml") or text.startswith("<!--"):
        if text.startswith("<?xml"):
            end = text.find("?>")
        else:
            end = text.find("-->")
        if end < 0:
            return None
        text = text[end + (2 if text.startswith("<?xml") else 3):].lstrip()
    return "SVG" if text.startswith("<svg") else None


_SVG_MALICIOUS_RE = re.compile(
    r"<script|<foreignobject|<!doctype|<!entity|javascript:|"
    r"\bon[a-z]+\s*=|@import|"
    r"url\s*\(\s*['\"]?\s*(?!#|data:image/)|"
    r"href\s*=\s*['\"]\s*(?!#|data:image/)",
    re.IGNORECASE,
)


def _reject_dangerous_svg(data: bytes) -> None:
    """Single malicious-content gate used before any SVG rasterization."""
    lowered = data.decode("utf-8", errors="ignore")
    if _SVG_MALICIOUS_RE.search(lowered):
        raise ModuleIconInvalid()


def _svg_to_png(data: bytes) -> bytes:
    """Rasterize SVG to PNG; reject if no safe rasterizer is available."""
    _reject_dangerous_svg(data)
    if _cairosvg is None:
        raise ModuleIconInvalid()
    try:
        png = _cairosvg.svg2png(bytestring=data)
    except Exception as exc:
        raise ModuleIconInvalid() from exc
    if not png:
        raise ModuleIconInvalid()
    return _decode_pillow(png, "PNG")


def load_icon(candidate: Path) -> tuple[bytes, str, int]:
    """Return (bytes, media_type, mtime_ns); all filesystem work happens here."""
    declared = ICON_FORMAT_BY_SUFFIX.get(candidate.suffix.lower())
    if declared is None:
        raise ModuleIconInvalid()
    try:
        stat = candidate.stat()
        with candidate.open("rb") as handle:
            data = handle.read(MAX_ICON_BYTES + 1)
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
        if len(data) < 22:
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
    return _svg_to_png(data), "image/png", stat.st_mtime_ns
