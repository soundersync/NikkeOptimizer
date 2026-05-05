"""Mihara: Bonding Chain — B3 Fire MG Pilgrim. Chain-stack attacker
with sustained-damage payload.

Encoded from the live ``Character`` skill descriptions in the DB.
M:BC's identity is a two-tier stack engine: ``Restraint Chains`` (max
10) gate her damage swings, while each swing seeds ``Ensnaring
Chains`` stacks (max 20) on the target. Her burst converts
Ensnaring stacks into a mirrored sustained-damage tick across the
team.

**Source description (S1)**:

    On battle start: self charges 10 Restraint Chains (max 10)
    If caster used Burst Skill before Full Burst ends: self +10 Restraint Chains
    On specific timing: random enemy — 50.06% of final ATK damage; Chain -1 per hit
    Same target: Ensnaring Chains — 25.08% sustained damage / 1s, max 20 stacks

**Source description (S2)**:

    After 40 normal attacks during FB: target with Ensnaring → stacks +1
    On self incapacitated: target with Ensnaring → stacks +20
    On enemy neutralized (had Ensnaring): self Restraint Chain +1, max 10
    On entering Burst Stage 3: self Sustained Damage +59.98% for 10s

**Source description (Burst)**:

    Targets in Ensnaring Chains: Dragging Chain — 50.05% of final ATK
    sustained / 1s. Mirrors Ensnaring stack count to other targets for 10s.
    Removes Ensnaring after the effect.
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
    character_name="Mihara: Bonding Chain",
    skill1=(
        SkillEffect(
            description="At battle start: self +10 Restraint Chains (max 10)",
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    stacks_max=10,
                    notes="Restraint Chain counter; DSL gap (CHAIN_STACK)",
                ),
            ),
        ),
        SkillEffect(
            description="If caster bursts before FB ends: +10 Restraint Chains",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="before Full Burst ends",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    stacks_max=10,
                    notes="Restraint Chain refill; DSL gap (CHAIN_STACK)",
                ),
            ),
        ),
        SkillEffect(
            description="Periodic chain swing: random enemy 50.06% damage (Chain -1)",
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=1.0,
                condition="Restraint Chains > 0",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=1),
                    magnitude=0.5006,
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=1),
                    magnitude=0.2508,
                    duration_seconds=999.0,
                    stacks_max=20,
                    notes=(
                        "Ensnaring Chains: 25.08% of final ATK / 1s sustained, "
                        "max 20 stacks. Captured as INFLICT_BURN — closest "
                        "DOT analog in DSL."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Every 40 hits in FB: Ensnaring stack +1 on target",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=40,
                condition="during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    stacks_max=20,
                    notes="Ensnaring Chain stack increment",
                ),
            ),
        ),
        SkillEffect(
            description="On self incapacitated: Ensnaring +20 on target",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self incapacitated",
            ),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    stacks_max=20,
                    notes="Ensnaring stacks +20 (death payload)",
                ),
            ),
        ),
        SkillEffect(
            description="On enemy kill (had Ensnaring): self Restraint Chain +1",
            trigger=Trigger(
                kind=TriggerKind.ON_KILL,
                condition="target had Ensnaring Chains",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    stacks_max=10,
                    notes="Restraint Chain refill on kill",
                ),
            ),
        ),
        SkillEffect(
            description="Burst Stage 3 entry: self +59.98% Sustained Damage 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=59.98,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: Dragging Chain on Ensnaring targets 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.5005,
                    duration_seconds=10.0,
                    notes=(
                        "Dragging Chain: 50.05% of final ATK / 1s sustained. "
                        "Mirrors Ensnaring stack count to other targets for "
                        "10s. Removes Ensnaring after."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire MG B3 chain attacker. Two-tier stack engine "
        "(Restraint→Ensnaring) with sustained-damage payoff. Burst "
        "mirrors stacks across enemies — true mob-clear potential in PvE, "
        "weaker against single-target PvP defenders."
    ),
)
register_character(_SKILL)
