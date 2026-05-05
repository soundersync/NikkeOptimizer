"""Clay — Electric SMG B2, true-damage support / debuff immunity.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Every 60 normal attacks during Full Burst: all allies
    Victorious Battle Cry — True Damage ▲ 6.45%, max 3 stacks, 6 sec.

**Source description (S2)**:

    Burst Stage 1 entry: all allies immune to 1 debuff for 10 sec.
    In Victorious Battle Cry: all allies ATK +20.07% of caster's
    ATK continuously.

**Source description (Burst)**:

    All allies: True Damage +12.56% for 10 sec.
    Self: normal attacks deal true damage for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Clay",
    skill1=(
        SkillEffect(
            description=(
                "Every 60 normal attacks during Full Burst: all allies "
                "Victorious Battle Cry — True Damage +6.45%, max 3 "
                "stacks, 6 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=60,
                condition="during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=6.45,
                    duration_seconds=6.0,
                    stacks_max=3,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "While in Victorious Battle Cry: all allies ATK +20.07% "
                "of caster's ATK continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Victorious Battle Cry stacks active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.07,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies True Damage +12.56% for 10 sec; self "
                "normal attacks deal true damage for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=12.56,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes="self normal attacks → true damage (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SMG B2 — true-damage team support. Pairs naturally "
        "with high-DEF defender opponents (Helm/Centi/Blanc); "
        "Victorious Battle Cry stacking favors sustained-DPS comps."
    ),
)
register_character(_SKILL)
