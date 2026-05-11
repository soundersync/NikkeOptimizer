"""Zwei (Treasure) — Electric SG B1, upgraded Pierce support.

Encoded from the live ``Character`` skill descriptions in the DB. The
Treasure form adds stack-based Pierce Damage and Crit Rate buffs that
fire on every normal attack during Full Burst / Pierce Attacks 101
status. Charge time drops from 1.5 to 1.2 sec on the burst weapon, and
the lingering Pierce Damage buff increases from 15.48 to 25.03%.

**Source description (S1)**:

    ■ Activates when entering Full Burst. Affects all allies. Pierce
    Damage ▲ 20.13% for 1 round(s). Pierce Damage ▲ 10.06% for 10 sec.
    ■ Activates when performing a normal attack during Full Burst.
    Affects all allies. Pierce Damage ▲ 24.99%, stacks up to 3
    Time(s), for 1 round(s).

**Source description (S2)**:

    ■ Activates after 5 normal attack(s). Affects all allies. Recovers
    Cover's HP by 7.52%.
    ■ Activates when entering Full Burst. Affects all allies. Critical
    Rate ▲ 18.63% for 10 sec.
    ■ Activates when performing a normal attack while in Pierce
    Attacks 101 status. Affects all allies. Critical Rate ▲ 15% for
    5 sec, stacks up to 3 time(s).

**Source description (Burst)**:

    ■ Affects self. Changes the weapon in use: Charge Time 1.2 sec,
    Damage 50.69% of final ATK, Full Charge Damage 300%, Max Ammo 1,
    Additional Effect: Pierce.
    ■ Affects all allies. Pierce Attacks 101: Pierce Damage ▲ 25.03%
    for 10 sec.
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
    character_name="Zwei (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Pierce Damage +20.13% "
                "for 1 round, plus +10.06% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.13,
                    duration_seconds=1.0,
                    notes="actually '1 round' duration; DSL gap",
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.06,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every normal attack during Full Burst: all allies "
                "Pierce Damage +24.99% for 1 round, stacks 3x."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=24.99,
                    duration_seconds=1.0,
                    stacks_max=3,
                    notes="actually '1 round' duration; DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 5 normal-attack hits: all allies recover 7.52% "
                "of Cover's HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.52,
                    notes="recovers Cover HP (not Nikke HP)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Crit Rate +18.63% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=18.63,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every normal attack while in Pierce Attacks 101 status: "
                "all allies Crit Rate +15% for 5 sec, stacks 3x."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="while in Pierce Attacks 101 status (post-burst)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.0,
                    duration_seconds=5.0,
                    stacks_max=3,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon change — Charge 1.2s, Damage 50.69%, "
                "Full Charge 300%, Pierce. All allies enter Pierce "
                "Attacks 101: Pierce Damage +25.03% for 10 sec."
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
                    magnitude=0.5069,
                    notes=(
                        "weapon-change shot: 50.69% per shot, Full "
                        "Charge applies 300% multiplier"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=25.03,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Pierce Attacks 101: Pierce Damage "
                        "+25.03%' — named state; enables S1/S2 stacking "
                        "triggers"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SG B1 — Treasure form. Much stronger than base Zwei: "
        "stack-based Pierce Damage and Crit Rate during Full Burst, "
        "shorter charge time, bigger lingering buff. Top-tier B1 in "
        "Pierce-team comps; close to Liter's general utility."
    ),
)
register_character(_SKILL)
