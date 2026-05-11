"""Soldier EG — B3 Electric AR Elysion. Basic Recruit self-ATK attacker.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit with chance-on-hit self ATK + Max Ammo buff
and a generic AOE burst.

**Source description (S1)**:

    When a normal attack hits, there is a 5% chance of affecting self.
    ATK ▲ 7.92% for 5 sec.

**Source description (S2)**:

    Affects self. Max Ammunition Capacity ▲ 112.77% for 5 sec.

**Source description (Burst)**:

    Affects enemy unit(s) within attack range. Deals 720% of final ATK as damage.
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
    character_name="Soldier EG",
    skill1=(
        SkillEffect(
            description="5% chance per normal attack: self ATK +7.92% for 5 sec.",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="5% chance per normal attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=7.92,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Periodic: self Max Ammo +112.77% for 5 sec.",
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=112.77,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: 720% of ATK to all enemies in range.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=7.2,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Basic Recruit. Tutorial/early-game; no PvP relevance.",
)
register_character(_SKILL)
