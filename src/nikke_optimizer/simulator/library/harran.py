"""Harran — Electric SR B3, virus-spread DOT carry.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    25% chance on attack: Virus Transfer — 17.28% ATK damage every 1
    sec for 5 sec on target.
    On killing virus-afflicted target: 2 nearby enemies inherit
    Virus Transfer.

**Source description (S2)**:

    Full Charge attack: self Pierce + Crit Rate +2.95% for 1 round.
    On enemy kill: self ATK +3.02%, max 15 stacks, 10 sec.

**Source description (Burst)**:

    Affects all enemies. 999% of ATK as damage.
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
    character_name="Harran",
    skill1=(
        SkillEffect(
            description=(
                "25% chance on attack: target Virus Transfer — 17.28% "
                "ATK damage every 1 sec for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                condition="25% chance per attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.1728,
                    duration_seconds=5.0,
                    notes="DoT, 1/sec ticks",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On killing virus-afflicted target: 2 nearby enemies "
                "inherit Virus Transfer."
            ),
            trigger=Trigger(kind=TriggerKind.ON_KILL),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=0.1728,
                    duration_seconds=5.0,
                    notes="virus spread to 2 nearby enemies (DSL gap)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge attack: self Pierce + Crit Rate +2.95% "
                "for 1 round."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=1.0,
                    notes="actually 1 round (DSL gap on round-vs-second)",
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.95,
                    duration_seconds=1.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On enemy kill: self ATK +3.02%, max 15 stacks, 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_KILL),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.02,
                    duration_seconds=10.0,
                    stacks_max=15,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 999% ATK damage to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=9.99,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SR B3 — DOT-spread sniper. Niche; better in waves of "
        "weak enemies than 1-2 high-HP targets. PvP usage limited."
    ),
)
register_character(_SKILL)
