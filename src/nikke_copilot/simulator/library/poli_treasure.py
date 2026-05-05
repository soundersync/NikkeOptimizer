"""Poli (Treasure) — Water SG B2, indomitability + team-shield tank.

Burst: in Police Badge → self Indomitability for 5 sec, removes badge.
Self shield 40% of Max HP protects all allies for 10 sec; team ATK
+44.55% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, ScalingSource, SkillEffect,
    Target, TargetKind, Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Poli (Treasure)",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self shield 40% of Max HP for 10 sec (protects "
                "team); all allies ATK +44.55% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="protects all allies (DSL gap on team-shield)",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=44.55,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Water SG B2 (Treasure). Stall-comp anchor with team ATK boost.",
)
register_character(_SKILL)
