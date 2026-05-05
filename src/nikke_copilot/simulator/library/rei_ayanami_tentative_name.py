"""Rei Ayanami (Tentative Name) — B3 Wind AR Abnormal (Eva collab).

Encoded from the live ``Character`` skill descriptions in the DB. Rei
TN is the Annihilation State carry — Anti A.T. Field damage stacker
+ on-burst self Attack State drives a 990.2% AOE burst.

**Source description (S1)**:

    Activates after landing 18 normal attacks. Affects target if in
    Anti A.T. Field status. Deals 590.64% of final ATK as additional
    damage. Stack count of Anti A.T. Field ▲ 10.

    Activates after landing 7 normal attacks when self is in Attack
    State. Affects target. Deals 286.37% of final ATK as additional
    damage.

    Activates when entering Full Burst. Affects all allies in
    Annihilation State.
        Units affected by Annihilation State's additional effect ▲ 1
            for 9 sec.
        Attack range of Annihilation State's additional effect ▲ 500%
            for 9 sec.
        ATK ▲ 17.6% of caster's ATK for 9 sec.

**Source description (S2)**:

    Activates when entering Full Burst. Affects all allies with a
    Machine Gun who have used their Burst Skills.
    MG heating up speed ▲ 100% for 13 sec.

    Activates when entering Full Burst. Affects all allies.
    ATK ▲ 11.61% of caster's ATK for 10 sec.

**Source description (Burst)**:

    Affects self. Attack State:
        Attack Damage ▲ 35.9% for 10 sec.
        ATK ▲ 63.36% of caster's ATK for 10 sec.

    Affects all enemies. Deals 990.2% of final ATK as Burst Skill damage.
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
    character_name="Rei Ayanami (Tentative Name)",
    skill1=(
        SkillEffect(
            description=(
                "Every 18 normal attacks (target in Anti A.T. Field): "
                "target takes 590.64% additional damage; AT Field "
                "stacks +10."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=18,
                condition="target in Anti A.T. Field",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=5.9064,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    notes=(
                        "Anti A.T. Field stack +10 — DSL has no AT Field "
                        "stacking system. 0-mag with note flag."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 7 normal attacks (self in Attack State): target "
                "takes 286.37% additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=7,
                condition="self in Attack State",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=2.8637,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: Annihilation State allies +1 "
                "AOE target, +500% range, ATK +17.6% of caster's ATK "
                "9 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=17.6,
                    duration_seconds=9.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="Annihilation State filter — DSL gap (state-machine)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry: MG allies who bursted get MG "
                "heat-up +100% for 13 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=100.0,
                    duration_seconds=13.0,
                    notes=(
                        "actually 'MG heating up speed +100%' on MG "
                        "allies who already bursted. DSL has no "
                        "MG_HEATUP / weapon-class filter / burst-history "
                        "filter. BUFF_RELOAD_SPEED proxy."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: all allies ATK +11.61% of "
                "caster's ATK 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.61,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Attack State (Attack Damage +35.9%, ATK "
                "+63.36% of caster's ATK 10 sec); all enemies take 990.2%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=35.9,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=63.36,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=9.902,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Rei: Tentative Name is the Wind-AR Eva collab carry — "
        "Annihilation State + Anti A.T. Field stacking drives sustained "
        "DPS, burst nukes for 990% AOE. Pairs natively with MG allies "
        "(Modernia, Rem in MG mode), and her S2 Anti A.T. Field "
        "interaction is unique among Eva collab units."
    ),
)
register_character(_SKILL)
