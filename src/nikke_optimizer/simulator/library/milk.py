"""Milk — Water SR B1, lifesteal AOE healer (base form).

Burst: 367.34% ATK damage to enemies in range; all allies regen via
16.16% lifesteal for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Milk",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 367.34% ATK damage to in-range enemies; all "
                "allies 16.16% lifesteal for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.6734,
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
    notes="Water SR B1 (base). Niche; outshone by Milk (Treasure).",
)
register_character(_SKILL)
