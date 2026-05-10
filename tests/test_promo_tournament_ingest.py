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

    stats = ingest_root(staging, archive_root=archive, db_path=db_path, ocr=False)
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

    # Files were relocated into the canonical layout (May 5 2026 →
    # Beta Season 28).
    canon = archive / "beta_season_28" / "promotion_tournament"
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

    s1 = ingest_root(staging, archive_root=archive, db_path=db_path, ocr=False)
    s2 = ingest_root(staging, archive_root=archive, db_path=db_path, ocr=False)

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

    stats = ingest_root(staging, archive_root=archive, move=True, db_path=db_path, ocr=False)
    assert stats.files_moved_deleted > 0

    pngs_after = list(src.rglob("*.png"))
    # Only the coord-picker leftovers should remain (those weren't copied
    # and aren't deleted by move).
    assert all("__" in p.stem for p in pngs_after), pngs_after


def test_ingest_picks_up_archive_only(tmp_path: Path):
    """If a tournament was placed in the archive manually (no staging),
    the ingest still picks it up."""
    archive = tmp_path / "captures"
    # Manually placed under the canonical season-based layout
    # (Apr 1 2026 → Beta Season 26).
    canon = archive / "beta_season_26" / "promotion_tournament"
    base = canon / "group_3" / "round_64" / "match_1"
    _png(base / "results" / "overview.png")
    for n in range(1, 6):
        _png(base / "results" / f"duel_{n}.png")

    db_path = tmp_path / "test.sqlite3"
    stats = ingest_root(tmp_path / "no_staging", archive_root=archive, db_path=db_path, ocr=False)
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

    stats = ingest_root(staging, archive_root=archive, db_path=db_path, ocr=False)
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

    # Files relocated under captures/beta_season_<N>/champions_duel/
    # (May 5 2026 → Beta Season 28).
    canon = archive / "beta_season_28" / "champions_duel"
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
    stats = ingest_root(promo_staging, archive_root=archive, db_path=db_path, ocr=False)
    assert stats.errors == []
    assert stats.tournaments == 2

    assert (archive / "beta_season_28" / "promotion_tournament").is_dir()
    assert (archive / "beta_season_28" / "champions_duel").is_dir()


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
    stats = ingest_root(staging, archive_root=archive, force=True, db_path=db_path, ocr=False)
    assert stats.errors == []
    assert (archive / "beta_season_28" / "promotion_tournament").is_dir()
    assert (archive / "beta_season_28" / "promotion_tournament_2").is_dir()
    assert stats.tournaments == 2


