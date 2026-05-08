"""Tests for doll/treasure tier classification.

Self-classification: each labeled exemplar should return its own
canonical key at distance ≈ 0. Unknown rejection: a wholly different
crop (e.g. a portrait region) should classify as ``unknown``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

from nikke_optimizer.roster.promo_tournament_doll_match import (
    DISPLAY_LABELS,
    EXEMPLAR_FILES,
    classify_doll_crop,
    clear_exemplar_cache,
    default_label_dir,
    load_exemplars,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_exemplar_cache()
    yield
    clear_exemplar_cache()


def _label_dir() -> Path:
    d = default_label_dir()
    if not d.is_dir():
        pytest.skip(f"labeled exemplars not present at {d}")
    return d


# ---------------------------------------------------------------------------
# Exemplar loading
# ---------------------------------------------------------------------------


def test_default_label_dir_resolves_under_repo():
    d = default_label_dir()
    # Repo-root-relative resolution; doesn't have to exist for this test.
    assert d.name == "labeled-doll-treasure-icons"
    assert d.parent.name == "debug"


def test_load_exemplars_skips_missing_silently(tmp_path):
    # Empty dir → empty result, no exception raised.
    out = load_exemplars(str(tmp_path))
    assert out == {}


def test_load_exemplars_returns_arrays_for_each_present_file():
    d = _label_dir()
    out = load_exemplars(str(d))
    # Every exemplar in EXEMPLAR_FILES that has a file on disk shows up.
    expected = {k for k, fname in EXEMPLAR_FILES.items() if (d / fname).is_file()}
    assert set(out.keys()) == expected
    # Each is a (32, 32, 3) HSV float array in [0, 1].
    for key, arr in out.items():
        assert arr.shape == (32, 32, 3), f"{key}: shape {arr.shape}"
        assert 0.0 <= arr.min() and arr.max() <= 1.0


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_classify_returns_none_when_no_exemplars():
    # No exemplars loaded → None (caller knows the matcher isn't ready).
    crop = PIL.new("RGB", (33, 37), (200, 100, 100))
    assert classify_doll_crop(crop, {}) is None


def test_each_exemplar_self_classifies():
    """Round-trip: load exemplar, classify it as itself, distance ≈ 0."""
    d = _label_dir()
    exemplars = load_exemplars(str(d))
    for key, fname in EXEMPLAR_FILES.items():
        path = d / fname
        if not path.is_file():
            continue
        img = PIL.open(path).convert("RGB")
        result = classify_doll_crop(img, exemplars)
        assert result is not None, f"{key} returned None"
        assert result.canonical_key == key, (
            f"{key} self-classified to {result.canonical_key} (d={result.distance:.5f})"
        )
        assert result.distance < 0.01, (
            f"{key} self-distance unexpectedly high: {result.distance}"
        )
        assert result.display_label == DISPLAY_LABELS[key]


def test_unknown_when_input_is_unrelated():
    """A crop that doesn't look like any exemplar → 'unknown'."""
    d = _label_dir()
    exemplars = load_exemplars(str(d))
    if not exemplars:
        pytest.skip("no exemplars on disk to classify against")
    # A flat magenta rectangle isn't any of the labeled icons.
    crop = PIL.new("RGB", (33, 37), (255, 0, 255))
    result = classify_doll_crop(crop, exemplars)
    assert result is not None
    assert result.canonical_key == "unknown"
    assert result.distance > 0.05
    assert result.display_label == DISPLAY_LABELS["unknown"]


def test_classify_separates_two_known_classes():
    """Each pair of labeled exemplars should rank itself first."""
    d = _label_dir()
    exemplars = load_exemplars(str(d))
    if len(exemplars) < 2:
        pytest.skip("need at least 2 exemplars")
    keys = list(exemplars.keys())
    for k in keys:
        path = d / EXEMPLAR_FILES[k]
        result = classify_doll_crop(PIL.open(path).convert("RGB"), exemplars)
        assert result.canonical_key == k


def test_display_labels_cover_every_canonical_key():
    """Every canonical key (including 'unknown' + future r_max) has
    a display label so the UI never falls back to a raw key."""
    for key in EXEMPLAR_FILES.keys():
        assert key in DISPLAY_LABELS, f"missing display label for {key}"
    assert "unknown" in DISPLAY_LABELS
    assert "r_max" in DISPLAY_LABELS  # placeholder for future exemplar
