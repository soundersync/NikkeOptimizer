"""Tove — Water AR B1, crit / SG-comp support.

Encoded from the live ``Character`` skill descriptions in the DB. Tove
specializes in SG comps — her S2 crit-rate buff and Burst ATK boost
both check for SG-wielding allies and apply only to that subset.

**Source description (S1)**:

    There is a 5% chance of activating when attacking. Affects self.
    Emergency-Crafted Bullets: Reload 5.31% of the magazine(s).
    Activates during Emergency-Crafted Bullets. Affects all allies.
    Temporary Modification: Max Ammunition Capacity ▲ 2, stacks up to
    3 time(s) and lasts for 5 sec. Critical Damage ▲ 5.24% for 5 sec.

**Source description (S2)**:

    Only activates when Temporary Modification is fully stacked.
    Affects all allies. Critical Rate ▲ 3.32% continuously.
    Only activates when Temporary Modification is fully stacked.
    Affects all allies with a Shotgun. Attack Speed ▲ 42.24%
    continuously.

**Source description (Burst)**:

    Affects all allies. Miracle of Makeshifts: ATK ▲ 2.32% of caster's
    ATK. Mirrors the stack count of Temporary Modification. Lasts for
    10 sec.
    Affects all allies with a Shotgun. Miracle of Makeshifts: ATK ▲
    24.21% of caster's ATK. Mirrors the stack count of Temporary
    Modification. Lasts for 10 sec.
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
    character_name="Tove",
    skill1=(
        SkillEffect(
            description=(
                "5% chance on attack: self reload 5.31% magazine "
                "(Emergency-Crafted Bullets), then Temp Modification "
                "team buff: Ammo Capacity +2 (max 3 stacks, 5 sec), "
                "Crit Damage +5.24% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                condition="5% chance on attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.0,
                    duration_seconds=5.0,
                    stacks_max=3,
                    notes="ammo capacity is a flat +2, not %",
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.24,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "When Temporary Modification fully stacked: all allies "
                "Crit Rate +3.32% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Temporary Modification fully stacked",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.32,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Temp Modification fully stacked: SG allies "
                "Attack Speed +42.24% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Temporary Modification fully stacked",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=42.24,
                    duration_seconds=86400.0,
                    notes="actually 'Attack Speed' (DSL gap, encoded as RELOAD)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies ATK +2.32% of caster's ATK (mirrors "
                "Temp Modification stacks) for 10 sec; SG allies ATK "
                "+24.21% of caster's ATK for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.32,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    stacks_max=3,
                    notes="mirrors Temp Mod stack count (1-3)",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=24.21,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    stacks_max=3,
                    notes="SG-only, mirrors Temp Mod stack count (1-3)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water AR B1 — SG-comp specialist. Crit team buffs + a fat SG-"
        "filtered ATK boost on burst. Pairs naturally with Leona / "
        "Anis: Sparkling Summer-style SG carries."
    ),
)
register_character(_SKILL)
