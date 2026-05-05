"""End-to-end test of arena extractor against user-provided fixtures.

These are exploratory tests — assertions are lenient because feature-print
matching against an in-game UI is imperfect. We log all results so the user
can inspect what was identified.
"""

from __future__ import annotations

import sys
from glob import glob
from pathlib import Path

import pytest
from sqlmodel import select

from nikke_optimizer.data.db import (
    default_db_path,
    default_portrait_library_path,
    get_session,
    init_db,
    make_engine,
)
from nikke_optimizer.data.models import Character, CharacterIcon

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Apple Vision OCR required (macOS only)"
)


def _portrait_library() -> Path:
    """Resolve the labeled portrait library, preferring the canonical
    user-data location over the historical test-fixtures copy.

    Skips the test cleanly if neither exists — the matcher tests can't
    run without a labeled library.
    """
    found = default_portrait_library_path()
    if found is not None:
        return found
    fallback = (
        Path(__file__).parent / "fixtures" / "screenshots" / "Portrait_library"
    )
    if fallback.is_dir():
        return fallback
    pytest.skip(
        "no portrait library found (checked $NIKKE_OPTIMIZER_PORTRAITS, "
        "<user_data_dir>/portraits/, and tests/fixtures/screenshots/Portrait_library/)"
    )
    raise AssertionError("unreachable")  # for type checkers


PORTRAIT_LIBRARY = _portrait_library()


def _real_db_engine():
    """Use the dev DB at /tmp/nikke_test.sqlite3 — populated by previous CLI runs."""
    p = Path("/tmp/nikke_test.sqlite3")
    if not p.exists():
        pytest.skip("/tmp/nikke_test.sqlite3 not found; run `refresh` + `fetch-portraits` first")
    engine = make_engine(p)
    init_db(engine)
    with get_session(engine) as s:
        n_chars = len(s.exec(select(Character)).all())
        n_icons = len(s.exec(select(CharacterIcon)).all())
        if n_chars < 100 or n_icons < 100:
            pytest.skip(f"DB underpopulated (chars={n_chars}, icons={n_icons})")
    return engine


def _build_library_matcher():
    """Build a PortraitMatcher backed by the labeled `Portrait_library/` folder.

    Cached at module level so 335 embeddings aren't recomputed for every test.
    """
    from nikke_optimizer.roster.portrait_matcher import PortraitMatcher

    if not PORTRAIT_LIBRARY.exists():
        pytest.skip(f"portrait library missing: {PORTRAIT_LIBRARY}")
    engine = _real_db_engine()
    with get_session(engine) as session:
        matcher = PortraitMatcher.from_portrait_library(
            PORTRAIT_LIBRARY, session=session
        )
    if len(matcher) < 100:
        pytest.skip(f"only {len(matcher)} portraits indexed")
    return matcher


def _rookie_screenshot() -> Path:
    matches = glob(
        "tests/fixtures/screenshots/Rookie_Arena/Screenshot*9.37.33*.png"
    )
    assert matches, "Rookie_Arena pre-battle screenshot not found"
    return Path(matches[0])


def _champion_team_screenshots() -> list[Path]:
    paths = sorted(glob("tests/fixtures/screenshots/Champion_Arena/IMG_2153.PNG"))
    return [Path(p) for p in paths]


def test_rookie_pre_battle_extraction():
    from nikke_optimizer.roster.arena import extract_pre_battle

    matcher = _build_library_matcher()

    result = extract_pre_battle(_rookie_screenshot(), matcher, user_username="NIKA")
    assert result is not None
    assert result.mode == "rookie"

    def _fmt(d):
        return f"{d:.3f}" if isinstance(d, float) else d

    print(f"\n--- ROOKIE ARENA PRE-BATTLE ---")
    print(f"title raw: {result.raw_title_ocr[:5]}")
    print(f"USER ({result.user_team.player_username}) power={result.user_team.power}")
    for c, b, d in zip(
        result.user_team.characters,
        result.user_team.best_matches,
        result.user_team.portrait_distances,
    ):
        print(f"  - confident={c}  best_match={b}  d={_fmt(d)}")
    print(f"OPPONENT ({result.opponent_team.player_username}) power={result.opponent_team.power}")
    for c, b, d in zip(
        result.opponent_team.characters,
        result.opponent_team.best_matches,
        result.opponent_team.portrait_distances,
    ):
        print(f"  - confident={c}  best_match={b}  d={_fmt(d)}")

    # Pipeline check: every cell produced *some* candidate (matcher index
    # was loaded and rank-1 returned). Confident matches are tracked
    # separately so we can iterate on geometry/preprocessing without making
    # the test brittle.
    best = [
        b
        for t in (result.user_team, result.opponent_team)
        for b in t.best_matches
    ]
    assert len(best) == 10
    assert all(b is not None for b in best), f"some cells returned no candidate: {best}"


def test_champion_arena_info_extraction():
    from nikke_optimizer.roster.arena import extract_champion_arena_info

    matcher = _build_library_matcher()

    paths = _champion_team_screenshots()
    assert paths, "no Champion_Arena fixtures found"
    result = extract_champion_arena_info(paths[0], matcher)
    assert result is not None

    def _fmt(d):
        return f"{d:.3f}" if isinstance(d, float) else d

    print(f"\n--- CHAMPION ARENA INFO ({paths[0].name}) ---")
    print(f"player={result.player_username} round={result.round_index} power={result.total_power}")
    for c, b, d in zip(
        result.team.characters, result.team.best_matches, result.team.portrait_distances
    ):
        print(f"  - confident={c}  best_match={b}  d={_fmt(d)}")
    assert all(b is not None for b in result.team.best_matches)
