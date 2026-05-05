"""Miranda (Treasure) — Fire SMG B1, top-2 ATK + Crit support.

Burst: 2 highest-ATK allies (except caster) ATK +40.4% and Crit
Damage +56.23% for 10 sec. Treasure-form magnitude bump over base.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Miranda (Treasure)",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: top-2 ATK allies ATK +40.4% and Crit Damage "
                "+56.23% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=2),
                    magnitude=40.4,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=2),
                    magnitude=56.23,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Fire SMG B1 (Treasure). Concentrates buffs on top-2 ATK allies.",
)
register_character(_SKILL)
