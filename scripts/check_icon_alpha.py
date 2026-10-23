#!/usr/bin/env python3
"""Verify that an ICO/PNG icon (file or Base64 Data URI) keeps an alpha channel."""

from __future__ import annotations

import argparse
import base64
from io import BytesIO

from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file")
    group.add_argument("--base64", dest="encoded")
    args = parser.parse_args()
    raw = (
        base64.b64decode(args.encoded.split(",", 1)[-1])
        if args.encoded
        else open(args.file, "rb").read()
    )
    with Image.open(BytesIO(raw)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        minimum, maximum = alpha.getextrema()
        print(f"format={image.format} mode={image.mode} alpha_min={minimum} alpha_max={maximum}")
        return 0 if minimum < 255 else 1


if __name__ == "__main__":
    raise SystemExit(main())
