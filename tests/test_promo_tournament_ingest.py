"""Ingest tests for the Promotion Tournament walker.

Builds a tmp staging tree mirroring the irregular real shape (round_64
with full match folders, top_32 results-only, top_16 single aggregated
results), runs ``ingest_root()`` against it, asserts row counts +
file relocation + idempotency.

Skipped when ``Pillow`` is unavailable since the fixture writes tiny
real PNGs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, select

PIL = pytest.importorskip("PIL.Image")

from nikke_optimizer.data.db import init_db, make_engine
from nikke_optimizer.data.models import (
    PromoGroup,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
)
from nikke_optimizer.roster.promo_tournament_ingest import ingest_root


def _png(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    PIL.new("RGB", (8, 8), color).save(path)
    return path


@pytest.fixture
def staging_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Build a minimal staging tournament with all three round shapes."""
    staging = tmp_path / "champion_arena"
    archive = tmp_path / "captures"
    src = staging / "promotion_tournament_20260505_224544"

    # group_1 / round_64 / match_1 — full structure
    base = src / "group_1" / "round_64" / "match_1"
    for n in range(1, 6):
        _png(base / "player_top" / f"round_{n}.png")
        _png(base / "player_bottom" / f"round_{n}.png")
    _png(base / "results" / "overview.png")
    for n in range(1, 6):
        _png(base / "results" / f"duel_{n}.png")
    # Coord-picker leftovers — must be filtered.
    _png(base / "results" / "duel_1__100_200_300_400__crop.png")
    _png(base / "results" / "overview__10_20_30_40__masked.png")

    # group_1 / round_64 / match_2 — second match in same round
    base2 = src / "group_1" / "round_64" / "match_2"
    for n in range(1, 6):
        _png(base2 / "player_top" / f"round_{n}.png")
        _png(base2 / "player_bottom" / f"round_{n}.png")
    _png(base2 / "results" / "overview.png")
    for n in range(1, 6):
        _png(base2 / "results" / f"duel_{n}.png")

    # group_1 / top_32 / match_1 — results-only
    base3 = src / "group_1" / "top_32" / "match_1"
    _png(base3 / "results" / "overview.png")
    for n in range(1, 6):
        _png(base3 / "results" / f"duel_{n}.png")

    # group_1 / top_16 / results — single aggregated, no match_X
    base4 = src / "group_1" / "top_16" / "results"
    _png(base4 / "overview.png")
    for n in range(1, 6):
        _png(base4 / f"duel_{n}.png")

    return staging, archive


def test_ingest_relocates_and_persists(staging_tree: tuple[Path, Path], tmp_path: Path):
    staging, archive = staging_tree
    db_path = tmp_path / "test.sqlite3"

    stats = ingest_root(staging, archive_root=archive, db_path=db_path)
    assert stats.errors == [], stats.errors
    assert stats.tournaments == 1
    assert stats.groups == 1
    # 2 round_64 matches + 1 top_32 match + 1 top_16 aggregated = 4
    assert stats.matches == 4
    # round_64/match_1: 5+5 loadouts + 1 overview + 5 duels = 16
    # round_64/match_2: 16
    # top_32/match_1:  6
    # top_16:           6
    assert stats.screenshots == 44

    # Files were relocated into the canonical layout.
    canon = archive / "2026-05-05" / "promotion_tournament"
    assert (canon / "group_1" / "round_64" / "match_1" / "player_top" / "round_3.png").is_file()
    assert (canon / "group_1" / "top_16" / "results" / "duel_2.png").is_file()
    # Coord-picker leftovers were *not* copied.
    assert not list((canon / "group_1" / "round_64" / "match_1" / "results").glob("*__*.png"))

    # DB state matches.
    engine = make_engine(db_path)
    init_db(engine)
    with Session(engine) as session:
        tournaments = session.exec(select(PromoTournament)).all()
        assert len(tournaments) == 1
        t = tournaments[0]
        assert t.capture_date.isoformat() == "2026-05-05"
        assert t.captured_at.hour == 22 and t.captured_at.minute == 45
        assert str(canon) == t.storage_root

        groups = session.exec(select(PromoGroup)).all()
        assert len(groups) == 1
        assert groups[0].group_no == 1

        matches = session.exec(select(PromoMatch)).all()
        round_labels = sorted(m.round_label for m in matches)
        assert round_labels == ["round_64", "round_64", "top_16", "top_32"]
        # top_16 has match_no = NULL.
        top16 = next(m for m in matches if m.round_label == "top_16")
        assert top16.match_no is None and top16.has_loadouts is False
        # top_32 results-only.
        top32 = next(m for m in matches if m.round_label == "top_32")
        assert top32.has_loadouts is False
        # round_64 has loadouts.
        assert all(m.has_loadouts for m in matches if m.round_label == "round_64")

        screenshots = session.exec(select(PromoMatchScreenshot)).all()
        assert len(screenshots) == 44
        # Loadout sides correctly tagged.
        loadout_sides = {(s.side, s.round_no) for s in screenshots if s.kind == "player_loadout"}
        assert loadout_sides == {
            (side, n) for side in ("top", "bottom") for n in range(1, 6)
        }


