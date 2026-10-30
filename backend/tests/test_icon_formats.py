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
