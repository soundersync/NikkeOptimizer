"""Marciana — B2 Iron SG Elysion. HP-Storage healer.

Encoded from the live ``Character`` skill descriptions in the DB.
Marciana's signature is the 'Storage' burst — overflow healing gets
banked as up to 27.87% of caster's Max HP, effectively shield-style
HP cushion.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects all allies.
    Recovers 10.95% of attack damage as HP over 3 sec.

    Activates when the last bullet hits the target. Affects 2 ally
    unit(s) with the highest ATK. HP Potency ▲ 26.98% for 3 sec.

**Source description (S2)**:

    Activates when using Burst Skill. Affects all allies.
    Recovers 28.11% of caster's final Max HP as HP.

**Source description (Burst)**:

    Affects all allies. Storage: If the target obtained a healing
    effect that exceeds the character's Max HP, excess portion will
    be stored, up to 27.87% of caster's Max HP, lasts for 10 sec.
    DEF ▲ 20.9% of caster's DEF for 10 sec.
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
    character_name="Marciana",
    skill1=(
        SkillEffect(
            description=(
                "On last bullet: all allies lifesteal-style heal "
                "(10.95% of attack damage over 3 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.65,
                    duration_seconds=3.0,
                    notes="actually 'recover 10.95% of attack damage over 3 sec'",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On last bullet: top-2 ATK allies HP Potency +26.98% "
                "for 3 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=0.0,
                    duration_seconds=3.0,
                    notes="HP Potency +26.98% — heal-amplifier; DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On burst: all allies recover 28.11% of Marciana's max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=28.11,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies get 'Storage' (excess heal banked up "
                "to 27.87% of Marciana's max HP for 10 sec) + DEF +20.9% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=27.87,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Storage' — excess heal becomes shield-"
                        "like buffer up to 27.87%. DSL gap (HEAL_OVERFLOW)."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.9,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Marciana's Storage mechanic is unique — when paired with a "
        "high-output healer (Tia, Naga, Helm burst), excess healing "
        "becomes effective shield. Pairs naturally with Bay (whose S2 "
        "heals all allies on Full Burst end)."
    ),
)
register_character(_SKILL)
