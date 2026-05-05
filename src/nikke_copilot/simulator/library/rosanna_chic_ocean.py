"""Rosanna: Chic Ocean — B2 Wind AR Tetra. Parts-destroy stacking buffer.

Encoded from the live ``Character`` skill descriptions in the DB. Rosanna:
CO buffs the team's Parts Damage at battle start, stacks ATK on parts
destruction, and her burst applies a 32% Damage Taken debuff to all
enemies — strong against parts-heavy bosses but also a generic AOE amp
in PvP.

**Source description (S1)**:

    Activates when entering battle. Affects all allies.
    Damage to Parts ▲ 24.26% for 15 sec.

    Activates when an ally or self destroys an enemy's part.
    Affects all allies. ATK ▲ 3% of caster's ATK, stacks up to 5 times
    and lasts for 30 sec.

**Source description (S2)**:

    Affects all allies. Damage to Parts ▲ 24.26% for 15 sec.

    Affects the enemy nearest to the crosshair.
    Deals 70.4% of final ATK as sustained damage every Sec for 15 sec.

**Source description (Burst)**:

    Affects all allies. Sustained Damage ▲ 20.32% for 10 sec.
    Affects all enemies. Damage Taken ▲ 32.23% for 10 sec.
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
    character_name="Rosanna: Chic Ocean",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: all allies Damage to Parts +24.26% "
                "for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=24.26,
                    duration_seconds=15.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On parts destroyed (any ally): all allies ATK +3% of "
                "caster's ATK (stacks 5x, 30 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="enemy parts destroyed by ally or self",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.0,
                    duration_seconds=30.0,
                    stacks_max=5,
                    notes=(
                        "actually 'ATK +3% of caster's ATK' — flat "
                        "value, cross-stat scaling. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: all allies Damage to Parts +24.26% 15 sec; "
                "nearest enemy takes 70.4% sustained damage/sec for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=24.26,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.704,
                    duration_seconds=15.0,
                    notes=(
                        "actually 'sustained damage every sec for 15 "
                        "sec' — INFLICT_BURN is the closest DOT kind."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Sustained Damage +20.32% 10 sec; "
                "all enemies Damage Taken +32.23% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.32,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=32.23,
                    duration_seconds=10.0,
                    notes="'Damage Taken +32.23%' — DEBUFF_DEFENSE proxy",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Rosanna: Chic Ocean is a parts-destruction stacking support — "
        "extra value vs parts-heavy bosses, but also a generic 32% "
        "Damage Taken debuff for all-enemy DPS rotations. Pairs with "
        "AOE attackers (Modernia / SBS / Maxwell)."
    ),
)
register_character(_SKILL)
