"""Soldier OW — B1 Fire SMG Elysion. Fire-element ammo support.

Encoded from the live ``Character`` skill descriptions in the DB.
A simple kit: probabilistic bonus damage (S1), top-3-ATK Cover DEF
buff (S2), and a Fire-element team Max-Ammo burst.

**Source description (S1)**:

    There is a 10% chance of activating after casting normal attack(s).
    Affects the target(s). Deals 75.6% of final ATK as additional damage.

**Source description (S2)**:

    Affects 3 ally unit(s) with the highest ATK.
    Cover's DEF ▲ 128.57% for 5 sec.

**Source description (Burst)**:

    Affects all allies with Fire Element. Max Ammunition Capacity ▲ 280% for 10 sec.
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
    character_name="Soldier OW",
    skill1=(
        SkillEffect(
            description=(
                "10% chance per normal attack: target takes 75.6% of "
                "ATK additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="10% chance per normal attack (probabilistic)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.756,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: top-3 ATK allies Cover DEF +128.57% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=3),
                    magnitude=128.57,
                    duration_seconds=5.0,
                    notes="actually 'Cover DEF' — distinct from member DEF",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all Fire-element allies Max Ammo +280% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=280.0,
                    duration_seconds=10.0,
                    notes="filtered to Fire-element allies (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Soldier OW's element-locked +280% Max Ammo is huge for "
        "Fire-element attack comps (Modernia, RH, Asuka, Drake). "
        "Niche but powerful when the comp aligns."
    ),
)
register_character(_SKILL)
