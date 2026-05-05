"""Folkwang — B2 Water AR Tetra. Top-2 ATK shielder + lifesteal.

Encoded from the live ``Character`` skill descriptions in the DB.
Folkwang's S1+S2 protect the team's strongest attackers (top-2 ATK)
with shields + heal potency, plus a single-target taunt on the highest
ATK enemy. Her burst layers a beefy shield + lifesteal on the same
top-2.

**Source description (S1)**:

    Affects 2 targets with the highest ATK.
    Gain a shield equal to 13.71% of caster's final Max HP for 10 sec.
    HP Potency ▲ 45.7% for 10 sec.

**Source description (S2)**:

    Affects the target with the highest ATK. Taunt for 5 sec.
    Affects self. Max HP ▲ 44.96% for 10 sec.

**Source description (Burst)**:

    Affects 2 allies with the highest ATK.
    Gain a shield equal to 32.9% of caster's final Max HP for 10 sec.
    Restores 65.81% of attack damage as HP for 10 sec.
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
    character_name="Folkwang",
    skill1=(
        SkillEffect(
            description=(
                "Top-2 ATK allies: shield 13.71% of Folkwang's max HP "
                "+ HP Potency +45.7% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=13.71,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes="HP Potency +45.7% — heal-amplifier; DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Highest-ATK enemy: taunted 5 sec. Self: Max HP +44.96% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=1.0,
                    duration_seconds=5.0,
                    notes="taunts highest-ATK enemy onto Folkwang",
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=44.96,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: top-2 ATK allies get shield 32.9% of caster's "
                "max HP + lifesteal 65.81% of attack damage for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=32.9,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=6.581,
                    duration_seconds=10.0,
                    notes="lifesteal: 65.81% of attack damage as HP",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Folkwang's identity is bodyguard duty — taunt the strongest "
        "opposing attacker (S2) while shielding her own team's top-2 "
        "ATK with massive lifesteal during burst. Niche but effective "
        "against single-target burst-style opponents."
    ),
)
register_character(_SKILL)
