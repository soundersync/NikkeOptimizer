"""Ade: Agent Bunny — Iron SR B2, anti-shield / pierce support.

Encoded from the live ``Character`` skill descriptions. Ade:AB is a
B2 SR pierce-buff specialist — her S2 grants Pierce + ATK when Spy
Lens is fully stacked, and her burst grants team-wide Attack Damage
+ Pierce Damage buffs.

**Source description (S1)**:

    Activates when landing Full Charge attacks on targets within the
    effective range. Affects all allies. ATK ▲ 15.2% of caster's ATK
    for 5 sec.
    Activates when attacking with Full Charge. Affects self. Spy Lens:
    Minimum Effective Range ▲ 4.44%, max 10 stacks, 5 sec.

**Source description (S2)**:

    Activates when landing Full Charge attacks on targets within the
    effective range. Affects all allies. Pierce Damage ▲ 18.36% for
    5 sec.
    Activates only if Spy Lens is fully stacked. Affects self. Gain
    Pierce continuously. ATK ▲ 16% continuously.

**Source description (Burst)**:

    Affects self. Minimum Effective Range ▲ 55.56% for 10 sec.
    Affects all allies. Attack Damage ▲ 55.04% for 10 sec. Pierce
    Damage ▲ 10.13% for 10 sec.
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
    character_name="Ade: Agent Bunny",
    skill1=(
        SkillEffect(
            description=(
                "Full Charge in-range hit: all allies ATK +15.2% of "
                "caster's ATK for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands within effective range",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.2,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Charge in-range hit: all allies Pierce Damage "
                "+18.36% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands within effective range",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=18.36,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Spy Lens is fully stacked: self gains Pierce + "
                "ATK +16% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Spy Lens fully stacked",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=16.0,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Effective Range +55.56% for 10 sec; all "
                "allies Attack Damage +55.04% + Pierce Damage +10.13% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=55.04,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.13,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SR B2 — pierce + ATK buffer. Strong support for SR-heavy "
        "comps (Maxwell / Alice / Snow White: HA) thanks to the "
        "team Attack Damage + Pierce Damage on burst."
    ),
)
register_character(_SKILL)
