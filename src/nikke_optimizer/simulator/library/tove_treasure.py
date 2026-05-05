"""Tove (Treasure) — Water AR B1, SG-comp ATK booster (Treasure form).

Burst: all allies ATK +2.32% of caster's ATK (×Temp Mod stacks);
SG allies ATK +24.21% of caster's ATK (×Temp Mod stacks). Both for
15 sec (Treasure extends from 10 to 15 sec).
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, ScalingSource, SkillEffect,
    Target, TargetKind, Trigger, TriggerKind, WeaponClass,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Tove (Treasure)",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies ATK +2.32% of caster's ATK; SG "
                "allies ATK +24.21% of caster's ATK. Both for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.32,
                    duration_seconds=15.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    stacks_max=3,
                    notes="mirrors Temp Mod stack count (1-3)",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=24.21,
                    duration_seconds=15.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    stacks_max=3,
                ),
            ),
        ),
    ),
    burst_duration_seconds=15.0,
    notes="Water AR B1 (Treasure). Treasure extends 10s → 15s duration.",
)
register_character(_SKILL)
