"""Yan — Fire RL B1, charge-damage support.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Full Burst entry: all allies Charge Damage +21.55% for 10 sec.

**Source description (S2)**:

    Full Charge attack: all allies ATK +2.77% and Crit Rate +1.33%
    for 5 sec.

**Source description (Burst)**:

    In-range enemies: 348.73% ATK damage; forced movement toward
    center for 2 sec.
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
    character_name="Yan",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst entry: all allies Charge Damage +21.55% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=21.55,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Charge attack: all allies ATK +2.77% and Crit "
                "Rate +1.33% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.77,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.33,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: in-range enemies take 348.73% ATK damage and "
                "are pulled toward center for 2 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.4873,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire RL B1 — charge-damage team buffer. Niche; pairs with "
        "RL/SR-heavy comps that benefit from Charge Damage."
    ),
)
register_character(_SKILL)
