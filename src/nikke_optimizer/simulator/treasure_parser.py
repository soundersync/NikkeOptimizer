"""Parse Treasure (SSR Favorite Item) skill descriptions into structured effects.

Treasures live as free-form text in the ``TreasureSkill.description_treasured``
column (51 rows × 17 chars). Each Nikke's treasure has 3 phase entries (P1,
P2, P3) that progressively unlock skill upgrades. Each phase's description
contains 1-5 typed effects in NIKKE's standard format:

    ■ Activates when ... Affects ...
    DEF ▲ 25.92% for 10 sec
    Max HP ▲ 5% for 10 sec
    Creates a Shield equal to 7% of caster's final Max HP for 5 sec

This module extracts those effects via regex patterns and maps them to
``NikkeSnapshot`` buff fields. Untranslatable effects (cooldown reductions,
conditional state machines) are dropped — same approach as the DSL encoder.

Sources used to calibrate stat-name → field mappings:
- nikke.gg/damage-formula stat-buff-categories
- Prydwen treasure pages
"""

from __future__ import annotations

import re
from typing import Optional


# Map normalized stat name → NikkeSnapshot _buff_pct field name.
# Stat names match what NIKKE in-game prose uses (after lowercasing).
_STAT_TO_FIELD: dict[str, str] = {
    "atk":                   "atk_buff_pct",
    "def":                   "def_buff_pct",
    "crit rate":             "crit_rate_buff_pct",
    "critical rate":         "crit_rate_buff_pct",
    "crit damage":           "crit_damage_buff_pct",
    "critical damage":       "crit_damage_buff_pct",
    "charge damage":         "charge_damage_buff_pct",
    "charge speed":          "charge_speed_buff_pct",
    "element damage":        "element_damage_buff_pct",
    "elemental damage":      "element_damage_buff_pct",
    "attack damage":         "attack_damage_buff_pct",
    "true damage":           "true_damage_buff_pct",
    "pierce damage":         "pierce_damage_buff_pct",
    "shield damage":         "shield_damage_buff_pct",
    "core damage":           "core_damage_buff_pct",
    "burst skill damage":    "burst_skill_damage_buff_pct",
    "sustained damage":      "sustained_damage_buff_pct",
    "damage to parts":       "parts_damage_buff_pct",
}

# Effect categories that we treat specially (not a simple _buff_pct).
_SHIELD_PATTERN = re.compile(
    r"Creates a Shield equal to ([\d.]+)% of (?:the )?caster's (?:final )?(?:Max )?HP",
    re.IGNORECASE,
)
_HEAL_PCT_HP_PATTERN = re.compile(
    r"(?:Recovers HP|Continuously recovers HP) (?:by )?([\d.]+)% of (?:the )?caster's (?:final )?(?:Max )?HP",
    re.IGNORECASE,
)
_MAX_HP_BUFF_PATTERN = re.compile(
    r"Max HP ▲\s*([\d.]+)%", re.IGNORECASE
)
_DAMAGE_TAKEN_DOWN_PATTERN = re.compile(
    r"Damage Taken ▼\s*([\d.]+)%", re.IGNORECASE
)
# Generic stat buff: "<STAT> ▲ X.YZ%"
_STAT_BUFF_PATTERN = re.compile(
    r"([\w][\w ]+?)\s*▲\s*([\d.]+)%"
)


def parse_treasure_description(text: str) -> dict[str, float]:
    """Parse one TreasureSkill description into a buff dict.

    Returns a dict with keys matching the ``NikkeSnapshot`` field names
    or special keys we'll handle in the evaluator:

    - ``atk_buff_pct`` / ``def_buff_pct`` / ``crit_*_buff_pct`` / etc.
    - ``shield_pct_caster_hp`` — shield value as % of caster max HP
    - ``heal_pct_caster_hp_per_sec`` — heal/sec as % of caster HP
    - ``max_hp_buff_pct`` — multiplicative HP boost
    - ``damage_taken_reduction_pct`` — damage taken reduction (0-100)

    The caller multiplies %-of-caster values by the actual caster's HP.
    Unparseable lines are silently dropped.
    """
    if not text:
        return {}
    out: dict[str, float] = {}

    # Shield creation
    for m in _SHIELD_PATTERN.finditer(text):
        out["shield_pct_caster_hp"] = out.get("shield_pct_caster_hp", 0) + float(m.group(1))

    # Heal per second
    for m in _HEAL_PCT_HP_PATTERN.finditer(text):
        out["heal_pct_caster_hp_per_sec"] = (
            out.get("heal_pct_caster_hp_per_sec", 0) + float(m.group(1))
        )

    # Max HP buff (multiplicative)
    for m in _MAX_HP_BUFF_PATTERN.finditer(text):
        out["max_hp_buff_pct"] = out.get("max_hp_buff_pct", 0) + float(m.group(1))

    # Damage Taken reduction
    for m in _DAMAGE_TAKEN_DOWN_PATTERN.finditer(text):
        out["damage_taken_reduction_pct"] = (
            out.get("damage_taken_reduction_pct", 0) + float(m.group(1))
        )

    # Generic stat buffs (ATK, DEF, Crit Rate, etc.)
    seen_offsets: set[int] = set()
    for m in _STAT_BUFF_PATTERN.finditer(text):
        # Skip "Max HP ▲" — already captured above
        if m.start() in seen_offsets:
            continue
        stat_raw = m.group(1).strip().lower()
        # Strip leading articles / verbs that occasionally land in the
        # match (regex captures greedily before the ▲).
        stat_raw = re.sub(r"^(self's |their |the )", "", stat_raw)
        if stat_raw == "max hp":
            continue  # already captured
        field = _STAT_TO_FIELD.get(stat_raw)
        if field is None:
            continue
        try:
            mag = float(m.group(2))
        except ValueError:
            continue
        out[field] = out.get(field, 0.0) + mag

    return out
