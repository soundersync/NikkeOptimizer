"""Sidecar tests for the player_data flow.

Stubs PromoExtractedField rows directly (no PaddleOCR), then drives
``process_player_data_tournament`` and asserts the players_lookup.json
output. Keeps the test in the simulator-tier (no PaddleOCR install).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("sqlmodel")

from sqlmodel import Session

from nikke_optimizer.data.db import init_db, make_engine
from nikke_optimizer.data.models import (
    Character,
    PromoExtractedField,
    PromoGroup,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
)
from nikke_optimizer.data.enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)
from nikke_optimizer.roster.promo_tournament_player_data import (
    CharSlot,
    PlayerRecord,
    aggregate_per_player,
    process_player_data_tournament,
    read_sidecar,
    sidecar_path,
)


def _make_char(session: Session, name: str) -> Character:
    """Minimal Character row — every NOT NULL column gets a placeholder."""
    c = Character(
        name=name,
        rarity=Rarity.SSR,
        element=Element.FIRE,
        weapon_class=WeaponClass.SMG,
        manufacturer=Manufacturer.MISSILIS,
        burst_type=BurstType.I,
        source="test",
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _add_field(
    session: Session,
    screenshot_id: int,
    slug: str,
    *,
    text: str | None = None,
    normalized: str | None = None,
    character_id: int | None = None,
    match_score: float | None = None,
    confidence: float | None = None,
) -> None:
    session.add(PromoExtractedField(
        screenshot_id=screenshot_id,
        region_slug=slug,
        text=text,
        normalized=normalized,
        character_id=character_id,
        character_match_score=match_score,
        confidence=confidence,
    ))
    session.commit()


@pytest.fixture
def populated_db(tmp_path: Path):
    """A DB with 1 player_data tournament, 1 group, 1 match, both
    sides populated with fake OCR rows for one fully-stocked top side
    and a sparse bottom side.
    """
    storage_root = tmp_path / "captures" / "beta_season_29" / "promotion_tournament_player_data"
    (storage_root / "group_1" / "round_64" / "match_1").mkdir(parents=True)

    db_path = tmp_path / "test.sqlite3"
    engine = make_engine(db_path)
    init_db(engine)

    with Session(engine) as session:
        moran = _make_char(session, "Moran")
        noise = _make_char(session, "Noise")
        snow_white = _make_char(session, "Snow White")
        noah = _make_char(session, "Noah")
        ada = _make_char(session, "Ada")

        captured = datetime(2026, 5, 11, 11, 33, 53, tzinfo=timezone.utc)
        t = PromoTournament(
            captured_at=captured,
            capture_date=captured.date(),
            storage_root=str(storage_root),
            source_root=None,
        )
        session.add(t)
        session.commit()
        session.refresh(t)

        g = PromoGroup(tournament_id=t.id, group_no=1)
        session.add(g)
        session.commit()
        session.refresh(g)

        match = PromoMatch(
            tournament_id=t.id,
            group_id=g.id,
            round_label="round_64",
            match_no=1,
            has_loadouts=True,
        )
        session.add(match)
        session.commit()
        session.refresh(match)

        # Two screenshots: top (fully populated) + bottom (sparse).
        shot_top = PromoMatchScreenshot(
            match_id=match.id, kind="player_loadout", side="top",
            round_no=None,
            file_path=str(storage_root / "group_1" / "round_64" / "match_1" / "player_top.png"),
        )
        shot_bot = PromoMatchScreenshot(
            match_id=match.id, kind="player_loadout", side="bottom",
            round_no=None,
            file_path=str(storage_root / "group_1" / "round_64" / "match_1" / "player_bottom.png"),
        )
        session.add(shot_top)
        session.add(shot_bot)
        session.commit()
        session.refresh(shot_top)
        session.refresh(shot_bot)

        # Header fields for the top side.
        _add_field(session, shot_top.id, "player_name", text="BBB", confidence=0.95)
        _add_field(session, shot_top.id, "player_level", text="151", normalized="151")
        _add_field(session, shot_top.id, "team_cp", text="3,697,055", normalized="3697055")
        # 5 chars (canonical names already fuzzy-resolved).
        for slot, char, cp in (
            (1, moran, "152840"),
            (2, noise, "155821"),
            (3, snow_white, "161034"),
            (4, noah, "145942"),
            (5, ada, "128417"),
        ):
            _add_field(
                session, shot_top.id, f"char{slot}.name",
                text=char.name, character_id=char.id, match_score=98.0,
            )
            _add_field(
                session, shot_top.id, f"char{slot}.cp",
                text=cp, normalized=cp,
            )
        _add_field(session, shot_top.id, "char1.lb_core", normalized="L3CMAX")
        _add_field(session, shot_top.id, "char3.lb_core", normalized="L2C03")

        # Sparse bottom: just player name + level. No team_cp, no chars.
        _add_field(session, shot_bot.id, "player_name", text="ZTARMAN")
        _add_field(session, shot_bot.id, "player_level", text="169", normalized="169")

        tournament_id = t.id

    return engine, tournament_id, storage_root


def _load_tournament(engine, tournament_id: int) -> PromoTournament:
    with Session(engine) as session:
        return session.get(PromoTournament, tournament_id)


def test_sidecar_writes_with_canonical_char_names(populated_db, tmp_path):
    engine, tournament_id, storage_root = populated_db
    with Session(engine) as session:
        t = session.get(PromoTournament, tournament_id)
        out = process_player_data_tournament(session, t, season_number=29)
    assert out is not None
    assert out == sidecar_path(storage_root)
    raw = json.loads(out.read_text())
    assert raw["season_number"] == 29
    assert raw["tournament_id"] == tournament_id
    assert len(raw["players"]) == 2

    # Records sorted by (group, match, side) — bottom before top.
    bot, top = raw["players"]
    assert bot["side"] == "bottom"
    assert top["side"] == "top"
    assert top["player_name"] == "BBB"
    assert top["player_level"] == 151
    assert top["team_cp"] == 3697055
    names = [c["name"] for c in top["chars"]]
    assert names == ["Moran", "Noise", "Snow White", "Noah", "Ada"]
    cps = [c["cp"] for c in top["chars"]]
    assert cps == [152840, 155821, 161034, 145942, 128417]
    # LB/Core decoded.
    assert top["chars"][0]["lb"] == 3
    assert top["chars"][0]["core"] == "MAX"
    assert top["chars"][2]["lb"] == 2
    assert top["chars"][2]["core"] == "03"

    # Sparse bottom: header set, char rows all-None.
    assert bot["player_name"] == "ZTARMAN"
    assert bot["player_level"] == 169
    assert bot["team_cp"] is None
    assert all(c["name"] is None and c["cp"] is None for c in bot["chars"])


def test_sidecar_idempotent_without_force(populated_db):
    engine, tournament_id, storage_root = populated_db
    with Session(engine) as session:
        t = session.get(PromoTournament, tournament_id)
        first = process_player_data_tournament(session, t, season_number=29)
        assert first is not None
        first_mtime = first.stat().st_mtime
        # Second pass returns None (skipped — sidecar exists).
        again = process_player_data_tournament(session, t, season_number=29)
        assert again is None
        assert first.stat().st_mtime == first_mtime
        # ``force=True`` rewrites.
        forced = process_player_data_tournament(
            session, t, season_number=29, force=True
        )
        assert forced == first


def test_aggregate_per_player_unions_chars_across_rounds():
    """5 per-round records → 1 aggregated record per (group, match, side)
    with the deduped union of chars across rounds.
    """
    rounds = []
    for round_no in range(1, 6):
        # Each round has 5 chars; deliberately overlap Moran (slot 1)
        # across all rounds + a unique char per round in slot 2.
        chars = [
            CharSlot(slot=1, name="Moran", name_raw="Moran",
                     name_match_score=100.0, cp=150_000, lb=3, core="MAX"),
            CharSlot(slot=2, name=f"Unique{round_no}", name_raw=f"Unique{round_no}",
                     name_match_score=98.0, cp=100_000, lb=None, core=None),
            CharSlot(slot=3, name="Helm", name_raw="Helm",
                     name_match_score=100.0, cp=130_000, lb=None, core=None),
            CharSlot(slot=4, name="Crown", name_raw="Crown",
                     name_match_score=100.0, cp=140_000, lb=None, core=None),
            CharSlot(slot=5, name="Liter", name_raw="Liter",
                     name_match_score=100.0, cp=120_000, lb=None, core=None),
        ]
        rounds.append(PlayerRecord(
            group_no=1, match_no=1, side="top",
            screenshot_id=100 + round_no,
            player_name="BBB",
            player_name_confidence=0.9 if round_no != 3 else 0.95,  # round 3 = best
            player_level=151,
            team_cp=3_500_000 + round_no * 50_000,  # increases per round
            chars=chars,
        ))

    out = aggregate_per_player(rounds)
    assert len(out) == 1
    rec = out[0]

    # Header fields from round 3 (highest confidence).
    assert rec.player_name == "BBB"
    assert rec.player_name_confidence == 0.95
    # team_cp = max across rounds (round 5: 3,500,000 + 250,000 = 3,750,000).
    assert rec.team_cp == 3_750_000
    # All 5 source screenshot ids preserved.
    assert rec.source_screenshots == [101, 102, 103, 104, 105]
    # Best screenshot id = round 3's (highest confidence).
    assert rec.screenshot_id == 103

    # Union chars: Moran + 5 Unique-N + Helm + Crown + Liter = 9 unique.
    # First-appearance order = round 1's order, then new entries appear
    # at their first round.
    names = [c.name for c in rec.chars]
    assert names == [
        "Moran", "Unique1", "Helm", "Crown", "Liter",
        "Unique2", "Unique3", "Unique4", "Unique5",
    ]
    # Slots are re-indexed 1-based on the union.
    assert [c.slot for c in rec.chars] == list(range(1, 10))
    # LB/core preserved from the source slot (Moran from round 1).
    assert rec.chars[0].lb == 3
    assert rec.chars[0].core == "MAX"


def test_aggregate_per_player_handles_empty_input():
    assert aggregate_per_player([]) == []


def test_sidecar_auto_invalidates_when_version_mismatches(populated_db):
    """Sidecar files written by an older schema version get
    automatically rewritten on the next process_player_data_tournament
    call, even without force=True. Removes the "forgot --force-ocr"
    foot-gun.
    """
    import json as _json
    from nikke_optimizer.roster.promo_tournament_player_data import (
        SIDECAR_VERSION,
        sidecar_path,
    )

    engine, tournament_id, storage_root = populated_db

    # Plant a sidecar from a "previous schema version".
    stale = sidecar_path(storage_root)
    stale.write_text(_json.dumps({
        "season_number": 29,
        "tournament_id": tournament_id,
        "storage_root": str(storage_root),
        "sidecar_version": SIDECAR_VERSION - 1,
        "players": [],   # deliberately stale content
    }))

    with Session(engine) as session:
        t = session.get(PromoTournament, tournament_id)
        # No force=True — should still rewrite because the on-disk
        # version is stale.
        out = process_player_data_tournament(session, t, season_number=29)
    assert out is not None
    raw = _json.loads(out.read_text())
    assert raw["sidecar_version"] == SIDECAR_VERSION
    # Stale empty players were replaced by the real fixture data.
    assert len(raw["players"]) == 2


def test_aggregate_per_player_keeps_distinct_sides_separate():
    """Same player_name in top vs bottom (e.g. nested tournaments)
    must remain TWO records — the natural key is (group, match, side)."""
    top = PlayerRecord(
        group_no=1, match_no=1, side="top", screenshot_id=1,
        player_name="Same", player_name_confidence=0.9,
        player_level=100, team_cp=1_000_000,
        chars=[CharSlot(slot=1, name="Helm", name_raw="Helm",
                        name_match_score=100.0, cp=100, lb=None, core=None)],
    )
    bot = PlayerRecord(
        group_no=1, match_no=1, side="bottom", screenshot_id=2,
        player_name="Same", player_name_confidence=0.9,
        player_level=200, team_cp=2_000_000,
        chars=[CharSlot(slot=1, name="Crown", name_raw="Crown",
                        name_match_score=100.0, cp=200, lb=None, core=None)],
    )
    out = aggregate_per_player([top, bot])
    assert len(out) == 2
    sides = sorted(r.side for r in out)
    assert sides == ["bottom", "top"]


def test_read_sidecar_roundtrips(populated_db):
    engine, tournament_id, storage_root = populated_db
    with Session(engine) as session:
        t = session.get(PromoTournament, tournament_id)
        process_player_data_tournament(session, t, season_number=29)
    parsed = read_sidecar(storage_root)
    assert parsed is not None
    assert parsed.season_number == 29
    assert parsed.tournament_id == tournament_id
    assert len(parsed.players) == 2
    top = next(p for p in parsed.players if p.side == "top")
    assert top.player_name == "BBB"
    assert top.chars[0].name == "Moran"
    assert top.chars[0].lb == 3
