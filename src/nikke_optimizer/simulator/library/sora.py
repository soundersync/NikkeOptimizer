"""Sora — Wind RL B1, healer/cleanser support with stack-storage mechanic.

Encoded from the live ``Character`` skill descriptions in the DB. Sora
is a heal-storage support — she boosts heal potency, stores excess
heals on allies (which then convert to ATK), and her burst dispels a
debuff while topping up the team.

**Source description (S1)**:

    ■ Activates when entering battle. Affects self. Potency of HP
    granted ▲ 35.2% continuously.

**Source description (S2)**:

    ■ Activates when an ally or self destroys an enemy's part. Affects
    all allies. Storage: Stores excess healing received by the caster,
    up to 5.36% of their max HP. Stacks up to 5 time(s) for 15 sec.
    ATK ▲ 23.74% of the caster's ATK for 15 sec.

**Source description (Burst)**:

    ■ Affects all allies. Recovers 52.27% of the caster's final max
    HP as HP. Dispels 1 debuff(s).
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
    character_name="Sora",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: self Potency of HP granted +35.2% "
                "continuously (heals from caster are 35.2% stronger)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=35.2,
                    duration_seconds=86400.0,
                    notes=(
                        "actually 'Potency of HP granted +35.2%' — heal "
                        "amplifier, not a heal-per-second; DSL gap, "
                        "encoded as HEAL_PER_SECOND proxy"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On part destroy (by self or ally): all allies gain "
                "Storage (5.36% Max HP cap, stacks 5x) and ATK +23.74% "
                "of caster's ATK for 15 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ally or self destroys an enemy part",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.36,
                    duration_seconds=15.0,
                    stacks_max=5,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes=(
                        "actually 'Storage' — stores excess healing up "
                        "to 5.36% Max HP; functions like a delayed "
                        "heal/shield; encoded as GRANT_SHIELD proxy"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=23.74,
                    duration_seconds=15.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies recover 52.27% of caster's Max HP "
                "and have 1 debuff dispelled."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=52.27,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.0,
                    notes="dispels 1 debuff per ally",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind RL B1 — heal-amp + cleanse support. Part-destroy trigger "
        "is the unique mechanic; pairs well with parts-target carries "
        "and stall-comp builds. ATK +23.74% of caster's ATK is a "
        "respectable team buff for an off-burst slot."
    ),
)
register_character(_SKILL)
