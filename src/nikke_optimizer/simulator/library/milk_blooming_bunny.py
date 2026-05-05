"""Milk: Blooming Bunny — Iron SR B3, Embarrassment-state pierce carry.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Full Charge attack: self Pierce for 6 sec.
    Full Charge held 0.5+ sec while not in Embarrassment: self enters
    Embarrassment — Forced Reload, +attack capability, +Distributed
    Damage. Effect 1: 290% of ATK Distributed Damage to all enemies.

**Source description (S2)**:

    Only in Embarrassment: self Pierce Damage ▲ 64.7% continuously.
    Only in Overconfident, Huh?! state: every 2 sec, all enemies take
    447.7% ATK as Distributed Damage.

**Source description (Burst)**:

    Self Overconfident, Huh?!: Immunity to Embarrassment for 10 sec.
    Pierce Damage ▲ 117.64% for 10 sec. ATK ▲ 220% for 10 sec.
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
    character_name="Milk: Blooming Bunny",
    skill1=(
        SkillEffect(
            description=(
                "Full Charge attack: self gains Pierce for 6 sec."
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
                    duration_seconds=6.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "While in Embarrassment: self Pierce Damage +64.7% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Embarrassment state active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=64.7,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst — Overconfident, Huh?!: self Pierce Damage "
                "+117.64% and ATK +220% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=117.64,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=220.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SR B3 — Embarrassment-state pierce carry with massive "
        "self-buff (220% ATK + 117% Pierce Damage) on burst. Niche "
        "until the Embarrassment state-machine is modeled."
    ),
)
register_character(_SKILL)
