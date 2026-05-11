"""Rupee — B2 Iron AR Tetra Talentum. Iron-element buff-stack supporter.

Encoded from the live ``Character`` skill descriptions in the DB.
Rupee gives Iron allies a buff-stack +1 with Crit Rate every 100
hits, stacks Mileage ATK on herself, and her burst nukes all enemies
in range + buffs the team ATK at max Mileage stacks.

**Source description (S1)**:

    Every 100 normal attacks: all Iron type allies, stack count of
    buffs ▲ 1. Crit Rate ▲ 2.24% for 10 sec.

**Source description (S2)**:

    Every 30 attacks: self Mileage — ATK ▲ 13.8%, ×5 stacks, 15 sec.

**Source description (Burst)**:

    All enemies in range: 274.28% ATK damage.
    If Mileage fully stacked: all allies ATK +19.8% for 5 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Rupee",
    skill1=(
        SkillEffect(
            description=(
                "Every 100 normal attacks: Iron allies buff stack +1 + "
                "Crit Rate +2.24% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=100),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.IRON,
                    ),
                    magnitude=2.24,
                    duration_seconds=10.0,
                    notes="stack count of buffs +1 (meta-buff, DSL gap)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 30 attacks: self Mileage — ATK +13.8%, ×5, 15s."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=30),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.8,
                    duration_seconds=15.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all enemies in range take 274.28% ATK; if "
                "Mileage 5/5, all allies ATK +19.8% 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.7428,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=19.8,
                    duration_seconds=5.0,
                    notes="conditional on Mileage 5/5",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron AR B2 — Iron-element buff-stack supporter with a "
        "Mileage self-ramp. Pairs natively with Iron stack carries "
        "(e.g. Trony, Snow White:HA) via the buff-stack +1 mechanic. "
        "Standalone damage is modest; her value is enabling Iron comps."
    ),
)
register_character(_SKILL)
