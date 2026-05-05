"""Noir — Wind SG B3, SG-comp finisher.

Encoded from the live ``Character`` skill descriptions. Noir's S2
gives a team Ammo + reload boost on Full Burst entry; her burst
deals heavy damage and grants SG-only Hit Rate / Damage to Parts.

**Source description (S1)**:

    Activates when above 70% HP. Affects all allies. ATK ▲ 14.08% of
    caster's ATK constantly.

**Source description (S2)**:

    Activates when entering Full Burst. Affects all allies. Max
    Ammunition Capacity ▲ 5 rounds for 10 sec. Reload 39.88%
    magazine(s).

**Source description (Burst)**:

    Affects all enemies. Deals 351.64% of final ATK as damage.
    Affects all allies with a Shotgun. Hit Rate ▲ 13.93% for 10 sec.
    Damage to interruption part ▲ 23.23% for 10 sec.
    Activates when Full Burst ends with an ally from the same squad
    on the battlefield. Affects all allies. Hit Rate ▲ 11.61% for
    30 sec. Damage to interruption part ▲ 19.36% for 30 sec.
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
    WeaponClass,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Noir",
    skill1=(
        SkillEffect(
            description=(
                "While self HP > 70%: all allies ATK +14.08% of caster's "
                "ATK continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self HP > 70%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.08,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Burst entry: all allies Max Ammo +5 rounds and "
                "reload 39.88% of magazine for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.0,
                    duration_seconds=10.0,
                    notes="ammo capacity is a flat +5, not %",
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=39.88,
                    duration_seconds=10.0,
                    notes="actually 'reload 39.88% of magazine' one-shot",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 351.64% ATK to all enemies; SG allies Hit Rate "
                "+13.93% and Damage to Parts +23.23% for 10 sec; team "
                "Hit Rate +11.61% / Damage to Parts +19.36% for 30 sec "
                "after FB ends (squad condition)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.5164,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=13.93,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=23.23,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Squad condition: when Full Burst ends with a same-squad "
                "ally alive, team Hit Rate +11.61% and Damage to Parts "
                "+19.36% for 30 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_END,
                condition="same-squad ally on battlefield",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.61,
                    duration_seconds=30.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=19.36,
                    duration_seconds=30.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SG B3 — SG-comp finisher with team ATK passive (above "
        "70% HP) and SG-filtered Hit Rate / parts buffs on burst. "
        "Pairs with Tove for SG burst-damage stacking."
    ),
)
register_character(_SKILL)