@pytest.fixture
def league_staging_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Build a league staging tournament with 4 players + leaderboard.

    Layout mirrors the user's coord-picker output: top-level
    ``leaderboard.png`` + 12 ``leaderboard__<bbox>__crop.png`` files
    (legitimate OCR inputs, must be archived) + 12 ``__masked.png``
    files (visualization-only, must be skipped). Each ``player_<N>/``
    has its own ``loadout/`` (5 rounds) and ``results/`` (overview +
    5 duels).
    """
    season_parent = tmp_path / "beta_season_29_2026-05-09"
    archive = tmp_path / "captures"
    src = season_parent / "league_20260509_202308"

    # Master image: ingest cuts canonical crops from it via the
    # LEADERBOARD_REGIONS constants. Must be large enough for every
    # region's bbox (max y ≈ 1634).
    src.mkdir(parents=True, exist_ok=True)
    PIL.new("RGB", (1080, 2400), (10, 10, 10)).save(src / "leaderboard.png")
    # Coord-picker leftovers — the user produces these to derive the
    # constants; the ingest must filter them out (never archive).
    for bbox in (
        "438_778_684_823", "442_852_729_898", "311_848_379_876",
        "438_1010_686_1055", "443_1080_725_1131", "312_1099_379_1128",
        "439_1259_687_1303", "442_1333_724_1385", "312_1350_379_1377",
        "437_1508_700_1556", "443_1584_726_1633", "312_1601_380_1630",
    ):
        _png(src / f"leaderboard__{bbox}__crop.png")
        _png(src / f"leaderboard__{bbox}__masked.png")

    # 4 players, each with loadout + results.
    for n in range(1, 5):
        for r in range(1, 6):
            _png(src / f"player_{n}" / "loadout" / f"round_{r}.png")
        _png(src / f"player_{n}" / "results" / "overview.png")
        for r in range(1, 6):
            _png(src / f"player_{n}" / "results" / f"duel_{r}.png")

    return season_parent, archive


def test_league_ingest_relocates_and_persists(
    league_staging_tree: tuple[Path, Path], tmp_path: Path
):
    """Relocate league_<TS>/ → captures/beta_season_<N>/league/.

    The season number is taken from the parent staging folder
    (``beta_season_29_2026-05-09``) instead of derived from captured_at,
    so the archive lives under ``beta_season_29`` even though the
    timestamp's date (May 9) also resolves there via the cadence table.
    """
    staging, archive = league_staging_tree
    db_path = tmp_path / "test.sqlite3"

    stats = ingest_root(staging, archive_root=archive, db_path=db_path, ocr=False)
    assert stats.errors == [], stats.errors
    assert stats.tournaments == 1
    assert stats.groups == 1
    # 4 player_N matches.
    assert stats.matches == 4
    # 5 loadouts + 1 overview + 5 duels per player = 11 × 4 = 44.
    assert stats.screenshots == 44

    # Files relocated under captures/beta_season_29/league/.
    canon = archive / "beta_season_29" / "league"
    assert canon.is_dir()
    assert (canon / "leaderboard.png").is_file()
    # Canonical crops produced by cut_leaderboard_crops from the
    # LEADERBOARD_REGIONS constants — slug-named, never numeric-bbox.
    crops = sorted(p.name for p in canon.glob("leaderboard__*__crop.png"))
    assert len(crops) == 12
    assert all("rank" in name for name in crops), crops
    # The user's coord-picker artifacts must NOT have made it across.
    assert not list(canon.glob("*__masked.png"))
    numeric_bbox_crops = [
        p for p in canon.glob("leaderboard__*__crop.png")
        if not any(f"rank{n}_" in p.name for n in (1, 2, 3, 4))
    ]
    assert numeric_bbox_crops == []
    # Per-player files are in place.
    assert (canon / "player_1" / "loadout" / "round_1.png").is_file()
    assert (canon / "player_4" / "results" / "overview.png").is_file()

    # DB rows.
    engine = make_engine(db_path)
    init_db(engine)
    with Session(engine) as session:
        t = session.exec(select(PromoTournament)).first()
        assert t is not None
        assert "league" in t.storage_root
        assert "beta_season_29" in t.storage_root

        matches = session.exec(select(PromoMatch)).all()
        match_nos = sorted(m.match_no for m in matches)
        assert match_nos == [1, 2, 3, 4]
        assert all(m.round_label == "league" for m in matches)
        assert all(m.has_loadouts for m in matches)

        # Loadouts have side=NULL for league (no head-to-head).
        loadouts = [
            s for s in session.exec(select(PromoMatchScreenshot)).all()
            if s.kind == "player_loadout"
        ]
        assert len(loadouts) == 20
        assert all(s.side is None for s in loadouts)


def test_league_archive_only_inherits_season_from_path(tmp_path: Path):
    """A league archive folder placed manually still gets persisted with
    the right season — captured_at is inferred from the season's start
    date."""
    archive = tmp_path / "captures"
    canon = archive / "beta_season_28" / "league"
    _png(canon / "leaderboard.png")
    _png(canon / "player_1" / "loadout" / "round_1.png")
    _png(canon / "player_1" / "results" / "overview.png")

    db_path = tmp_path / "test.sqlite3"
    stats = ingest_root(
        tmp_path / "no_staging", archive_root=archive, db_path=db_path, ocr=False
    )
    assert stats.errors == []
    assert stats.tournaments == 1
    assert stats.matches == 1
    engine = make_engine(db_path)
    init_db(engine)
    with Session(engine) as session:
        t = session.exec(select(PromoTournament)).first()
        # April 23 2026 is the start of Beta Season 28.
        assert t.capture_date.isoformat() == "2026-04-23"
