"""Julia (Treasure) — Iron AR B3, crit-stacking carry.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Self Crit Rate +26.04% for 10 sec, ATK +20% for 10 sec, Normal
    Attack Crit Rate +36.16% for 10 sec.

**Source description (S2)**:

    Every 6 crit normal hits: self Crescendo — Crit Damage +24.79%,
    max 5 stacks, 15 sec.
    Every 8 crit normal hits: target takes 88% ATK as Marcato additional damage.

**Source description (Burst)**:

    Random enemies: 5 sequential 544.5% ATK hits.
    Same target if Crescendo fully stacked: +544.5% additional damage.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Julia (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "Self Crit Rate +26.04%, ATK +20%, Normal Attack Crit "
                "Rate +36.16% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=26.04,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 6 normal crit hits: self Crescendo — Crit Damage "
                "+24.79%, max 5 stacks, 15 sec each."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=6),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=24.79,
                    duration_seconds=15.0,
                    stacks_max=5,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 8 normal crit hits: target takes 88% ATK as "
                "Marcato additional damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=8),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.88,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 5 sequential 544.5% ATK hits to random enemies; "
                "+544.5% additional when Crescendo fully stacked."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=5),
                    magnitude=5.445,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=5),
                    magnitude=5.445,
                    notes="conditional on Crescendo fully stacked",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron AR B3 (Treasure) — crit-stacking carry. The Treasure "
        "form trades Julia base's high-DEF-target focus for a more "
        "conventional crit-rate AR carry."
    ),
)
register_character(_SKILL)
