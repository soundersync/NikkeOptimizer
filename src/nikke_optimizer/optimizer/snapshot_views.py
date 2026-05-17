"""Build CharacterViews from a RosterSnapshot for match-specific simulation.

When a Champions Arena ``ArenaMatch`` has its ``user_snapshot_id`` /
``opponent_snapshot_id`` populated (see migration 0001), the simulator
should resolve each player's stats against the snapshot rather than
the live ``OwnedCharacter`` table — Champions loadouts are season-locked
so the snapshot is the source of truth for "what the player had this
season."

This module provides two helpers:

  - :func:`load_views_from_snapshot` — given a ``RosterSnapshot``, returns
    one :class:`CharacterView` per attached ``RosterSnapshotCharacter``.

  - :func:`load_views_for_match` — looks at a match's snapshot FK and
    returns the views, or ``None`` if no snapshot is linked (caller
    falls back to ``load_owned``).

**Champions level clamp**: in-match per-character level is capped at
``CHAMPIONS_LEVEL_CAP`` (400) regardless of the player's actual
synchro level. Applied at view-construction time when
``mode_clamp='champion'`` so the snapshot itself keeps the player's
real sync_level intact — see [[nikke-synchro-level-semantics]] for
why this is mode-specific.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from ..data.models import (
    AccountState,
    ArenaMatch,
    Character,
    RosterSnapshot,
    RosterSnapshotCharacter,
)
from .loader import _lookup_char_class, _predict_base_stats
from .models import CharacterView

log = logging.getLogger(__name__)

# In-match per-character level cap for Champions Arena. NIKKE clamps
# every char in a Champions match to this level regardless of actual
# investment, so predicted stats for Champions sims must clamp before
# computing base stats.
CHAMPIONS_LEVEL_CAP = 400


def _build_view_from_snapshot_data(
    char: Character,
    data: dict,
    *,
    account_state: Optional[AccountState],
    clamp_level_to: Optional[int],
) -> CharacterView:
    """Reconstruct a single CharacterView from a snapshot payload."""
    sync_lv = data.get("sync_level") or 1
    if clamp_level_to is not None:
        sync_lv = min(sync_lv, clamp_level_to)
    core_lv = data.get("core") or 0
    grade_lv = data.get("limit_break")
    if grade_lv is None:
        grade_lv = 3 if core_lv >= 1 else 0

    # v1 prediction path: AccountState-derived buffs (no per-char rank
    # stats reconstructed from snapshot, no cube/treasure stats yet).
    # This matches mode 2 in _predict_base_stats. Good enough for
    # relative comparisons; future slice can wire snapshot-derived
    # gear/cube/treasure stats for to-the-digit accuracy.
    p_atk, p_hp, p_def, p_pow = _predict_base_stats(
        char.name,
        level=sync_lv,
        grade=grade_lv,
        core=core_lv,
        skill1_level=data.get("skill1_level") or 1,
        skill2_level=data.get("skill2_level") or 1,
        burst_skill_level=data.get("burst_skill_level") or 1,
        account_state=account_state,
        char_class=_lookup_char_class(char.name),
        manufacturer=char.manufacturer.value if char.manufacturer else None,
    )

    # PvP cube preferred for Champions, falls back to PvE cube if absent.
    # Snapshot stores tids only; we don't resolve to Cube rows in v1.
    return CharacterView(
        name=char.name,
        rarity=char.rarity,
        element=char.element,
        weapon_class=char.weapon_class,
        burst_type=char.burst_type,
        manufacturer=char.manufacturer,
        role_tags=tuple(char.role_tags or ()),
        owned=True,
        power=data.get("arena_combat") or data.get("power") or 0,
        sync_level=sync_lv,
        skill1_level=data.get("skill1_level") or 1,
        skill2_level=data.get("skill2_level") or 1,
        burst_skill_level=data.get("burst_skill_level") or 1,
        predicted_base_atk=p_atk,
        predicted_base_hp=p_hp,
        predicted_base_def=p_def,
        predicted_power=p_pow,
    )


def load_views_from_snapshot(
    session: Session,
    snapshot: RosterSnapshot,
    *,
    clamp_level_to: Optional[int] = None,
) -> list[CharacterView]:
    """Return one CharacterView per character row in ``snapshot``.

    Sparse snapshots (only the played chars) yield only those views.
    ``clamp_level_to`` caps every char's level at the given value
    before computing predicted stats — pass ``CHAMPIONS_LEVEL_CAP``
    for Champions matches.

    Account-level buffs (class / manufacturer / research) are drawn
    from the snapshot's own research fields, not the live
    ``AccountState``, so historical snapshots reproduce the player's
    state at the time of capture.
    """
    rows = session.exec(
        select(RosterSnapshotCharacter, Character).where(
            RosterSnapshotCharacter.snapshot_id == snapshot.id,
            RosterSnapshotCharacter.character_id == Character.id,
        )
    ).all()

    # Materialize a transient AccountState carrying the snapshot's
    # research fields so account_buffs.* compute the right values.
    transient_state = AccountState(
        id=-1,
        synchro_level=snapshot.synchro_level,
        general_research_level=snapshot.general_research_level,
        class_attacker_level=snapshot.class_attacker_level,
        class_defender_level=snapshot.class_defender_level,
        class_supporter_level=snapshot.class_supporter_level,
        mfr_pilgrim_level=snapshot.mfr_pilgrim_level,
        mfr_elysion_level=snapshot.mfr_elysion_level,
        mfr_tetra_level=snapshot.mfr_tetra_level,
        mfr_missilis_level=snapshot.mfr_missilis_level,
        mfr_abnormal_level=snapshot.mfr_abnormal_level,
    )

    return [
        _build_view_from_snapshot_data(
            char, snap_char.data or {},
            account_state=transient_state,
            clamp_level_to=clamp_level_to,
        )
        for snap_char, char in rows
    ]


def load_views_for_match(
    session: Session,
    match: ArenaMatch,
    *,
    side: str = "user",
) -> Optional[list[CharacterView]]:
    """Return CharacterViews for one side of a match, resolved against
    the linked snapshot.

    Returns ``None`` if the match has no snapshot FK on that side —
    caller should fall back to ``load_owned``. For Champions matches
    automatically applies the LV-400 clamp.

    ``side`` is ``"user"`` or ``"opponent"``.
    """
    snap_id = (
        match.user_snapshot_id if side == "user" else match.opponent_snapshot_id
    )
    if snap_id is None:
        return None
    snapshot = session.get(RosterSnapshot, snap_id)
    if snapshot is None:
        log.warning(
            "match %s references missing snapshot id=%s", match.id, snap_id
        )
        return None
    clamp = CHAMPIONS_LEVEL_CAP if match.mode == "champion" else None
    return load_views_from_snapshot(session, snapshot, clamp_level_to=clamp)
