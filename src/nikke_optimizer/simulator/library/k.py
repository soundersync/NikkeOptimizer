"""K — Electric SMG B3, weapon-swap pellet carry.

Burst: weapon swap (92.5% ATK per shot × 10 pellets, attack speed
-90%, 10 sec); self ATK +63.36% of caster's ATK and Attack Damage
+21.12% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, ScalingSource, SkillEffect,
    Target, TargetKind, Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="K",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: weapon swap (~925% ATK / sec via 10-pellet "
                "shots); self ATK +63.36% of caster's ATK + Attack "
                "Damage +21.12% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=63.36,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.12,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=9.25,
                    notes="weapon-swap aggregate (10 pellets × 92.5% × ~1/sec)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Electric SMG B3. Pellet weapon swap; niche close-range carry.",
)
register_character(_SKILL)
