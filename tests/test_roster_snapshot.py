"""Tests for the per-season roster snapshot module.

Covers:

* Self-snapshot path: copies live OwnedCharacter + AccountState into
  RosterSnapshot / RosterSnapshotCharacter rows.
* CSV-import snapshot path: parses an external player's CSV without
  touching the live OwnedCharacter table; manual research-level
  overrides are persisted on the snapshot row.
* Idempotency: re-running for the same (season, player) replaces.
* Serialization round-trip: the JSON payload contains all
  ``OwnedCharacter`` columns we care about for downstream
  reconstruction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import select

from nikke_optimizer.data.db import get_session, init_db, make_engine
from nikke_optimizer.data.enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)
from nikke_optimizer.data.models import (
    AccountState,
    Character,
    OwnedCharacter,
    RosterSnapshot,
    RosterSnapshotCharacter,
)
from nikke_optimizer.roster.snapshot import (
    get_snapshot,
    import_snapshot_csv,
    list_snapshots_for_season,
    make_self_snapshot,
    serialize_owned,
)


def _seed_characters(engine, names: list[str]) -> dict[str, Character]:
    """Insert minimal Character rows for the names we test against."""
    out: dict[str, Character] = {}
    with get_session(engine) as session:
        for n in names:
            session.add(
                Character(
                    name=n,
                    rarity=Rarity.SSR,
                    element=Element.FIRE,
                    weapon_class=WeaponClass.AR,
                    burst_type=BurstType.I,
                    manufacturer=Manufacturer.ELYSION,
                    role_tags=["Attacker"],
                    source="manual",
                )
            )
        session.commit()
        for n in names:
            out[n] = session.exec(
                select(Character).where(Character.name == n)
            ).first()
    return out


def _seed_owned(engine, *, characters: dict[str, Character]) -> None:
    with get_session(engine) as session:
        for n, ch in characters.items():
            session.add(OwnedCharacter(
                character_id=ch.id,
                power=4_000_000,
                sync_level=600,
                core=7,
                limit_break=3,
                skill1_level=10,
                skill2_level=10,
                burst_skill_level=10,
            ))
        session.commit()


def _seed_account_state(engine, **fields) -> None:
    with get_session(engine) as session:
        state = session.get(AccountState, 1) or AccountState()
        for k, v in fields.items():
            setattr(state, k, v)
        session.add(state)
        session.commit()


def test_make_self_snapshot_copies_live_state(tmp_path: Path):
    db = tmp_path / "test.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    chars = _seed_characters(engine, ["Alpha", "Bravo"])
    _seed_owned(engine, characters=chars)
    _seed_account_state(
        engine,
        synchro_level=667,
        general_research_level=300,
        class_attacker_level=192,
    )

    report = make_self_snapshot(
        season_number=29, player_username="Nika", db_path=db,
    )
    assert report.matched == 2
    assert report.snapshot_id is not None
    assert report.replaced_existing is False

    with get_session(engine) as session:
        snap = get_snapshot(session, season_number=29, player_username="Nika")
        assert snap is not None
        assert snap.synchro_level == 667
        assert snap.general_research_level == 300
        assert snap.class_attacker_level == 192
        chars_in_snap = session.exec(
            select(RosterSnapshotCharacter).where(
                RosterSnapshotCharacter.snapshot_id == snap.id
            )
        ).all()
        assert len(chars_in_snap) == 2
        # Each entry serialized correctly.
        for entry in chars_in_snap:
            assert entry.data["sync_level"] == 600
            assert entry.data["limit_break"] == 3
            assert entry.data["core"] == 7


def test_self_snapshot_replaces_on_rerun(tmp_path: Path):
    db = tmp_path / "test.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    chars = _seed_characters(engine, ["Alpha"])
    _seed_owned(engine, characters=chars)

    first = make_self_snapshot(
        season_number=29, player_username="Nika", db_path=db,
    )
    assert first.replaced_existing is False
    second = make_self_snapshot(
        season_number=29, player_username="Nika", db_path=db,
    )
    assert second.replaced_existing is True

    with get_session(engine) as session:
        snaps = list_snapshots_for_season(session, 29)
        assert len(snaps) == 1
        assert snaps[0].id == second.snapshot_id


def test_snapshots_for_different_players_coexist(tmp_path: Path):
    db = tmp_path / "test.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    chars = _seed_characters(engine, ["Alpha"])
    _seed_owned(engine, characters=chars)

    make_self_snapshot(season_number=29, player_username="Nika", db_path=db)
    make_self_snapshot(season_number=29, player_username="KYUSHEN", db_path=db)

    with get_session(engine) as session:
        snaps = list_snapshots_for_season(session, 29)
        assert sorted(s.player_username for s in snaps) == ["KYUSHEN", "Nika"]


def test_import_snapshot_csv_does_not_touch_live_owned(tmp_path: Path):
    """The CSV importer for snapshots must NOT write to OwnedCharacter
    — it's another player's data, not our roster."""
    db = tmp_path / "test.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    chars = _seed_characters(engine, ["Alpha"])

    # Write a tiny minimal CSV
    csv_path = tmp_path / "kyushen.csv"
    csv_path.write_text(
        "Name,Power,Synchro Level,Class,Manufacturer,Limit Break,Core Level,HP,ATK,DEF\n"
        "Alpha,4000000,667,Attacker,Elysion,3/3,max,9000000,400000,60000\n",
        encoding="utf-8",
    )

    research = {
        "synchro_level": 667,
        "general_research_level": 300,
        "class_attacker_level": 192,
        "mfr_elysion_level": 178,
    }
    report = import_snapshot_csv(
        csv_path=csv_path,
        season_number=29,
        player_username="KYUSHEN",
        research=research,
        db_path=db,
    )
    assert report.matched == 1
    assert report.snapshot_id is not None

    with get_session(engine) as session:
        # Live OwnedCharacter table is untouched (still empty).
        owned = session.exec(select(OwnedCharacter)).all()
        assert owned == []
        # Snapshot row exists with the supplied research overrides.
        snap = get_snapshot(session, season_number=29, player_username="KYUSHEN")
        assert snap is not None
        assert snap.synchro_level == 667
        assert snap.general_research_level == 300
        assert snap.class_attacker_level == 192
        assert snap.mfr_elysion_level == 178
        # Char payload includes the parsed power.
        snap_chars = session.exec(
            select(RosterSnapshotCharacter).where(
                RosterSnapshotCharacter.snapshot_id == snap.id
            )
        ).all()
        assert len(snap_chars) == 1
        assert snap_chars[0].data["power"] == 4000000


def test_serialize_owned_carries_basic_columns(tmp_path: Path):
    db = tmp_path / "test.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    chars = _seed_characters(engine, ["Alpha"])
    _seed_owned(engine, characters=chars)

    with get_session(engine) as session:
        owned = session.exec(select(OwnedCharacter)).first()
        payload = serialize_owned(owned, session=session)

    # Every plain column in our serialization list must be present.
    for key in ("sync_level", "core", "limit_break", "power",
                "skill1_level", "skill2_level", "burst_skill_level"):
        assert key in payload
    assert payload["sync_level"] == 600
    assert payload["limit_break"] == 3
    # Cube fields are present (None when no cube assigned).
    assert payload["battle_cube_name"] is None
    assert payload["arena_cube_name"] is None
    # Relationship lists are present, even when empty.
    assert payload["ol_gear"] == []
    assert payload["buff_summary"] == []
