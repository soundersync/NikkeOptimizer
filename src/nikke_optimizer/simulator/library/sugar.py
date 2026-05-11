"""Sugar — Iron SG B3, shotgun-team buffer / self-DPS.

Encoded from the live ``Character`` skill descriptions in the DB.
Sugar is a niche B3 — a shotgun-comp enabler with a self-targeted attack-
speed burst. Pairs with other SG attackers (Modernia, Privaty:UC) to
crank up their ammo capacity during Full Burst.

**Source description (S1)**:

    ■ Affects self. 20% chance of casting when Cover is under attack.
    Critical Damage ▲ 16.39% for 10 sec. Reloading Speed ▲ 12.12% for
    10 sec.

**Source description (S2)**:

    ■ Affects self. Cast when entering Full Burst. Critical Rate ▲
    13.02% for 10 sec.
    ■ Affects all allies with a Shotgun. Cast when entering Full
    Burst. Max Ammunition Capacity ▲ 83.08% for 10 sec.

**Source description (Burst)**:

    ■ Affects self. ATK Speed ▲ 66% for 15 sec. Hit Rate ▲ 33% for
    15 sec.
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
    WeaponClass,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Sugar",
    skill1=(
        SkillEffect(
            description=(
                "When cover takes damage (20% proc): self Crit Damage "
                "+16.39% and Reload Speed +12.12% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="cover under attack; 20% proc chance",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=16.39,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.12,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry: self Crit Rate +13.02% and all "
                "SG allies Max Ammo +83.08% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.02,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=83.08,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Attack Speed +66% and Hit Rate +33% for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=66.0,
                    duration_seconds=15.0,
                    notes=(
                        "actually 'Attack Speed +66%'; DSL has no "
                        "ATTACK_SPEED kind — encoded as BUFF_HIT_RATE proxy"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=33.0,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=15.0,
    notes=(
        "Iron SG B3 — niche SG-comp ammo buffer + self-attack-speed "
        "burst. Outshone by modern B3s but the 83% SG-ally Max-Ammo "
        "buff is unique and useful in dedicated shotgun comps."
    ),
)
register_character(_SKILL)
