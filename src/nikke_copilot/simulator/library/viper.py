"""Viper — Water SG B2, niche on-spawn ATK + invincibility burst.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Activates when target appears. Affects all allies. ATK ▲ 25.98%
    for 10 sec. Hit Rate ▲ 11.13% for 10 sec.

**Source description (S2)**:

    Affects self. Hit Rate ▲ 3.43%.
    Activates when entering Full Burst. Affects self. Vamp: Prevents
    self from being targeted by single-target attacks for 10 sec.
    Loses effect when caster takes damage. Invincible for 1 sec.

**Source description (Burst)**:

    Affects designated 1 enemy unit. Deals 462.85% of final ATK as
    damage.
    Activates when designated enemy is the stage target. Affects same
    target. DEF ▼ 19.83% for 10 sec.
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
    character_name="Viper",
    skill1=(
        SkillEffect(
            description=(
                "On enemy spawn: all allies ATK +25.98% and Hit Rate "
                "+11.13% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="enemy spawns",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=25.98,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.13,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Passive: self Hit Rate +3.43% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.43,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 462.85% ATK to designated enemy; if stage target, "
                "DEF -19.83% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=4.6285,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=19.83,
                    duration_seconds=10.0,
                    notes="conditional on stage target match",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SG B2 — on-spawn team ATK buff + DEF-shred burst. Niche "
        "support; outshone by Crown for general use but useful in "
        "anti-bossy stage scenarios."
    ),
)
register_character(_SKILL)
