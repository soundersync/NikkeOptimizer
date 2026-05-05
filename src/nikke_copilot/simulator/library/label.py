"""Label — Iron AR B1, shield-tank support.

Burst: self Max HP +20.26% for 10 sec; Shared Delusion — Label's
shield becomes invulnerable for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Label",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Max HP +20.26% for 10 sec; Label's shield "
                "becomes invulnerable for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.26,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Iron AR B1. Shield-tank; mostly stall-comp niche.",
)
register_character(_SKILL)
