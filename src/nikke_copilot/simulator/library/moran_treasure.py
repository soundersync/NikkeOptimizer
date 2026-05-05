"""Moran (Treasure) — Electric AR B1, weapon-swap taunter (Treasure form).

Burst: weapon swap (14.7% ATK / shot, 10 sec) with Attract taunt and
unlimited ammo; team damage taken -35.14% and DEF +14.85% of caster's
DEF for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, ScalingSource, SkillEffect,
    Target, TargetKind, Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Moran (Treasure)",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: weapon swap with attract taunt + lifesteal; team "
                "damage reduction and DEF buff for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=35.14,
                    duration_seconds=10.0,
                    notes="actually 'damage taken' debuff (DSL gap)",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.85,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Electric AR B1 (Treasure). Treasure adds unlimited ammo for 10 sec.",
)
register_character(_SKILL)
