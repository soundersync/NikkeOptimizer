"""Neon — B1 Fire SG Elysion. Crit-Rate Shotgun support.

Encoded from the live ``Character`` skill descriptions in the DB.
Neon is a budget Crit-Rate buffer: she gives top-2 ATK allies Crit on
kill, full-burst Crit Rate buffs all allies for 2 shots, and her burst
nukes the highest-DEF enemy + grants Shotgun allies Max Ammo.

**Source description (S1)**:

    Affects 2 allies with the highest ATK. Cast when killing an enemy.
    Critical Rate ▲ 3.56% for 5 sec.

**Source description (S2)**:

    Activates at the beginning of Full Burst. Affects all allies.
    Critical Rate ▲ 45.93% for 2 shots.

**Source description (Burst)**:

    Affects 1 enemy with the highest DEF. Deals 528.97% of final ATK as damage.
    Affects all allies with a Shotgun. Max Ammunition Capacity ▲ 3 for 10 sec.
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
    character_name="Neon",
    skill1=(
        SkillEffect(
            description=(
                "On kill: top-2 ATK allies get Crit Rate +3.56% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_KILL),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=3.56,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst start: all allies Crit Rate +45.93% for "
                "2 shots."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=45.93,
                    duration_seconds=5.0,
                    notes=(
                        "duration is 'next 2 shots', not seconds — "
                        "DSL has no per-shot duration; approximated as 5s."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 528.97% of ATK to highest-DEF enemy + all SG "
                "allies Max Ammo +3 for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=5.2897,
                    notes="actually highest-DEF enemy; target approx as highest-HP",
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=3.0,
                    duration_seconds=10.0,
                    notes="flat +3 rounds, SG-only",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Neon's big burst nuke is real (528% to highest-DEF), and the "
        "Shotgun Max Ammo buff is a nice SG-comp synergy. The Crit Rate "
        "buffs are small but consistent."
    ),
)
register_character(_SKILL)
