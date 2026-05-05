"""OCR engine smoke tests using synthetic images.

Real Nikke screenshot fixtures will live under tests/fixtures/screenshots/ once
the user provides them; for now we generate test images programmatically so
this file works on CI / fresh checkouts.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from nikke_optimizer.roster.ocr import recognize, regions_in_bbox

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Apple Vision OCR requires macOS"
)


def _make_text_image(
    text: str,
    *,
    size=(640, 120),
    font_size: int = 48,
    pos: tuple[int, int] = (20, 20),
) -> Image.Image:
    img = Image.new("RGB", size, color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except OSError:
        font = ImageFont.load_default()
    draw.text(pos, text, fill=(0, 0, 0), font=font)
    return img


def test_recognize_simple_string():
    img = _make_text_image("Element Damage Dealt 47.12%")
    regions = recognize(img)
    full = " ".join(r.text for r in regions)
    assert "Element" in full and "Damage" in full
    assert "47.12" in full or "47" in full
    # Vision typically returns confidence well above 0.9 for clean text
    assert any(r.confidence > 0.8 for r in regions)


def test_recognize_returns_pixel_coordinates():
    img = _make_text_image("ATK 18.69%")
    regions = recognize(img)
    assert regions, "expected at least one region"
    for r in regions:
        x, y, w, h = r.bbox
        assert 0 <= x < img.width
        assert 0 <= y < img.height
        assert w > 0 and h > 0
        assert x + w <= img.width
        assert y + h <= img.height


def test_regions_in_bbox_filter():
    # Place text deliberately on the right side; filter to right 60%.
    img = _make_text_image("441165", pos=(360, 30), size=(640, 120))
    regions = recognize(img)
    assert any("441165" in r.text or "441" in r.text for r in regions)
    right_60 = (256, 0, 384, 120)
    filtered = regions_in_bbox(regions, right_60)
    text = " ".join(r.text for r in filtered)
    assert "441165" in text or "441" in text
