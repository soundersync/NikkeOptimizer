"""Pure-logic tests for the Vision-feature-print doll classifier.

Uses a stub embedder so the test suite stays fast and runs on
non-macOS environments where pyobjc-Vision isn't installed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

PIL = pytest.importorskip("PIL.Image")

from nikke_optimizer.roster.promo_tournament_doll_vision import (
    DollVisionMatcher,
    _IndexEntry,
)


# ---------------------------------------------------------------------------
# Stub embedder — turns each image into an opaque "embedding" object whose
# `compute_distance` is a deterministic function. We don't need real Vision
# semantics here, just something that behaves like a metric.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeEmbedding:
    """Carries a single int "feature" so distance is just |a - b|."""

    feature: int


class _StubEmbedder:
    """Embedder substitute: maps PIL crops to integer features.

    We assign features by inspecting the image's first pixel — tests
    construct crops with specific colours so they map to known features.
    """

    def embed_pil(self, image):
        # Use the average R channel as the feature so similar-coloured
        # crops cluster together.
        if image.mode != "RGB":
            image = image.convert("RGB")
        pixels = list(image.getdata())
        avg_r = sum(p[0] for p in pixels) // len(pixels)
        return _FakeEmbedding(feature=avg_r)

    @staticmethod
    def compute_distance(a, b) -> float:
        return float(abs(a.feature - b.feature))


def _crop(r: int) -> "PIL.Image":
    """A tiny 8×8 crop filled with a single red value."""
    return PIL.new("RGB", (8, 8), (r, 0, 0))


# ---------------------------------------------------------------------------
# Empty matcher → None
# ---------------------------------------------------------------------------


def test_empty_matcher_returns_none():
    m = DollVisionMatcher(embedder=_StubEmbedder())
    assert m.match(_crop(100)) is None
    assert len(m) == 0
    assert m.coverage() == {}


# ---------------------------------------------------------------------------
# Manually-seeded matcher: classification by k-NN majority vote
# ---------------------------------------------------------------------------


def _seed(matcher, *triples):
    """Inject ``(feature, class, field_id)`` rows into the matcher index."""
    for feature, normalized, field_id in triples:
        matcher._index.append(_IndexEntry(
            embedding=_FakeEmbedding(feature=feature),
            field_id=field_id,
            normalized=normalized,
            screenshot_id=field_id,
            region_slug="char1.doll",
        ))


def test_classifies_to_majority_class():
    """Five neighbours: 3 sr_max, 2 r_partial → wins sr_max."""
    m = DollVisionMatcher(embedder=_StubEmbedder())
    _seed(
        m,
        (10, "sr_max", 1),
        (11, "sr_max", 2),
        (12, "sr_max", 3),
        (50, "r_partial", 4),
        (51, "r_partial", 5),
    )
    result = m.match(_crop(11), k=5)
    assert result is not None
    assert result.canonical_key == "sr_max"
    assert result.n_voting == 3


def test_self_match_distance_zero():
    """An exact-feature seed matches itself at distance 0 with full confidence."""
    m = DollVisionMatcher(embedder=_StubEmbedder())
    _seed(m, (42, "sr_max", 7))
    result = m.match(_crop(42), k=1)
    assert result is not None
    assert result.canonical_key == "sr_max"
    assert result.distance == 0.0
    assert result.confidence == 1.0


def test_exclude_field_id_avoids_self_match():
    """``exclude_field_id`` lets the diagnostic command skip a row's own entry."""
    m = DollVisionMatcher(embedder=_StubEmbedder())
    _seed(
        m,
        (42, "sr_max", 7),       # same field as the query — should be excluded
        (45, "sr_partial", 8),   # closer once 7 is gone
        (46, "sr_partial", 9),
    )
    result = m.match(_crop(42), k=2, exclude_field_id=7)
    assert result is not None
    assert result.canonical_key == "sr_partial"  # 7 was excluded → 8/9 win


def test_unknown_when_no_neighbour_close_enough():
    """When the best mean distance is above the no-match threshold,
    classify as unknown."""
    m = DollVisionMatcher(embedder=_StubEmbedder())
    _seed(m, (10, "sr_max", 1), (11, "sr_max", 2))
    # Query is very far away (feature 200 vs neighbours at 10–11).
    result = m.match(_crop(200), k=2)
    assert result is not None
    assert result.canonical_key == "unknown"
    assert result.confidence == 0.0


def test_coverage_counts_per_class():
    m = DollVisionMatcher(embedder=_StubEmbedder())
    _seed(
        m,
        (10, "sr_max", 1),
        (11, "sr_max", 2),
        (50, "r_partial", 3),
    )
    cov = m.coverage()
    assert cov == {"sr_max": 2, "r_partial": 1}


def test_tie_breaker_prefers_lower_mean_distance():
    """When two classes tie on votes, the one whose voters are closer
    to the query wins."""
    m = DollVisionMatcher(embedder=_StubEmbedder())
    _seed(
        m,
        (50, "sr_max", 1),       # distance |50-100| = 50
        (60, "sr_max", 2),       # distance |60-100| = 40
        (140, "treasure_max", 3),  # distance |140-100| = 40
        (150, "treasure_max", 4),  # distance |150-100| = 50
    )
    # k=4 — vote count is 2-2, mean distance is 45 vs 45 (tied).
    # Switch the query so sr_max is closer.
    result = m.match(_crop(80), k=4)
    assert result is not None
    # sr_max distances: 30, 20 → mean 25; treasure_max: 60, 70 → mean 65.
    # Both 2 votes → tie broken by lowest mean → sr_max wins.
    assert result.canonical_key == "sr_max"
