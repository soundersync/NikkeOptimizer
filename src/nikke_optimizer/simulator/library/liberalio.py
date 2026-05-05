"""Liberalio — Wind SR B3, single-target carry with charge-speed tricks.

Encoded from the live ``Character`` skill descriptions in the DB.
Liberalio's S2 has a state-machine ("Raging Current" vs "Gentle Current")
that flips on whether the hit target is the stage target. We encode
the headline buffs; the state flip is a DSL gap noted on each skill.

**Source description (S1)**:

    Activates when entering Full Burst. Affects self. ATK ▲ 160% for
    3 sec.
    Activates when landing Full Charge attacks on a target's core.
    Affects self. Attack Damage ▲ 20.83% for 60 sec.
    Activates when landing Full Charge attacks. Affects target(s).
    Deals 40.5% of final ATK as additional damage. Activates 5 times.
    Activates when entering Full Burst. Affects 1 Burst Stage 3 ally
    unit(s) with the lowest final ATK. Charge Speed ▲ 12.74% of
    caster's Charge Speed for 10 sec.

**Source description (S2)**:

    Activates when landing Full Charge attacks. Affects self if the
    enemy hit is the stage target. Raging Current: Attack Damage
    ▲ 231% continuously. Removes Gentle Current.
    Activates when landing Full Charge attacks. Affects self if the
    enemy hit is a Rapture that is not the stage target. Gentle
    Current: Fixes Charge Time at 1 sec continuously. Dispels Raging
    Current.
    Activates at battle start. Affects self. Gains immunity to Charge
    Speed effects continuously.

**Source description (Burst)**:

    Affects self. Attack Damage ▲ 50% for 10 sec.
    Affects all enemies. Deals 925% of final ATK as additional damage.
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
    character_name="Liberalio",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst entry: self ATK +160% for 3 sec (massive "
                "burst-window self-buff)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=160.0,
                    duration_seconds=3.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Charge core hit: self Attack Damage +20.83% for "
                "60 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands on target core",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.83,
                    duration_seconds=60.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Charge hit: 40.5% ATK additional damage to target. "
                "Activates 5 times max per battle."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands (max 5 activations/battle)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.405,
                    notes="capped at 5 activations per battle (DSL gap)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst entry: lowest-ATK B3 ally gets Charge Speed "
                "+12.74% of caster's Charge Speed for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=1),
                    magnitude=12.74,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'lowest ATK' filtered to B3 — encoded "
                        "as ALLY_LOWEST_HP placeholder"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Charge hit on stage target: self Attack Damage "
                "+231% continuously (Raging Current state)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge lands on stage target (Raging Current)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=231.0,
                    duration_seconds=86400.0,
                    notes=(
                        "state-machine: removes Gentle Current; only "
                        "active while in Raging Current state (DSL gap)"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Battle start: self gains immunity to Charge Speed "
                "buffs/debuffs continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes="immunity to charge-speed effects (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Attack Damage +50% for 10 sec; deals 925% "
                "of ATK to all enemies as additional damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=50.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=9.25,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SR B3 — single-target carry with a massive 160% ATK self-"
        "buff during the FB window. Pairs with B1+B2 supporters that "
        "set up the Raging Current state-flip on the stage target."
    ),
)
register_character(_SKILL)
