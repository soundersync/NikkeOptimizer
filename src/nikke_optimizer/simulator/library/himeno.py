"""Himeno — B2 Wind SR Abnormal. SR-team ATK/Ammo support.

Encoded from the live ``Character`` skill descriptions in the DB.
Himeno is a niche SR-comp enabler: she buffs only sniper-rifle allies
and grants Charge Damage / Crit to the highest-ATK ally on burst. Useful
in mono-SR teams (Maxwell, Snow White, Alice).

**Source description (S1)**:

    Activates when hitting a target with Full Charge. Affects the target.
    DEF ▼ 6.94% for 3 sec.

**Source description (S2)**:

    Affects all allies with sniper rifles. ATK ▲ 10.98% for 10 sec.
    Max Ammunition Capacity ▲ 2 round(s) for 10 sec.

**Source description (Burst)**:

    Affects 1 ally unit(s) with the highest ATK. Charge Damage ▲ 23.76%
    for 10 sec. Critical Rate ▲ 16.35% for 10 sec.
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
    character_name="Himeno",
    skill1=(
        SkillEffect(
            description="On Full Charge hit: target DEF -6.94% for 3 sec.",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge hit lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=6.94,
                    duration_seconds=3.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: sniper-rifle allies ATK +10.98% and Max Ammo "
                "+2 rounds for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SR,
                    ),
                    magnitude=10.98,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SR,
                    ),
                    magnitude=2.0,
                    duration_seconds=10.0,
                    notes="flat +2 rounds, not %",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: highest-ATK ally Charge Damage +23.76% and Crit "
                "Rate +16.35% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=23.76,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=16.35,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Himeno's SR-only filter on S2 limits her to mono-SR comps. "
        "Burst-targeted Charge Damage + Crit on top-ATK ally pairs well "
        "with Snow White / Maxwell / Alice carries."
    ),
)
register_character(_SKILL)
