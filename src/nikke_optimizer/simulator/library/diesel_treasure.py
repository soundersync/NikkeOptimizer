"""Diesel (Treasure) — Wind MG B2, attract-tank / ammo support.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Full Burst entry: self DEF +25.92% for 10 sec.
    Attacked while in Attract: self heals 12.96% of caster's Max HP.

**Source description (S2)**:

    Every 70 normal attacks: self Strawberry Candy — Max Ammo +56.7%,
    max 10 stacks, 10 sec.
    At max stacks (cleared): all allies reload 86.62% magazine.

**Source description (Burst)**:

    5 highest-ATK enemies: 299.98% ATK damage.
    Self: Max HP +100.05% for 10 sec, Attract taunt for 10 sec.
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
    character_name="Diesel (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst entry: self DEF +25.92% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.92,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 70 normal attacks: self Strawberry Candy — Max "
                "Ammo +56.7%, max 10 stacks, 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=70),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=56.7,
                    duration_seconds=10.0,
                    stacks_max=10,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "At max Strawberry Candy stacks: all allies reload "
                "86.62% magazine."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Strawberry Candy fully stacked → cleared",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=86.62,
                    notes="actually 'reload N% of magazine' one-shot",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 5 highest-ATK enemies take 299.98% ATK damage; "
                "self Max HP +100.05% for 10 sec, Attract taunt for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.9998,
                    notes="actually 5 highest-ATK enemies",
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.05,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind MG B2 (Treasure) — attract-tank with ammo support. "
        "100% Max HP burst makes her hard to kill during the FB window."
    ),
)
register_character(_SKILL)
