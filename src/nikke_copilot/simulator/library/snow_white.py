"""Snow White (base) — B3 Iron AR Pilgrim. Weapon-change pierce sniper.

Encoded from the live ``Character`` skill descriptions in the DB. Base
form Snow White is a simpler kit than her Heavy Arms version: a 30-hit
periodic damage trigger + Full Burst crit-rate self buff + a beefy
weapon-change burst.

**Source description (S1)**:

    Activates when normal attacks hits 30 times. Affects enemy targets.
    Deals 82.8% of final ATK as additional damage.

    Activates when normal attacks hits 30 times. Affects self.
    ATK ▲ 8.28% for 5 sec.

**Source description (S2)**:

    Affects enemies within the attack range.
    Deals 144.73% of final ATK as damage.

    Activates when attacking during Full Burst Time. Affects self.
    Critical Rate ▲ 26.1% for 10 sec.

**Source description (Burst)**:

    Affects self. Changes the weapon in use:
        Charge Time: 5 sec
        Damage: 499.5% of final ATK
        Full Charge Damage: 1000% damage
        Max Ammunition Capacity: 1 round
        Additional Effect: Pierce
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
    character_name="Snow White",
    skill1=(
        SkillEffect(
            description=(
                "Every 30 normal attacks: target takes 82.8% of ATK + "
                "self ATK +8.28% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=30),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.828,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=8.28,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic AOE: enemies in range take 144.73% of ATK."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.4473,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While in Full Burst window: self Crit Rate +26.1% "
                "for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="attacking during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=26.1,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon change — Charge 5s, Damage 499.5%, "
                "Full Charge multiplier 1000%, Max Ammo 1, Pierce."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=4.995,
                    notes="weapon change; Full Charge applies 1000% multiplier",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Base Snow White is the original Pilgrim sniper-burst — beefy "
        "1-shot Pierce nuke, slower than her Heavy Arms form. Pairs "
        "well with reload-speed buffers (Liter, Volume, Privaty)."
    ),
)
register_character(_SKILL)
