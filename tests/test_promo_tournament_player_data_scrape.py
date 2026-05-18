"""Plan-building tests for the player_data scrape driver.

Network-free: exercises ``dedupe_by_player`` + ``build_plan`` +
``StatusSidecar`` round-trip. The actual lookup/snapshot loop needs
Playwright + cookies and is covered by manual end-to-end runs against
real BlablaLink data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nikke_optimizer.roster.promo_tournament_player_data import (
    CharSlot,
    PlayerDataSidecar,
    PlayerRecord,
)
from nikke_optimizer.roster.promo_tournament_player_data_scrape import (
    STATUS_FOUND,
    STATUS_NO_RESULTS,
    PlayerScrapeRecord,
    StatusSidecar,
    build_plan,
    dedupe_by_player,
)


def _record(
    name: str,
    level: int,
    *,
    group: int = 1,
    match: int = 1,
    side: str = "top",
    team_cp: int | None = 3_000_000,
    char_names: tuple[str, ...] = ("A", "B", "C", "D", "E"),
    confidence: float | None = 0.95,
    screenshot_id: int = 0,
) -> PlayerRecord:
    return PlayerRecord(
        group_no=group,
        match_no=match,
        side=side,
        screenshot_id=screenshot_id,
        player_name=name,
        player_name_confidence=confidence,
        player_level=level,
        team_cp=team_cp,
        chars=[
            CharSlot(slot=i, name=n, name_raw=n, name_match_score=98.0,
                     cp=100_000, lb=None, core=None)
            for i, n in enumerate(char_names, start=1)
        ],
    )


# ---------------------------------------------------------------------------
# dedupe_by_player
# ---------------------------------------------------------------------------


def test_dedupe_drops_empty_names():
    records = [
        _record("", 100),
        _record("  ", 100),
        _record("BBB", 151),
    ]
    out = dedupe_by_player(records)
    assert [r.player_name for r in out] == ["BBB"]


def test_dedupe_keeps_missing_level_for_inspector():
    """Missing-level rows survive dedupe so inspectors can surface them;
    ``build_plan`` filters them when constructing the scrape work list.
    """
    records = [
        _record("BBB", 151),
        PlayerRecord(
            group_no=2, match_no=1, side="top", screenshot_id=1,
            player_name="NoLevel", player_name_confidence=0.9,
            player_level=None, team_cp=None, chars=[],
        ),
    ]
    out = dedupe_by_player(records)
    assert sorted(r.player_name for r in out) == ["BBB", "NoLevel"]


def test_build_plan_skips_missing_level():
    """The scrape can't search without an expected level — those rows
    drop out of the plan even though dedupe keeps them visible."""
    records = [
        _record("BBB", 151),
        PlayerRecord(
            group_no=2, match_no=1, side="top", screenshot_id=1,
            player_name="NoLevel", player_name_confidence=0.9,
            player_level=None, team_cp=None, chars=[],
        ),
    ]
    plan = build_plan(_sidecar(records), _status())
    assert [e.name for e in plan] == ["BBB"]


def test_dedupe_prefers_higher_quality_collision():
    """Same player in two records — keep the one with more populated fields."""
    sparse = _record(
        "Aerin", 200, group=1, match=1, side="top", team_cp=None,
        char_names=("A", None, None, None, None),  # type: ignore[arg-type]
        confidence=0.7,
    )
    rich = _record(
        "Aerin", 200, group=8, match=4, side="bottom",
        team_cp=3_500_000, char_names=("A", "B", "C", "D", "E"),
        confidence=0.9,
    )
    out = dedupe_by_player([sparse, rich])
    assert len(out) == 1
    assert out[0].team_cp == 3_500_000
    assert out[0].side == "bottom"


def test_dedupe_deterministic_on_tie():
    """Two identical-quality records: lowest (group, match, side) wins."""
    a = _record("Tie", 100, group=1, match=2, side="top")
    b = _record("Tie", 100, group=1, match=2, side="bottom")
    out = dedupe_by_player([b, a])  # reversed input
    assert out[0].side == "bottom"  # alphabetical: bottom < top


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------


def _sidecar(records: list[PlayerRecord], season=29, tid=1) -> PlayerDataSidecar:
    return PlayerDataSidecar(
        season_number=season,
        tournament_id=tid,
        storage_root="/tmp/fake",
        players=records,
    )


def _status(found: list[str] = (), tid=1, season=29) -> StatusSidecar:
    return StatusSidecar(
        sidecar_version=1,
        tournament_id=tid,
        season_number=season,
        last_run_at="",
        players={
            n: PlayerScrapeRecord(name=n, level=200, status=STATUS_FOUND)
            for n in found
        },
    )


def test_build_plan_skips_already_found():
    sidecar = _sidecar([
        _record("BBB", 151), _record("ZTARMAN", 169), _record("Aerin", 200),
    ])
    status = _status(found=["Aerin"])
    plan = build_plan(sidecar, status)
    names = [e.name for e in plan]
    assert names == ["BBB", "ZTARMAN"]


def test_build_plan_force_reincludes_found():
    sidecar = _sidecar([_record("BBB", 151), _record("Aerin", 200)])
    status = _status(found=["Aerin"])
    plan = build_plan(sidecar, status, force=True)
    assert {e.name for e in plan} == {"BBB", "Aerin"}


def test_build_plan_only_filters():
    sidecar = _sidecar([
        _record("BBB", 151), _record("ZTARMAN", 169), _record("Aerin", 200),
    ])
    plan = build_plan(sidecar, _status(), only={"bbb", "aerin"})
    assert {e.name for e in plan} == {"BBB", "Aerin"}


def test_build_plan_only_with_skip_doesnt_re_include():
    sidecar = _sidecar([_record("BBB", 151), _record("Aerin", 200)])
    status = _status(found=["Aerin"])
    plan = build_plan(sidecar, status, only={"BBB", "Aerin"}, force=False)
    assert [e.name for e in plan] == ["BBB"]


def test_build_plan_limit_caps_after_sort():
    """``--limit N`` keeps the lexicographically first N players (the
    work list is sorted before cap). Stable so a re-run with the same
    limit hits the same subset.
    """
    sidecar = _sidecar([
        _record("Zed", 100), _record("BBB", 151),
        _record("Charlie", 200), _record("Aerin", 200),
        _record("Mike", 175),
    ])
    plan = build_plan(sidecar, _status(), limit=3)
    assert [e.name for e in plan] == ["Aerin", "BBB", "Charlie"]


def test_build_plan_limit_zero_returns_empty():
    sidecar = _sidecar([_record("BBB", 151), _record("Aerin", 200)])
    plan = build_plan(sidecar, _status(), limit=0)
    assert plan == []


def test_build_plan_limit_larger_than_plan_is_no_op():
    sidecar = _sidecar([_record("BBB", 151), _record("Aerin", 200)])
    plan = build_plan(sidecar, _status(), limit=99)
    assert len(plan) == 2


def test_build_plan_carries_char_names():
    sidecar = _sidecar([
        _record("BBB", 151, char_names=("Moran", "Noise", "Snow White", "Noah", "Ada")),
    ])
    plan = build_plan(sidecar, _status())
    assert plan[0].char_names == ["Moran", "Noise", "Snow White", "Noah", "Ada"]


# ---------------------------------------------------------------------------
# StatusSidecar I/O
# ---------------------------------------------------------------------------


def test_status_sidecar_roundtrip(tmp_path: Path):
    s = StatusSidecar(
        sidecar_version=1, tournament_id=42, season_number=29, last_run_at="",
    )
    s.players["BBB"] = PlayerScrapeRecord(
        name="BBB", level=151, status=STATUS_FOUND,
        snapshot_id=7, snapshotted_at="2026-05-17T00:00:00+00:00",
        actual_level=152, uid="abc==",
        is_roster_private=False, is_outpost_private=False,
        char_names_attempted=["Moran"], char_names_matched=["Moran"],
    )
    s.players["ZTARMAN"] = PlayerScrapeRecord(
        name="ZTARMAN", level=169, status=STATUS_NO_RESULTS,
    )

    s.save(tmp_path)
    loaded = StatusSidecar.load_or_init(
        tmp_path, tournament_id=42, season_number=29,
    )
    assert loaded.tournament_id == 42
    assert loaded.season_number == 29
    assert set(loaded.players.keys()) == {"BBB", "ZTARMAN"}
    assert loaded.players["BBB"].snapshot_id == 7
    assert loaded.players["BBB"].char_names_matched == ["Moran"]
    assert loaded.players["ZTARMAN"].status == STATUS_NO_RESULTS


def test_status_sidecar_init_when_missing(tmp_path: Path):
    s = StatusSidecar.load_or_init(
        tmp_path, tournament_id=99, season_number=30,
    )
    assert s.players == {}
    assert s.tournament_id == 99
    assert s.season_number == 30


def test_status_sidecar_handles_malformed_file(tmp_path: Path):
    (tmp_path / "players_lookup_status.json").write_text("{not json")
    s = StatusSidecar.load_or_init(
        tmp_path, tournament_id=5, season_number=29,
    )
    assert s.players == {}  # fresh init
