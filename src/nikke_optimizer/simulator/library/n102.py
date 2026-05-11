"""N102 — B1 Water RL Missilis. Top-ATK Ammo/Crit-Damage support.

Encoded from the live ``Character`` skill descriptions in the DB.
N102 buffs the top-ATK ally with Max Ammo + Crit Damage and the
highest-HP ally with Charge Damage. Her burst is a standard team
ATK buff.

**Source description (S1)**:

    Affects 1 ally with the highest ATK. Cast when attacking during
    Full Charge. Max Ammunition Capacity ▲ 3 shots for 10 sec.
    Critical Damage ▲ 10.34% for 10 sec.

**Source description (S2)**:

    Affects 1 ally unit(s) with the highest HP. Charge Damage ▲ 25.84%
    for 5 sec.

**Source description (Burst)**:

    Affects all allies. ATK ▲ 25.86% for 10 sec.
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
    character_name="N102",
    skill1=(
        SkillEffect(
            description=(
                "On Full Charge hit: highest-ATK ally Max Ammo +3 rounds "
                "+ Crit Damage +10.34% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge hit lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=3.0,
                    duration_seconds=10.0,
                    notes="flat +3 rounds",
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=10.34,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: highest-HP ally Charge Damage +25.84% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=25.84,
                    duration_seconds=5.0,
                    notes=(
                        "actually 'highest HP' ally — DSL has no "
                        "ALLY_HIGHEST_HP target; using ALLY_LOWEST_HP as "
                        "the closest single-ally HP-based selector."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies ATK +25.86% for 10 sec.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=25.86,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "N102 is a budget RL B1 with a Max Ammo + Crit Damage buff for "
        "the team's main DPS, plus a standard team-wide ATK burst."
    ),
)
register_character(_SKILL)
