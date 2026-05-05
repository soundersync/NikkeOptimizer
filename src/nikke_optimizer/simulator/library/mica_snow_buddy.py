"""Mica: Snow Buddy — Iron SMG B1, defensive support / burst-gen battery.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Every 120 normal attacks: all allies Tidying Up — Damage Taken
    -2%, max 10 stacks, 15 sec.
    When Tidying Up fully stacked: all allies Max Ammunition Capacity
    +40% continuously.

**Source description (S2)**:

    Every 150 normal attacks: all allies +1 stack on stackable buffs.
    Battle start: self Burst Gauge filling speed +300% continuously.

**Source description (Burst)**:

    All allies: dispel 1 debuff, ATK +39.3% of caster's ATK for 5 sec.
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
    character_name="Mica: Snow Buddy",
    skill1=(
        SkillEffect(
            description=(
                "Every 120 normal attacks: all allies Tidying Up — "
                "Damage Taken -2%, max 10 stacks, 15 sec each."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.0,
                    duration_seconds=15.0,
                    stacks_max=10,
                    notes="actually 'Damage Taken -2%' (DSL gap, encoded as DEF)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Tidying Up fully stacked: all allies Max Ammunition "
                "+40% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Tidying Up fully stacked",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.0,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self Burst Gauge filling speed +300% "
                "continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=300.0,
                    notes="actually 'gauge fill speed +300%' (continuous)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies dispel 1 debuff and gain ATK +39.3% "
                "of caster's ATK for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=39.3,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_duration_seconds=5.0,
    notes=(
        "Iron SMG B1 — defensive support / burst-gen battery. The "
        "300% gauge-fill speed is huge for fast burst rotation in "
        "PvP; pairs with sustained-DPS comps that need ammo + tank."
    ),
)
register_character(_SKILL)
