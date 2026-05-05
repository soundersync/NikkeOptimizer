"""Rem — B2 Water MG Abnormal (Re:Zero collab).

Encoded from the live ``Character`` skill descriptions in the DB.
Rem is the RL-comp B2 — a Demon's Breath self-stacker that shares
HP recovery with high-ATK RL allies. Pairs natively with Emilia / Red
Hood / Maxwell rocket teams.

**Source description (S1)**:

    Activates after landing 15 normal attack(s) in Demon's Breath status.
    Affects self. ATK ▲ 4.22%, stacks up to 30 times and lasts for 10 sec.

    Activates when using Burst Skill. Affects all allies.
    Shares HP recovery for 10 sec.

**Source description (S2)**:

    Activates when entering battle. Affects self.
    Recovers 42.24% of attack damage as HP continuously.

    Activates when entering battle. Affects self and 2 Rocket
    Launcher-wielding ally units with the highest ATK.
    Shares HP recovery continuously.

**Source description (Burst)**:

    Affects self. Demon's Breath: Critical Rate ▲ 37.8% for 10 sec.

    Affects all allies with a Rocket Launcher.
    ATK ▲ 50.78% of caster's ATK for 10 sec.
    Max Ammunition Capacity ▲ 5 round(s) for 10 sec.
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
    character_name="Rem",
    skill1=(
        SkillEffect(
            description=(
                "Every 15 normal attacks in Demon's Breath: self ATK "
                "+4.22% (stacks 30x, 10 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=15,
                condition="Demon's Breath state active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=4.22,
                    duration_seconds=10.0,
                    stacks_max=30,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use: all allies share HP recovery 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'shares HP recovery' — DSL has no "
                        "SHARE_HP_RECOVERY kind. 0-mag with note flag."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self lifesteal 42.24% of damage "
                "continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=4.224,
                    duration_seconds=999.0,
                    notes=(
                        "actually 'recover 42.24% of attack damage as "
                        "HP' — lifesteal. DSL gap."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Battle start: self + 2 highest-ATK RL allies share "
                "HP recovery continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    notes=(
                        "actually 'self + 2 highest-ATK RL allies; "
                        "shares HP recovery' — DSL has no weapon-class "
                        "filter, no HP-share kind. 0-mag with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Demon's Breath Crit Rate +37.8% 10 sec; "
                "RL allies ATK +50.78% (of caster ATK) and Max Ammo "
                "+5 for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=37.8,
                    duration_seconds=10.0,
                    notes="'Demon's Breath' state — gates her S1 stacking",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.RL,
                    ),
                    magnitude=50.78,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.RL,
                    ),
                    magnitude=5.0,
                    duration_seconds=10.0,
                    notes="flat +5 rounds (not %)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Rem is a B2 RL-comp anchor — buffs Max Ammo +5 and ATK by "
        "her own ATK (a flat add). Pairs natively with Emilia (the "
        "two collab carry/support pair), Red Hood, Maxwell, Helm "
        "burst (which also adds RL synergy via Modernia/Drake). "
        "Demon's Breath state is undocumented in DSL."
    ),
)
register_character(_SKILL)
