"""Convert :class:`AccountState` research levels into stat-buff dicts.

The user's Outpost research provides flat additive buffs to every Nikke,
applied inside the core multiplier in the BlablaLink stat formula:

    basic = round( (F + floor(class+mfr+general) + round(bond)) * core_mult )
                + equip + cube + treasure

This module owns the *rates* — observed from real in-game data and
documented per-level. If Shift Up changes them in a future patch, only
the constants here need updating.

Per-level rates (May 2026, derived from a real account):
  - General Research:    +450 HP / level
  - Class research:      +750 HP / level, +5 DEF / level
  - Manufacturer research: +25 ATK / level, +5 DEF / level

NIKKE's "Healer" sub-role uses Supporter research — there's no separate
Healer research bucket.
"""

from __future__ import annotations

from typing import Optional

from ..data.enums import Manufacturer
from ..data.models import AccountState

# Per-level rates. Round numbers, derived from R30-R179 observations.
HP_PER_GENERAL_LEVEL = 450
HP_PER_CLASS_LEVEL = 750
DEF_PER_CLASS_LEVEL = 5
ATK_PER_MFR_LEVEL = 25
DEF_PER_MFR_LEVEL = 5

# BlablaLink ``class`` field values map to the user-facing class buckets.
_CLASS_FIELD_MAP = {
    "Attacker": "attacker",
    "Defender": "defender",
    "Supporter": "supporter",
    # NIKKE has no separate "Healer" research level; Healer Nikkes
    # reuse Supporter research. Both Prydwen and BlablaLink classify
    # their `class` as "Supporter" anyway.
    "Healer": "supporter",
}


def class_buff(state: AccountState, char_class: str) -> dict[str, int]:
    """Return ``{atk, hp, def}`` buff for a character of the given class.

    ``char_class`` is the BlablaLink ``class`` field (e.g. ``"Attacker"``).
    Unknown classes yield zero buffs.
    """
    bucket = _CLASS_FIELD_MAP.get(char_class)
    if bucket is None:
        return {"atk": 0, "hp": 0, "def": 0}
    level = getattr(state, f"class_{bucket}_level", 0) or 0
    return {
        "atk": 0,
        "hp": HP_PER_CLASS_LEVEL * level,
        "def": DEF_PER_CLASS_LEVEL * level,
    }


def manufacturer_buff(
    state: AccountState, manufacturer: Optional[Manufacturer | str]
) -> dict[str, int]:
    """Return ``{atk, hp, def}`` buff for a character of the given manufacturer.

    Accepts either a :class:`Manufacturer` enum or the BlablaLink
    ``corporation`` string (case-insensitive).
    """
    if manufacturer is None:
        return {"atk": 0, "hp": 0, "def": 0}
    name = (
        manufacturer.value if isinstance(manufacturer, Manufacturer) else str(manufacturer)
    ).lower()
    level = getattr(state, f"mfr_{name}_level", 0) or 0
    return {
        "atk": ATK_PER_MFR_LEVEL * level,
        "hp": 0,
        "def": DEF_PER_MFR_LEVEL * level,
    }


def general_research_buff(state: AccountState) -> dict[str, int]:
    """Return ``{atk, hp, def}`` buff from Recycle Room → General Research."""
    level = state.general_research_level or 0
    return {
        "atk": 0,
        "hp": HP_PER_GENERAL_LEVEL * level,
        "def": 0,
    }


def get_or_default_state(session) -> AccountState:
    """Fetch the singleton :class:`AccountState` row, creating it on demand."""
    state = session.get(AccountState, 1)
    if state is None:
        state = AccountState(id=1)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state
