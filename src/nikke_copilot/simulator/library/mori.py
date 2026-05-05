"""Mori — Wind AR B2, shield-tank with sustained-damage support.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Battle start (or burst use if not in Struggle): self Struggle —
    Shield equal to 40.12% of caster's Max HP, continuous.

**Source description (S2)**:

    Every 60 normal attacks while in Struggle: target taunted 4 sec.
    On any ally's parts destroyed: all allies Sustained Damage +2.03%,
    max 5 stacks, 15 sec.

**Source description (Burst)**:

    In Struggle: self regen Shield HP equal to 15.04% of Max HP.
    Not in Struggle: self Max HP +10.09% for 10 sec.
    All allies: Sustained Damage +10.16% for 10 sec.
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
    character_name="Mori",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: self Struggle — Shield equal to 40.12% "
                "of caster's Max HP continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.12,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="Struggle state — continuous (DSL gap on permanent shield)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 60 normal attacks while in Struggle: target "
                "taunted for 4 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=60,
                condition="Struggle status active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.0,
                    duration_seconds=4.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On any ally's parts destroyed: all allies Sustained "
                "Damage +2.03%, max 5 stacks, 15 sec each."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any ally's parts destroyed",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.03,
                    duration_seconds=15.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: in Struggle, self Shield regen 15.04% of Max HP; "
                "all allies Sustained Damage +10.16% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.04,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.16,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind AR B2 — shield-tank with sustained-damage team support. "
        "Pairs with sustained-damage carries (Raven, Mihara: Bonding "
        "Chain). Niche but solid stall-comp anchor."
    ),
)
register_character(_SKILL)
