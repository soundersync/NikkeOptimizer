"""Nero — B2 Fire SMG Tetra Happy Zoo. Taunt-tank Defender with damage debuff.

Encoded from the live ``Character`` skill descriptions in the DB. Nero
is a high-HP Defender who layers Damage Taken reductions on herself
(Cat's Repayment stack), debuffs enemies who attack her (30% on-hit),
and taunts on burst with a Grumpy Cat HP-Potency self-buff.

**Source description (S1)**:

    On recovery taking effect (caster is healed): healer takes Damage
        Taken -14.14% for 5 sec.
    On recovery: self Cat's Repayment — Damage Taken -8.43%, stacks
        ×5, 5 sec.

**Source description (S2)**:

    30% on damage taken: attacker Damage Taken +8.26% for 5 sec.
    30% on damage taken (while in Grumpy Cat): 158.05% ATK damage to
        attacker.
    Battle start: self Max HP +60.28% continuously.

**Source description (Burst)**:

    Highest-HP enemy: 1104.91% ATK damage.
    Self: Attract — taunt all enemies for 15 sec.
    Self if Cat's Repayment fully stacked: Grumpy Cat — HP Potency
        +60.08% for 15 sec.
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
    character_name="Nero",
    skill1=(
        SkillEffect(
            description=(
                "On self heal received: healer Damage Taken -14.14% for "
                "5 sec; self Cat's Repayment (DT -8.43%, ×5, 5 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self receives a heal",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=14.14,
                    duration_seconds=5.0,
                    notes=(
                        "actually 'healer who applied the recovery'. "
                        "DSL has no HEAL_SOURCE target — proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=8.43,
                    duration_seconds=5.0,
                    stacks_max=5,
                    notes="Cat's Repayment — Damage Taken reduction",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "30% chance on damage taken: attacker takes DT +8.26% "
                "5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="30% chance",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=8.26,
                    duration_seconds=5.0,
                    notes="actually 'the attacker' — DSL has no ATTACKER target",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "30% chance on damage taken while in Grumpy Cat: deals "
                "158.05% ATK damage to attacker."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="30% chance and self in Grumpy Cat",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.5805,
                    notes="actually 'the attacker'",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Battle start: self Max HP +60.28% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.28,
                    duration_seconds=999.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: highest-HP enemy takes 1104.91% ATK; self Taunt "
                "15 sec; if Cat's Repayment 5/5 → Grumpy Cat (HP Potency "
                "+60.08% 15 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=11.0491,
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=15.0,
                    notes=(
                        "Grumpy Cat — HP Potency +60.08% (heal-potency "
                        "modifier, not a heal). DSL gap (HEAL_POTENCY); "
                        "0-mag flag. Conditional on full Cat's Repayment."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire SMG B2 Defender — tank/anti-tank hybrid. +60% Max HP "
        "passive makes her a sizable HP bag; heal-trigger Damage "
        "Taken reductions stack via Cat's Repayment, and her burst "
        "is a heavy single-target nuke + Taunt for protecting carries."
    ),
)
register_character(_SKILL)
