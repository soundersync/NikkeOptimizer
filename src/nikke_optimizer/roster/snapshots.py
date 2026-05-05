"""Roster snapshot + diff.

On every CSV import we save a snapshot of the OwnedCharacter state to
``<user_data_dir>/snapshots/<timestamp>.json``. The diff route compares
the current roster against the most recent snapshot N days ago and
lists what changed: new Nikkes, sync-level / skill-level changes,
cube swaps, Limit Break upgrades.

Snapshots are flat JSON dicts of ``{name: {field: value}}`` so the
diff is a simple set/dict comparison.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir
from sqlmodel import Session, select

from ..data.models import Character, Cube, OwnedCharacter

_APP_NAME = "NikkeOptimizer"
_SNAPSHOTS_DIRNAME = "snapshots"


def _snapshots_dir() -> Path:
    base = Path(user_data_dir(_APP_NAME, appauthor=False))
    out = base / _SNAPSHOTS_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def take_snapshot(session: Session, *, label: str = "") -> Path:
    """Capture the current roster state to a timestamped JSON file."""
    chars_by_id = {c.id: c.name for c in session.exec(select(Character)).all()}
    cubes_by_id = {c.id: c.name for c in session.exec(select(Cube)).all()}
    owned = list(session.exec(select(OwnedCharacter)).all())

    state: dict[str, dict] = {}
    for o in owned:
        name = chars_by_id.get(o.character_id)
        if not name:
            continue
        state[name] = {
            "power": o.power,
            "sync_level": o.sync_level,
            "core": o.core,
            "limit_break": o.limit_break,
            "skill1_level": o.skill1_level,
            "skill2_level": o.skill2_level,
            "burst_skill_level": o.burst_skill_level,
            "arena_cube": cubes_by_id.get(o.arena_cube_id) if o.arena_cube_id else None,
            "battle_cube": cubes_by_id.get(o.battle_cube_id) if o.battle_cube_id else None,
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f"{ts}{('_' + label) if label else ''}.json"
    path = _snapshots_dir() / fname
    path.write_text(
        json.dumps(
            {"timestamp": ts, "label": label, "characters": state},
            indent=2,
            sort_keys=True,
        )
    )
    return path


def list_snapshots() -> list[Path]:
    """Return all snapshot files sorted oldest → newest."""
    return sorted(_snapshots_dir().glob("*.json"))


def latest_snapshot_before(days_ago: int) -> Optional[Path]:
    """Find the most recent snapshot from at least ``days_ago`` days back.

    Returns None when no qualifying snapshot exists.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
    cutoff_ts = cutoff.strftime("%Y%m%dT%H%M%SZ")
    candidates = [p for p in list_snapshots() if p.stem[:16] <= cutoff_ts[:16]]
    return candidates[-1] if candidates else None


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text())


def diff_against(session: Session, snapshot_path: Path) -> dict:
    """Compare current roster to a saved snapshot.

    Returns a structured dict:
      {
        "snapshot_timestamp": str,
        "added": [name, ...],          # owned now, not in snapshot
        "removed": [name, ...],        # in snapshot, not owned now
        "changed": {                   # field-level changes
          name: {field: (old, new), ...},
        },
      }
    """
    snap = load_snapshot(snapshot_path)
    snap_chars: dict[str, dict] = snap.get("characters", {})

    chars_by_id = {c.id: c.name for c in session.exec(select(Character)).all()}
    cubes_by_id = {c.id: c.name for c in session.exec(select(Cube)).all()}
    current: dict[str, dict] = {}
    for o in session.exec(select(OwnedCharacter)).all():
        name = chars_by_id.get(o.character_id)
        if not name:
            continue
        current[name] = {
            "power": o.power,
            "sync_level": o.sync_level,
            "core": o.core,
            "limit_break": o.limit_break,
            "skill1_level": o.skill1_level,
            "skill2_level": o.skill2_level,
            "burst_skill_level": o.burst_skill_level,
            "arena_cube": cubes_by_id.get(o.arena_cube_id) if o.arena_cube_id else None,
            "battle_cube": cubes_by_id.get(o.battle_cube_id) if o.battle_cube_id else None,
        }

    added = sorted(set(current) - set(snap_chars))
    removed = sorted(set(snap_chars) - set(current))
    changed: dict[str, dict] = {}
    for name in sorted(set(current) & set(snap_chars)):
        diffs: dict[str, tuple] = {}
        for field, new_v in current[name].items():
            old_v = snap_chars[name].get(field)
            if new_v != old_v:
                diffs[field] = (old_v, new_v)
        if diffs:
            changed[name] = diffs

    return {
        "snapshot_timestamp": snap.get("timestamp", ""),
        "snapshot_path": str(snapshot_path),
        "added": added,
        "removed": removed,
        "changed": changed,
    }
