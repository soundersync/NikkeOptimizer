"""Test the arena screenshot importer + ArenaMatch persistence."""

from __future__ import annotations

import sys
from glob import glob
from pathlib import Path

import pytest
from sqlmodel import select

from nikke_optimizer.data.db import (
    default_portrait_library_path,
    get_session,
    init_db,
    make_engine,
)
from nikke_optimizer.data.models import ArenaMatch, Character, CharacterIcon

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Apple Vision OCR required (macOS only)"
)


def _portrait_library() -> Path:
    """Same fallback chain as test_arena.py — prefers the canonical
    user-data location, falls back to the historical fixtures copy."""
    found = default_portrait_library_path()
    if found is not None:
        return found
    fallback = (
        Path(__file__).parent / "fixtures" / "screenshots" / "Portrait_library"
    )
    if fallback.is_dir():
        return fallback
    pytest.skip("no portrait library found")
    raise AssertionError("unreachable")


PORTRAIT_LIBRARY = _portrait_library()


def _real_db_engine():
    p = Path("/tmp/nikke_test.sqlite3")
    if not p.exists():
        pytest.skip("/tmp/nikke_test.sqlite3 not found; run `refresh` first")
    engine = make_engine(p)
    init_db(engine)
    with get_session(engine) as s:
        if len(s.exec(select(Character)).all()) < 100:
            pytest.skip("DB underpopulated")
    return engine


def _build_matcher():
    from nikke_optimizer.roster.portrait_matcher import PortraitMatcher

    if not PORTRAIT_LIBRARY.exists():
        pytest.skip(f"missing portrait library: {PORTRAIT_LIBRARY}")
    engine = _real_db_engine()
    with get_session(engine) as session:
        matcher = PortraitMatcher.from_portrait_library(
            PORTRAIT_LIBRARY, session=session
        )
    if len(matcher) < 100:
        pytest.skip(f"only {len(matcher)} portraits indexed")
    return matcher


def test_import_rookie_pre_battle(tmp_path):
    """Importing the rookie fixture must persist exactly one ArenaMatch row
    with both teams populated and capture_quality metadata stored."""
    from nikke_optimizer.roster.arena_importer import import_arena_screenshots

    matches = glob(
        "tests/fixtures/screenshots/Rookie_Arena/Screenshot*9.37.33*.png"
    )
    assert matches, "rookie fixture missing"
    db_path = tmp_path / "arena.sqlite3"
    matcher = _build_matcher()
    report = import_arena_screenshots(
        [Path(matches[0])],
        matcher,
        db_path=db_path,
        user_username="NIKA",
    )
    assert report.files_seen == 1
    assert report.rookie == 1
    assert report.skipped == 0

    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as session:
        rows = list(session.exec(select(ArenaMatch)).all())
        assert len(rows) == 1
        row = rows[0]
        assert row.mode == "rookie"
        assert len(row.user_team) == 5
        assert len(row.opponent_team) == 5
        # capture_quality must record per-cell metadata for both teams.
        assert "user" in row.capture_quality
        assert "opponent" in row.capture_quality
        assert len(row.capture_quality["user"]["distances"]) == 5
        # The opponent username 'WINTER' is OCR'd from the title strip.
        assert row.opponent_username == "WINTER"


def test_import_champion_arena_info(tmp_path):
    from nikke_optimizer.roster.arena_importer import import_arena_screenshots

    path = Path("tests/fixtures/screenshots/Champion_Arena/IMG_2153.PNG")
    if not path.exists():
        pytest.skip("champion fixture missing")
    db_path = tmp_path / "arena.sqlite3"
    matcher = _build_matcher()
    report = import_arena_screenshots(
        [path], matcher, db_path=db_path, user_username="NIKA"
    )
    assert report.files_seen == 1
    assert report.champion == 1

    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as session:
        row = session.exec(select(ArenaMatch)).one()
        assert row.mode == "champion"
        assert len(row.user_team) == 5
        # Champion captures don't have an opponent team in the popup view.
        assert row.opponent_team == []
        # round_index OCR'd from the screenshot
        assert row.round_index in (1, 2, 3, 4, 5)
        assert "user" in row.capture_quality
