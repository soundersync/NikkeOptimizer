"""Laplace (Treasure) — Iron RL B3, Hero-Vision pierce/true-damage carry.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Full Charge attack: self Hero Vision — Explosion Range +3.57%,
    max 5 stacks, 15 sec.

**Source description (S2)**:

    Full Charge hit: target takes 132.45% ATK additional damage.
    Parts hit: target body takes 14.78% ATK additional damage.

**Source description (Burst)**:

    Self weapon swap: 1455.72% ATK initial + 22.2% ATK DOT for 10 sec.
    Pierce. When Hero Vision fully stacked: normal damage as true damage.
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
    character_name="Laplace (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "Full Charge attack: self Hero Vision — Explosion Range "
                "+3.57%, max 5 stacks, 15 sec each."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.57,
                    duration_seconds=15.0,
                    stacks_max=5,
                    notes="actually 'Explosion Range' (DSL gap)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge hit: target takes 132.45% ATK additional "
                "damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.3245,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon swap (1455.72% ATK initial + 22.2% "
                "ATK DOT for 10 sec). Pierce. At Hero Vision max stacks: "
                "normal damage applied as true damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=14.5572,
                    notes="initial weapon-swap payload",
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes="conditional on Hero Vision max stacks (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron RL B3 (Treasure) — Hero-Vision-stacked true-damage carry. "
        "Counters high-DEF stall comps once Hero Vision is fully stacked."
    ),
)
register_character(_SKILL)
