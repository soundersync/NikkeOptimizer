"""Arcana — Electric RL B2, Electric-code burst support.

Encoded from the live ``Character`` skill descriptions. Arcana's
"Wheel of Fortune" state (active during her burst) gates massive
buffs on Electric-code B3 allies — strong synergy with Electric-code
attackers but niche outside that team archetype.

**Source description (S1)**:

    Full Burst end (in Wheel of Fortune): Electric-code B3 allies who
    bursted get The Magician — Skill 2 CD -75% and Attack Damage
    +180% for 15 sec.
    Full Burst end: all allies ATK +5% of caster's ATK for 10 sec.

**Source description (S2)**:

    Full Burst end (in Wheel of Fortune): Electric-code B3 allies who
    bursted get Strength — ATK +180% of caster's ATK for 15 sec.
    Full Burst end (in Wheel of Fortune): all allies Death — burst
    skill CD -6 sec, ATK +50% of caster's ATK for 5 sec.

**Source description (Burst)**:

    All Electric-code allies: Wheel of Fortune — Attack Damage +10%
    for 10 sec.
    All enemies: 300% of ATK as Burst-Skill damage. Judgement: Damage
    Taken +10% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Arcana",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst end: all allies ATK +5% of caster's ATK for "
                "10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst end (in Wheel of Fortune): Electric-code B3 "
                "allies — The Magician (Attack Damage +180% for 15 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_END,
                condition="Wheel of Fortune state active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=180.0,
                    duration_seconds=15.0,
                    notes=(
                        "actually filtered to B3-bursted-this-cycle; "
                        "encoded as element-filter only (DSL gap on "
                        "burst-position + previously-bursted)"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Burst end (Wheel of Fortune): Electric-code B3 "
                "allies Strength — ATK +180% of caster's ATK for 15 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_END,
                condition="Wheel of Fortune state active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=180.0,
                    duration_seconds=15.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: Electric-code allies Wheel of Fortune — Attack "
                "Damage +10% for 10 sec; 300% ATK damage to all enemies "
                "(Judgement: Damage Taken +10% for 10 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=10.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric RL B2 — Electric-code B3 force multiplier. Pairs "
        "with Modernia / Snow White: Heavy Arms-style EleC carries; "
        "Wheel of Fortune state is gated on her own burst, so the "
        "180% Attack Damage / 180% ATK buffs only fire after she's "
        "bursted."
    ),
)
register_character(_SKILL)
