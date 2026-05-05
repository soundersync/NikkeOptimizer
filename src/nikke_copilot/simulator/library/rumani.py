"""Rumani — Fire RL B1, sustain-buff support.

Burst: self Max HP +15.13%, team Normal Attack Damage Multiplier
+10.05% for 10 sec; at Muscle Up max stacks: self Damage Taken
-20.06% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Rumani",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Max HP +15.13% for 10 sec; team Normal "
                "Attack Damage Multiplier +10.05% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.13,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.05,
                    duration_seconds=10.0,
                    notes="actually 'Normal Attack Damage Multiplier'",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Fire RL B1. Niche team-buff B1; small magnitudes vs meta peers.",
)
register_character(_SKILL)
