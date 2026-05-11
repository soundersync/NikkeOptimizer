"""Product 08 — B1 Electric SR Missilis. Basic Recruit DEF/Crit support.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit; minimal kit centered on small Crit + ATK buffs.

**Source description (S1)**:

    When a normal attack hits, there is 20% chance of affecting 1 ally
    unit(s) with the lowest HP. DEF ▲ 9.09% for 5 sec.

**Source description (S2)**:

    Affects 1 ally unit(s) with the highest ATK. Critical Rate ▲ 22.99%
    for 5 sec.

**Source description (Burst)**:

    Affects all allies. ATK ▲ 19.39% for 10 sec.
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
    character_name="Product 08",
    skill1=(
        SkillEffect(
            description=(
                "20% chance per normal attack: lowest-HP ally DEF +9.09% "
                "for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="20% chance per normal attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=9.09,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: highest-ATK ally Crit Rate +22.99% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=22.99,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies ATK +19.39% for 10 sec.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=19.39,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Basic Recruit. Tutorial/early-game; no PvP relevance.",
)
register_character(_SKILL)
