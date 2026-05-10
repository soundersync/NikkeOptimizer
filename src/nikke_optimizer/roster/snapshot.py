"""Per-season roster snapshots.

Two persistence paths:

* :func:`make_self_snapshot` — copies the current ``OwnedCharacter`` +
  ``AccountState`` rows into ``RosterSnapshot`` / ``RosterSnapshotCharacter``.
  Use at season start to lock in your own roster as the season's
  reference; subsequent CSV imports won't disturb the snapshot.

* :func:`import_snapshot_csv` — parses another player's roster CSV
  (without writing to OwnedCharacter), pairs it with manually-supplied
  research levels + synchro level, and writes a snapshot under that
  player's name. The shared row-parsing logic
  (``csv_importer.build_owned_from_row``) handles cube upserts +
  Doll/Treasure parsing identically to live import.

Both paths replace any prior snapshot for the same
``(season_number, player_username)`` so re-runs are idempotent. Per-character
data is serialized as JSON so the snapshot table doesn't have to mirror
every column of ``OwnedCharacter`` — :func:`deserialize_owned`
reconstructs a transient ``OwnedCharacter`` instance for downstream
consumers (simulator, tournament viewer).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from sqlmodel import Session, delete, select

from ..data.db import get_session, init_db, make_engine
from ..data.models import (
    AccountState,
    Character,
    Cube,
    OLGear,
    OLGearBonus,
    OwnedCharacter,
    RosterSnapshot,
    RosterSnapshotCharacter,
)
from .csv_importer import (
    COLUMN_ALIASES,
    REQUIRED_COLUMNS,
    ImportReport,
    _find_character,
    _is_v2_format,
    _normalize_row,
    build_owned_from_row,
)

log = logging.getLogger(__name__)


# Account-level fields shared between AccountState and RosterSnapshot.
_RESEARCH_FIELDS: tuple[str, ...] = (
    "synchro_level",
    "general_research_level",
    "class_attacker_level",
    "class_defender_level",
    "class_supporter_level",
    "mfr_pilgrim_level",
    "mfr_elysion_level",
    "mfr_tetra_level",
    "mfr_missilis_level",
    "mfr_abnormal_level",
)

# Plain-column subset of OwnedCharacter to serialize. Excludes id,
# character_id (carried separately on the snapshot row), and
# imported_at (re-derived at deserialization time if needed).
_OWNED_COLUMNS: tuple[str, ...] = (
    "sync_level", "core", "limit_break", "star_count", "phase",
    "skill1_level", "skill2_level", "burst_skill_level",
    "burst_cooldown_seconds",
    "skill1_name", "skill2_name", "burst_name",
    "skill1_description", "skill2_description", "burst_description",
    "rank", "squad", "manufacturer_level",
    "power", "total_hp", "total_atk", "total_def",
    "power_bonus", "hp_bonus", "atk_bonus", "def_bonus",
    "bond_rank", "bond_hp", "bond_def", "bond_atk",
    "class_rank_level", "class_rank_hp", "class_rank_def", "class_rank_atk",
    "mfr_rank_level", "mfr_rank_hp", "mfr_rank_def", "mfr_rank_atk",
    "treasure_name", "treasure_phase",
    "treasure_atk", "treasure_def", "treasure_hp",
    "treasure_rarity", "treasure_skill_levels",
    "costumes",
    "source_screenshot", "raw_ocr",
)


@dataclass
class SnapshotReport:
    """Summary returned by both snapshot entry points."""

    snapshot_id: Optional[int] = None
    season_number: int = 0
    player_username: str = ""
    matched: int = 0
    unmatched: int = 0
    rows_seen: int = 0
    cubes_upserted: int = 0
    warnings: list[str] = field(default_factory=list)
    replaced_existing: bool = False

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "season_number": self.season_number,
            "player_username": self.player_username,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "rows_seen": self.rows_seen,
            "cubes_upserted": self.cubes_upserted,
            "replaced_existing": self.replaced_existing,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_owned(owned: OwnedCharacter, *, session: Session) -> dict:
    """Render an ``OwnedCharacter`` instance (transient or persisted)
    as a JSON-safe dict.

    Cubes are referenced by name (not id) so the snapshot stays valid
    even if cube IDs are reassigned later. ``ol_gear`` and
    ``buff_summary`` relationships are inlined as nested lists.
    """
    payload: dict = {col: getattr(owned, col, None) for col in _OWNED_COLUMNS}
    payload["battle_cube_name"] = _cube_name(session, owned.battle_cube_id)
    payload["arena_cube_name"] = _cube_name(session, owned.arena_cube_id)
    payload["ol_gear"] = [_serialize_gear(g) for g in (owned.ol_gear or [])]
    payload["buff_summary"] = [
        {
            "bonus_type": b.bonus_type.value if b.bonus_type else None,
            "raw_label": b.raw_label,
            "percent": b.percent,
            "bonus_amount": b.bonus_amount,
            "highlighted": b.highlighted,
            "text_confidence": b.text_confidence,
        }
        for b in (owned.buff_summary or [])
    ]
    return payload


def _cube_name(session: Session, cube_id: Optional[int]) -> Optional[str]:
    if cube_id is None:
        return None
    cube = session.get(Cube, cube_id)
    return cube.name if cube else None


def _serialize_gear(gear: OLGear) -> dict:
    return {
        "slot": gear.slot.value if gear.slot else None,
        "base_hp": gear.base_hp,
        "base_atk": gear.base_atk,
        "base_def": gear.base_def,
        "icon_confidence": gear.icon_confidence,
        "bonuses": [
            {
                "bonus_type": b.bonus_type.value if b.bonus_type else None,
                "raw_label": b.raw_label,
                "percent": b.percent,
                "highlighted": b.highlighted,
                "text_confidence": b.text_confidence,
            }
            for b in (gear.bonuses or [])
        ],
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _replace_existing_snapshot(
    session: Session, season_number: int, player_username: str
) -> bool:
    """Delete any prior snapshot for the same (season, player). Returns
    True when an existing row was removed."""
    existing = session.exec(
        select(RosterSnapshot).where(
            RosterSnapshot.season_number == season_number,
            RosterSnapshot.player_username == player_username,
        )
    ).first()
    if existing is None:
        return False
    session.exec(
        delete(RosterSnapshotCharacter).where(
            RosterSnapshotCharacter.snapshot_id == existing.id
        )
    )
    session.delete(existing)
    session.commit()
    return True


def _persist_snapshot(
    session: Session,
    *,
    season_number: int,
    player_username: str,
    captured_at: Optional[datetime],
    source_csv_path: Optional[str],
    label: Optional[str],
    research: dict,
    characters: list[tuple[int, dict]],
    report: SnapshotReport,
) -> None:
    """Write a RosterSnapshot + per-character rows. Caller is
    responsible for having cleared any prior snapshot."""
    snapshot = RosterSnapshot(
        season_number=season_number,
        player_username=player_username,
        captured_at=captured_at or datetime.now(timezone.utc),
        source_csv_path=source_csv_path,
        label=label,
    )
    for fld in _RESEARCH_FIELDS:
        if fld in research and research[fld] is not None:
            setattr(snapshot, fld, int(research[fld]))
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)

    for char_id, payload in characters:
        session.add(RosterSnapshotCharacter(
            snapshot_id=snapshot.id,
            character_id=char_id,
            data=payload,
        ))
    session.commit()
    report.snapshot_id = snapshot.id


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def make_self_snapshot(
    *,
    season_number: int,
    player_username: str,
    label: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> SnapshotReport:
    """Snapshot the current ``OwnedCharacter`` + ``AccountState``
    rows under ``(season_number, player_username)``.

    Replaces any existing snapshot for the same (season, player). Use
    once per season at season start to lock the user's roster.
    """
    engine = make_engine(db_path)
    init_db(engine)
    report = SnapshotReport(
        season_number=season_number,
        player_username=player_username,
    )

    with get_session(engine) as session:
        report.replaced_existing = _replace_existing_snapshot(
            session, season_number, player_username
        )

        owned_rows = session.exec(select(OwnedCharacter)).all()
        characters: list[tuple[int, dict]] = []
        for owned in owned_rows:
            payload = serialize_owned(owned, session=session)
            characters.append((owned.character_id, payload))
            report.matched += 1
        report.rows_seen = len(owned_rows)

        # Pull research levels off the live AccountState singleton.
        state = session.get(AccountState, 1) or AccountState()
        research = {fld: getattr(state, fld, None) for fld in _RESEARCH_FIELDS}

        _persist_snapshot(
            session,
            season_number=season_number,
            player_username=player_username,
            captured_at=datetime.now(timezone.utc),
            source_csv_path=None,
            label=label or "self-snapshot",
            research=research,
            characters=characters,
            report=report,
        )

    return report


def import_snapshot_csv(
    *,
    csv_path: Path,
    season_number: int,
    player_username: str,
    research: dict,
    label: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> SnapshotReport:
    """Import another player's roster CSV as a snapshot.

    ``research`` should carry whichever of the
    :data:`_RESEARCH_FIELDS` keys the caller wants to set —
    typically all of them, since other-player CSVs don't include
    account-wide research data.
    """
    engine = make_engine(db_path)
    init_db(engine)
    report = SnapshotReport(
        season_number=season_number,
        player_username=player_username,
    )
    # build_owned_from_row reports cube/warning details into an
    # ImportReport — we mirror its counters into ours.
    import_report = ImportReport()

    with get_session(engine) as session:
        report.replaced_existing = _replace_existing_snapshot(
            session, season_number, player_username
        )

        all_chars = session.exec(select(Character)).all()
        all_names = [c.name for c in all_chars]

        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames or [])
            normalized_fields = {COLUMN_ALIASES.get(f, f) for f in fields}
            missing_required = [
                c for c in REQUIRED_COLUMNS if c not in normalized_fields
            ]
            if missing_required:
                report.warnings.append(
                    f"CSV missing required columns: {missing_required}"
                )
            v2 = _is_v2_format(fields)
            characters: list[tuple[int, dict]] = []

            for raw_row in reader:
                row = _normalize_row(raw_row)
                report.rows_seen += 1
                name = (row.get("Name") or "").strip()
                if not name:
                    report.warnings.append(
                        f"row {report.rows_seen}: empty Name, skipping"
                    )
                    report.unmatched += 1
                    continue
                char = _find_character(
                    session, name, all_names=all_names, report=import_report
                )
                if char is None:
                    report.unmatched += 1
                    report.warnings.append(
                        f"row {report.rows_seen}: no Character match for '{name}'"
                    )
                    continue
                report.matched += 1

                owned = build_owned_from_row(
                    session, row, char=char, v2=v2, report=import_report,
                )
                # Don't persist OwnedCharacter — we only want the
                # serialized payload. Cubes were upserted in-place by
                # build_owned_from_row, which is fine: cubes are a
                # shared resource (one row per cube name, not
                # per-player).
                payload = serialize_owned(owned, session=session)
                characters.append((char.id, payload))

        report.cubes_upserted = import_report.cubes_upserted
        report.warnings.extend(import_report.warnings or [])

        _persist_snapshot(
            session,
            season_number=season_number,
            player_username=player_username,
            captured_at=datetime.now(timezone.utc),
            source_csv_path=str(csv_path),
            label=label,
            research=research,
            characters=characters,
            report=report,
        )

    return report


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_snapshot(
    session: Session, *, season_number: int, player_username: str
) -> Optional[RosterSnapshot]:
    """Return the snapshot for ``(season, player)`` or ``None``."""
    return session.exec(
        select(RosterSnapshot).where(
            RosterSnapshot.season_number == season_number,
            RosterSnapshot.player_username == player_username,
        )
    ).first()


def list_snapshots_for_season(
    session: Session, season_number: int
) -> list[RosterSnapshot]:
    """All snapshots tied to ``season_number``, sorted by capture time."""
    return list(session.exec(
        select(RosterSnapshot)
        .where(RosterSnapshot.season_number == season_number)
        .order_by(RosterSnapshot.captured_at.desc())
    ).all())
