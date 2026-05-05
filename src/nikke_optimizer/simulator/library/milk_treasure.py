"""Milk (Treasure) — Water SR B1, anti-DEF nuker + healer (Treasure form).

Burst: 367.34% ATK damage to highest-DEF enemy; team lifesteal 16.16%
of attack damage as HP for 10 sec, HP Potency +75.5% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Milk (Treasure)",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 367.34% ATK damage to highest-DEF enemy; team "
                "lifesteal + HP Potency for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=3.6734,
                    notes="actually highest-DEF enemy",
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.616,
                    duration_seconds=10.0,
                    notes="actually 'damage→HP lifesteal' (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Water SR B1 (Treasure). Anti-shield-comp nuker.",
)
register_character(_SKILL)
