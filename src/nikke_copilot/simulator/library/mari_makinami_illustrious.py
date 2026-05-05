"""Mari Makinami Illustrious — B2 Electric SR Abnormal (Eva collab).

Encoded from the live ``Character`` skill descriptions in the DB. Mari
is the Eva-collab anti-shield + Pierce specialist — full charge buffs
team shield damage by +100%, core hits buff team Pierce damage by +41%,
burst grants self Pierce + team Attack Damage.

**Source description (S1)**:

    Activates when landing an attack with Full Charge. Affects all allies.
    Damage dealt to Shield ▲ 100.09% for 3 sec.
    (It only affects the damage dealt to the shield, not to the Rapture itself.)

    Activates when hitting the target's core. Affects all allies.
    Pierce Damage ▲ 40.99% for 10 sec.

**Source description (S2)**:

    Affects self. Gain Pierce for 5 sec. ATK ▲ 30.78% for 5 sec.

    Affects all allies. ATK ▲ 30.78% of caster's ATK for 5 sec.

**Source description (Burst)**:

    Affects all enemies. Deals 639.36% of final ATK as damage.

    Affects all allies. Attack damage ▲ 40.99% for 10 sec.
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
    character_name="Mari Makinami Illustrious",
    skill1=(
        SkillEffect(
            description=(
                "On full charge: all allies' shield damage +100.09% "
                "for 3 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SHIELD_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=100.09,
                    duration_seconds=3.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On core hit: all allies Pierce Damage +40.99% for "
                "10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="hits target's core",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.99,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: self Pierce + ATK +30.78% for 5 sec; all "
                "allies ATK +30.78% of caster's ATK for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.78,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.78,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all enemies take 639.36%; all allies Attack "
                "Damage +40.99% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=6.3936,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.99,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Mari is the Eva-collab Pierce/anti-shield specialist — full "
        "charge doubles team shield damage, core hits stack Pierce "
        "damage, burst extends a team-wide Attack Damage buff. Pairs "
        "with full-charge attackers (SBS / Cinderella / Maxwell) "
        "and core-hit-leaning teams."
    ),
)
register_character(_SKILL)
