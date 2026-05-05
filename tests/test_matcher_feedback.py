"""Matcher feedback loop tests for slice #135.

Covers:
  * discover_feedback_exemplars walks feedback/<Character>/ correctly
  * resolve_library includes feedback exemplars (resolved against db_names)
  * PortraitMatcher.add_exemplar appends to the running index

Uses a fake embedder + monkey-patched compute_distance so tests don't
depend on Apple Vision (pyobjc) being installed — they pass in any
pure-Python environment.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest

if importlib.util.find_spec("PIL") is None:  # pragma: no cover
    pytest.skip("PIL not available", allow_module_level=True)


from PIL import Image  # noqa: E402

from nikke_copilot.roster import portrait_library  # noqa: E402
from nikke_copilot.roster.portrait_library import (  # noqa: E402
    discover_feedback_exemplars,
    resolve_library,
)
from nikke_copilot.roster.portrait_matcher import PortraitMatcher  # noqa: E402


@dataclass
class _FakeEmbedding:
    """Stand-in for Apple's VNFeaturePrintObservation."""
    fingerprint: bytes


class _FakeEmbedder:
    """Embedder that hashes raw image bytes — deterministic and no native deps."""

    def embed_pil(self, image: Image.Image) -> _FakeEmbedding:
        # Reduce to a tiny size so identical-content crops produce identical
        # fingerprints regardless of source resolution.
        small = image.resize((8, 8)).convert("RGB")
        return _FakeEmbedding(fingerprint=small.tobytes())

    def embed_path(self, path: Path) -> _FakeEmbedding:
        return self.embed_pil(Image.open(path).convert("RGB"))


def _fake_distance(a: _FakeEmbedding, b: _FakeEmbedding) -> float:
    """Stand-in for Apple's VN feature-print distance: byte-wise L2."""
    if not isinstance(a, _FakeEmbedding) or not isinstance(b, _FakeEmbedding):
        return float("inf")
    if len(a.fingerprint) != len(b.fingerprint):
        return float("inf")
    return float(
        sum((x - y) ** 2 for x, y in zip(a.fingerprint, b.fingerprint)) ** 0.5
    )


@pytest.fixture(autouse=True)
def _patch_distance(monkeypatch):
    """Replace the native compute_distance with a Python-only L2 metric."""
    from nikke_copilot.roster import _vision_features
    monkeypatch.setattr(
        _vision_features.FeaturePrintEmbedder,
        "compute_distance",
        staticmethod(_fake_distance),
    )


def _color_image(color: tuple[int, int, int], size: int = 64) -> Image.Image:
    return Image.new("RGB", (size, size), color)


class TestDiscoverFeedbackExemplars:
    def test_walks_character_subdirs(self, tmp_path: Path):
        lib = tmp_path / "lib"
        (lib / "feedback" / "Crow").mkdir(parents=True)
        (lib / "feedback" / "Crown").mkdir(parents=True)
        _color_image((10, 20, 30)).save(
            lib / "feedback" / "Crow" / "1.webp", "WEBP"
        )
        _color_image((40, 50, 60)).save(
            lib / "feedback" / "Crow" / "2.png", "PNG"
        )
        _color_image((70, 80, 90)).save(
            lib / "feedback" / "Crown" / "1.webp", "WEBP"
        )
        out = discover_feedback_exemplars(lib)
        chars = sorted({name for _, name in out})
        assert chars == ["Crow", "Crown"]
        # 2 Crow + 1 Crown = 3 total
        assert len(out) == 3

    def test_returns_empty_when_no_feedback_dir(self, tmp_path: Path):
        lib = tmp_path / "lib"
        lib.mkdir()
        assert discover_feedback_exemplars(lib) == []


class TestResolveLibraryWithFeedback:
    def test_feedback_exemplars_are_marked_feedback(self, tmp_path: Path):
        lib = tmp_path / "lib"
        (lib / "feedback" / "Crow").mkdir(parents=True)
        _color_image((1, 2, 3)).save(
            lib / "feedback" / "Crow" / "1.webp", "WEBP"
        )
        entries = resolve_library(lib, db_names=["Crow", "Crown"])
        feedback_entries = [e for e in entries if e.resolution == "feedback"]
        assert len(feedback_entries) == 1
        assert feedback_entries[0].character_name == "Crow"
        assert feedback_entries[0].skin_name == "feedback"

    def test_unknown_character_dir_marked_unresolved(self, tmp_path: Path):
        lib = tmp_path / "lib"
        (lib / "feedback" / "TotallyFakeNikke").mkdir(parents=True)
        _color_image((1, 2, 3)).save(
            lib / "feedback" / "TotallyFakeNikke" / "1.webp", "WEBP"
        )
        entries = resolve_library(lib, db_names=["Crow"])
        unresolved = [e for e in entries if e.resolution == "feedback-unresolved"]
        assert len(unresolved) == 1
        assert unresolved[0].character_name is None


class TestAddExemplar:
    def test_appends_to_index(self):
        matcher = PortraitMatcher(embedder=_FakeEmbedder())
        assert len(matcher) == 0
        matcher.add_exemplar("Crow", _color_image((10, 20, 30)))
        assert len(matcher) == 1

    def test_named_exemplar_wins_over_unrelated(self):
        """Adding an in-game-style Crow exemplar should make Crow win on a
        similar image even when other characters are also indexed."""
        matcher = PortraitMatcher(embedder=_FakeEmbedder())
        # Index a Crown exemplar (catalog art).
        matcher.add_exemplar("Crown", _color_image((100, 200, 50)))
        # Now add a Crow exemplar matching a specific in-game crop colour.
        in_game_crop = _color_image((10, 20, 30))
        matcher.add_exemplar("Crow", in_game_crop)
        # Query with the same crop — Crow should rank #1.
        match = matcher.match_best(in_game_crop)
        assert match is not None
        assert match.character_name == "Crow"

    def test_returns_false_on_embed_failure(self):
        class _BrokenEmbedder:
            def embed_pil(self, image):  # noqa: D401
                raise RuntimeError("boom")
            def embed_path(self, path):
                raise RuntimeError("boom")
        matcher = PortraitMatcher(embedder=_BrokenEmbedder())
        ok = matcher.add_exemplar("Crow", _color_image((1, 2, 3)))
        assert ok is False
        assert len(matcher) == 0