def test_ingest_idempotent(staging_tree: tuple[Path, Path], tmp_path: Path):
    staging, archive = staging_tree
    db_path = tmp_path / "test.sqlite3"

    s1 = ingest_root(staging, archive_root=archive, db_path=db_path)
    s2 = ingest_root(staging, archive_root=archive, db_path=db_path)

    assert s2.tournaments == 0
    assert s2.groups == 0
    assert s2.matches == 0
    assert s2.screenshots == 0
    assert s2.files_copied == 0
    assert s2.files_skipped == s1.files_copied  # all hits, no re-copy

    engine = make_engine(db_path)
    init_db(engine)
    with Session(engine) as session:
        assert len(session.exec(select(PromoTournament)).all()) == 1
        assert len(session.exec(select(PromoMatchScreenshot)).all()) == 44


def test_ingest_move_clears_staging(staging_tree: tuple[Path, Path], tmp_path: Path):
    staging, archive = staging_tree
    db_path = tmp_path / "test.sqlite3"

    src = staging / "promotion_tournament_20260505_224544"
    pngs_before = list(src.rglob("*.png"))
    assert pngs_before  # sanity

    stats = ingest_root(staging, archive_root=archive, move=True, db_path=db_path)
    assert stats.files_moved_deleted > 0

    pngs_after = list(src.rglob("*.png"))
    # Only the coord-picker leftovers should remain (those weren't copied
    # and aren't deleted by move).
    assert all("__" in p.stem for p in pngs_after), pngs_after


def test_ingest_picks_up_archive_only(tmp_path: Path):
    """If a tournament was placed in the archive manually (no staging),
    the ingest still picks it up."""
    archive = tmp_path / "captures"
    canon = archive / "2026-04-01" / "promotion_tournament"
    base = canon / "group_3" / "round_64" / "match_1"
    _png(base / "results" / "overview.png")
    for n in range(1, 6):
        _png(base / "results" / f"duel_{n}.png")

    db_path = tmp_path / "test.sqlite3"
    stats = ingest_root(tmp_path / "no_staging", archive_root=archive, db_path=db_path)
    assert stats.tournaments == 1
    assert stats.matches == 1
    assert stats.screenshots == 6


