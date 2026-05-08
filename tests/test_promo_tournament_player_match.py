"""Tests for image-hash-based player identification.

Builds tiny synthetic PIL images so the perceptual hash can be exercised
without depending on the live capture archive.
"""

from __future__ import annotations

import pytest

PIL = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

from nikke_optimizer.roster.promo_tournament_player_match import (
    _phash_8x8,
    _phash_normalized,
    _trim_to_text_bbox,
    hamming_distance,
)


def _named_crop(text: str, *, w: int = 183, h: int = 31, margin_x: int = 0):
    """Build a synthetic name-banner crop: dark background, white text."""
    img = PIL.new("RGB", (w, h), (32, 32, 40))
    draw = ImageDraw.Draw(img)
    draw.text((5 + margin_x, 6), text, fill=(230, 230, 240))
    return img


# ---------------------------------------------------------------------------
# hamming_distance
# ---------------------------------------------------------------------------


def test_hamming_zero_for_identical():
    assert hamming_distance(0xCAFEBABE, 0xCAFEBABE) == 0


def test_hamming_counts_bits():
    assert hamming_distance(0b1100, 0b1010) == 2
    assert hamming_distance(0xFFFF, 0x0000) == 16


# ---------------------------------------------------------------------------
# _phash_8x8 — same input → same hash; different inputs → different
# ---------------------------------------------------------------------------


def test_phash_identical_crops_match_exactly():
    a = _named_crop("ELES")
    b = _named_crop("ELES")  # same render
    assert _phash_8x8(a) == _phash_8x8(b)
    assert hamming_distance(_phash_8x8(a), _phash_8x8(b)) == 0


def test_phash_different_text_distinguishes():
    """Synthetic 8x8 phash on tiny PIL-default-font renders is lossy,
    but two clearly different texts should not collide at distance 0."""
    a = _named_crop("ELES")
    b = _named_crop("CHIGLETS")
    d = hamming_distance(_phash_8x8(a), _phash_8x8(b))
    assert d >= 1, f"different texts collided at distance 0: {d}"


def test_normalized_phash_separates_distinct_players_better():
    """The 32x8 normalized hash captures more horizontal detail —
    lets it differentiate text patterns the 8x8 hash compresses away."""
    a = _named_crop("ELES")
    b = _named_crop("CHIGLETS")
    d = hamming_distance(_phash_normalized(a), _phash_normalized(b))
    assert d >= 8, f"normalized distance for distinct names too low: {d}"


def test_phash_handles_blank_crop():
    blank = PIL.new("RGB", (50, 20), (10, 10, 10))
    h = _phash_8x8(blank)
    assert isinstance(h, int)
    assert 0 <= h < 1 << 64


# ---------------------------------------------------------------------------
# _trim_to_text_bbox — same text at different left margins → similar bbox
# ---------------------------------------------------------------------------


def test_trim_collapses_horizontal_whitespace():
    """Same text rendered at the left edge vs shifted right should
    produce trimmed crops with the same dimensions."""
    a = _named_crop("ELES", margin_x=0)
    b = _named_crop("ELES", margin_x=40)
    ta = _trim_to_text_bbox(a)
    tb = _trim_to_text_bbox(b)
    # Trimmed crops should be the same width — only horizontal
    # whitespace differed.
    assert abs(ta.size[0] - tb.size[0]) <= 2
    assert ta.size[1] == tb.size[1]


def test_normalized_phash_matches_across_margins():
    """The whole point: a player rendered with different surrounding
    whitespace should still hash similarly when normalized."""
    a = _named_crop("ELES", margin_x=0)
    b = _named_crop("ELES", margin_x=40)
    d_plain = hamming_distance(_phash_8x8(a), _phash_8x8(b))
    d_norm = hamming_distance(_phash_normalized(a), _phash_normalized(b))
    # Normalized hash should give a tighter match than plain.
    assert d_norm <= d_plain
    assert d_norm <= 8, f"normalized distance for same-text crops too high: {d_norm}"


def test_trim_handles_pure_blank_gracefully():
    blank = PIL.new("RGB", (50, 20), (40, 40, 40))
    out = _trim_to_text_bbox(blank)
    # Should fall back to original (no glyphs found).
    assert out.size == blank.size
