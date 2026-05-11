"""Mica — B1 Wind RL Tetra. Top-ATK Ammo/DEF buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Mica is a budget Centi-adjacent RL B1: she buffs the top-2 ATK allies'
Max Ammo + DEF and her burst is the standard RL AOE + DEF debuff.

**Source description (S1)**:

    Activates when attacked 20 time(s). Affects self. DEF ▲ 39.18% for 10 sec.

**Source description (S2)**:

    Affects 2 allies with the highest ATK. Max Ammunition Capacity ▲ 2
    round(s) for 10 sec. DEF ▲ 19.89% for 10 sec.

**Source description (Burst)**:

    Affects all enemies. Deals 152.22% of final ATK as damage.
    DEF ▼ 13.32% for 5 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Mica",
    skill1=(
        SkillEffect(
            description="After being attacked 20 times: self DEF +39.18% for 10 sec.",
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="20 hits taken (counter-based)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=39.18,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: top-2 ATK allies Max Ammo +2 rounds and "
                "DEF +19.89% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=2.0,
                    duration_seconds=10.0,
                    notes="flat +2 rounds",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=19.89,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all enemies take 152.22% of ATK + DEF -13.32% "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.5222,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=13.32,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Mica is a budget Centi/Anis-style B1 RL: Max Ammo + DEF buff "
        "to top-2 ATK allies + standard AOE/DEF-debuff burst."
    ),
)
register_character(_SKILL)