@pytest.fixture
def duel_staging_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Build a champions_duel staging tournament with qf/sf/finals shape."""
    staging = tmp_path / "champion_arena"
    archive = tmp_path / "captures"
    src = staging / "champions_duel_20260505_211315"

    # Quarterfinals — 4 matches with full structure. NB: match folders
    # use ``matchN`` (no underscore) in champions_duel.
    for k in range(1, 5):
        base = src / "quarterfinals" / f"match{k}"
        for n in range(1, 6):
            _png(base / "player_top" / f"round_{n}.png")
            _png(base / "player_bottom" / f"round_{n}.png")
        _png(base / "results" / "overview.png")
        for n in range(1, 6):
            _png(base / "results" / f"duel_{n}.png")

    # Semifinals — 2 matches, results-only (matches the real capture
    # shape; loadouts are typically only saved for the earliest round).
    for k in range(1, 3):
        base = src / "semifinals" / f"match{k}"
        _png(base / "results" / "overview.png")
        for n in range(1, 6):
            _png(base / "results" / f"duel_{n}.png")

    # Finals — single aggregated, results-only.
    base = src / "finals" / "results"
    _png(base / "overview.png")
    for n in range(1, 6):
        _png(base / f"duel_{n}.png")

    return staging, archive


def test_duel_ingest_relocates_and_persists(
    duel_staging_tree: tuple[Path, Path], tmp_path: Path
):
    staging, archive = duel_staging_tree
    db_path = tmp_path / "test.sqlite3"

    stats = ingest_root(staging, archive_root=archive, db_path=db_path)
    assert stats.errors == [], stats.errors
    assert stats.tournaments == 1
    # Synthetic group_no=1 for the duel — 1 group expected.
    assert stats.groups == 1
    # 4 quarterfinal + 2 semifinal + 1 finals (aggregated) = 7 matches.
    assert stats.matches == 7
    # qf: 4 × 16 (full) = 64
    # sf: 2 × 6  (results-only) = 12
    # finals: 6
    # total = 82
    assert stats.screenshots == 82

    # Files relocated under captures/<date>/champions_duel/
    canon = archive / "2026-05-05" / "champions_duel"
    assert (canon / "quarterfinals" / "match1" / "player_top" / "round_1.png").is_file()
    assert (canon / "finals" / "results" / "overview.png").is_file()

    engine = make_engine(db_path)
    init_db(engine)
    with Session(engine) as session:
        t = session.exec(select(PromoTournament)).first()
        assert t is not None
        assert "champions_duel" in t.storage_root
        # Matches per round.
        matches = session.exec(select(PromoMatch)).all()
        labels = sorted(m.round_label for m in matches)
        assert labels == ["finals"] + ["quarterfinals"] * 4 + ["semifinals"] * 2
        finals = next(m for m in matches if m.round_label == "finals")
        assert finals.match_no is None
        assert finals.has_loadouts is False
        # Quarterfinals have loadouts; semifinals (results-only in this
        # capture) do not.
        assert all(
            m.has_loadouts for m in matches if m.round_label == "quarterfinals"
        )
        assert all(
            not m.has_loadouts for m in matches if m.round_label == "semifinals"
        )


def test_duel_and_promo_coexist(
    staging_tree: tuple[Path, Path],
    duel_staging_tree: tuple[Path, Path],
    tmp_path: Path,
):
    """Both formats on the same date land in sibling folders + DB rows.

    Both fixtures share ``tmp_path`` and write into the same
    ``champion_arena/`` staging dir, so a single ingest pass picks up
    both tournaments naturally.
    """
    # Both fixtures point at the same staging + archive paths.
    promo_staging, archive = staging_tree
    duel_staging, _ = duel_staging_tree
    assert promo_staging == duel_staging  # sanity: they share tmp_path

    db_path = tmp_path / "joint.sqlite3"
    stats = ingest_root(promo_staging, archive_root=archive, db_path=db_path)
    assert stats.errors == []
    assert stats.tournaments == 2

    assert (archive / "2026-05-05" / "promotion_tournament").is_dir()
    assert (archive / "2026-05-05" / "champions_duel").is_dir()


def test_force_creates_suffixed_dir_when_collision(tmp_path: Path):
    """A second tournament on the same date with --force gets a numbered suffix."""
    staging = tmp_path / "champion_arena"
    archive = tmp_path / "captures"

    # First tournament — minimal payload.
    src1 = staging / "promotion_tournament_20260505_010000"
    _png(src1 / "group_1" / "top_16" / "results" / "overview.png")

    # Second tournament — same date, later time.
    src2 = staging / "promotion_tournament_20260505_180000"
    _png(src2 / "group_1" / "top_16" / "results" / "overview.png")

    db_path = tmp_path / "test.sqlite3"
    stats = ingest_root(staging, archive_root=archive, force=True, db_path=db_path)
    assert stats.errors == []
    assert (archive / "2026-05-05" / "promotion_tournament").is_dir()
    assert (archive / "2026-05-05" / "promotion_tournament_2").is_dir()
    assert stats.tournaments == 2
