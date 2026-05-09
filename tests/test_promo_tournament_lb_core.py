"""Tests for the LB-stars + Core-badge detector.

Six fixture crops cover the full state space:
* lb0.png             — 3 grey stars (LB 0, no badge)
* lb1.png             — 1 yellow + 2 grey (LB 1, no badge)
* lb2_purple_bg.png   — 2 yellow + 1 grey, character has a purple rank-icon
                        background (no Core badge — guards against false-
                        positive badge detection on purple-bg chars)
* lb3_core0.png       — 3 yellow stars (MLB Core 0, no badge)
* lb3_core2.png       — 3 yellow stars + Core badge "02"
* lb3_max.png         — 3 yellow stars + Core badge "MAX"

Star detection is pure pixel work and runs without any deps beyond PIL +
numpy. Badge OCR uses a stub ``ocr_fn`` so the suite doesn't require
PaddleOCR. (Real Paddle calls are exercised by the ingest pipeline.)
"""
from __future__ import annotations

from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
np = pytest.importorskip("numpy")

from PIL import Image  # noqa: E402

from nikke_optimizer.roster.promo_tournament_lb_core import (  # noqa: E402
    LbCoreResult,
    detect_lb_core,
)


_FIXTURES = Path(__file__).parent / "fixtures" / "lb_core"


def _stub_ocr_for(text: str, conf: float = 0.99):
    """Return an ``ocr_fn`` callable that always yields one fake result."""
    def _fn(_img):
        return [(None, text, conf)]
    return _fn


def _empty_ocr(_img):
    return []


# ---------------------------------------------------------------------------
# Star count + badge presence (no OCR)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture,expected_stars,expected_badge",
    [
        ("lb0.png", 0, False),
        ("lb1.png", 1, False),
        ("lb2_purple_bg.png", 2, False),
        ("lb3_core0.png", 3, False),
        ("lb3_core2.png", 3, True),
        ("lb3_max.png", 3, True),
    ],
)
def test_star_count_and_badge_presence(fixture, expected_stars, expected_badge):
    img = Image.open(_FIXTURES / fixture)
    result = detect_lb_core(img, _empty_ocr)
    assert result.stars == expected_stars, f"{fixture}: stars"
    assert result.badge_present == expected_badge, f"{fixture}: badge"


def test_invariant_badge_implies_three_stars():
    """Every badge-present crop must read as MLB (LB 3)."""
    for png in sorted(_FIXTURES.glob("*.png")):
        img = Image.open(png)
        r = detect_lb_core(img, _empty_ocr)
        if r.badge_present:
            assert r.stars == 3, f"{png.name}: badge present but stars={r.stars}"


# ---------------------------------------------------------------------------
# Badge OCR + normalization
# ---------------------------------------------------------------------------


def test_badge_value_digit():
    img = Image.open(_FIXTURES / "lb3_core2.png")
    r = detect_lb_core(img, _stub_ocr_for("02"))
    assert r.core == 2
    assert r.badge_text == "02"
    assert r.normalized == "mlb_c2"
    assert r.text == "3 stars + 02"


def test_badge_value_max_maps_to_seven():
    img = Image.open(_FIXTURES / "lb3_max.png")
    r = detect_lb_core(img, _stub_ocr_for("MAX"))
    assert r.core == 7
    assert r.normalized == "mlb_max"
    assert r.text == "3 stars + MAX"


def test_badge_value_unparseable_falls_to_unknown():
    img = Image.open(_FIXTURES / "lb3_core2.png")
    r = detect_lb_core(img, _stub_ocr_for("???"))
    assert r.core is None
    # Badge present but OCR returned garbage → unknown class.
    assert r.normalized == "unknown"


def test_no_badge_implies_core_zero_when_mlb():
    """LB=3 with no badge → Core 0 (the badge is hidden when Core=0)."""
    img = Image.open(_FIXTURES / "lb3_core0.png")
    r = detect_lb_core(img, _empty_ocr)
    assert r.stars == 3
    assert r.badge_present is False
    assert r.core is None
    assert r.normalized == "mlb_c0"


def test_partial_lb_class_key():
    """LB<3 → ``lb<n>`` class key."""
    img = Image.open(_FIXTURES / "lb1.png")
    r = detect_lb_core(img, _empty_ocr)
    assert r.normalized == "lb1"
    assert r.text == "1 star"


def test_lb0_renders_zero_stars():
    img = Image.open(_FIXTURES / "lb0.png")
    r = detect_lb_core(img, _empty_ocr)
    assert r.stars == 0
    assert r.normalized == "lb0"
    assert r.text == "0 stars"


# ---------------------------------------------------------------------------
# LbCoreResult shape
# ---------------------------------------------------------------------------


def test_lbcore_result_is_frozen():
    """LbCoreResult is a frozen dataclass — immutable across passes."""
    r = LbCoreResult(stars=3, core=7, badge_present=True, badge_text="MAX", confidence=0.99)
    with pytest.raises(Exception):
        r.stars = 0  # type: ignore[misc]
