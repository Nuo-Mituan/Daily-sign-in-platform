"""Regression tests for raster module icon formats."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.services.module_icon import ModuleIconInvalid, load_icon


@pytest.mark.parametrize(
    ("fmt", "suffix"),
    [("PNG", ".png"), ("JPEG", ".jpg"), ("JPEG", ".jpeg"), ("WEBP", ".webp")],
)
def test_raster_icon_magic_is_normalized_to_png(
    tmp_path: Path, fmt: str, suffix: str
) -> None:
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format=fmt)
    path = tmp_path / f"icon{suffix}"
    path.write_bytes(output.getvalue())

    data, media_type, _ = load_icon(path)

    assert media_type == "image/png"
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_suffix_must_match_magic(tmp_path: Path) -> None:
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    path = tmp_path / "icon.jpg"
    path.write_bytes(output.getvalue())
    with pytest.raises(ModuleIconInvalid):
        load_icon(path)


def test_unknown_icon_extension_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "icon.gif"
    path.write_bytes(b"GIF89a")
    with pytest.raises(ModuleIconInvalid):
        load_icon(path)


@pytest.mark.parametrize(
    "body",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject></foreignObject></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><use href="https://evil.test/x.svg"/></svg>',
    ],
)
def test_svg_xss_patterns_are_rejected(tmp_path: Path, body: bytes) -> None:
    path = tmp_path / "icon.svg"
    path.write_bytes(body)
    with pytest.raises(ModuleIconInvalid):
        load_icon(path)


def test_oversized_dimensions_return_413(tmp_path: Path) -> None:
    from app.services.module_icon import ModuleIconTooLarge

    path = tmp_path / "icon.png"
    Image.new("RGB", (1025, 1025), "red").save(path, format="PNG")
    with pytest.raises(ModuleIconTooLarge):
        load_icon(path)


def test_svg_response_has_hardening_headers() -> None:
    from app.routers.modules import _icon_response

    response = _icon_response(b"<svg/>", "image/svg+xml")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "attachment"
    assert response.headers["content-security-policy"] == "default-src 'none'"
