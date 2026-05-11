"""iDoll Sun — B3 Iron AR Tetra. Basic Recruit self-buff attacker.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit AR: small self-DEF and self-ATK procs, Max Ammo
burst.

**Source description (S1)**:

    Affects self. Activates after landing 10 normal attack(s).
    DEF ▲ 7.56% for 5 sec.

**Source description (S2)**:

    There is a 20% chance to activate when attacked. ATK ▲ 9.09% for 5 sec.

**Source description (Burst)**:

    Affects self. Max Ammunition Capacity ▲ 787.5% for 10 sec.
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
    character_name="iDoll Sun",
    skill1=(
        SkillEffect(
            description="Every 10 normal attacks: self DEF +7.56% for 5 sec.",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=7.56,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="20% chance on damage taken: self ATK +9.09% for 5 sec.",
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="20% chance per hit taken",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=9.09,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: self Max Ammo +787.5% for 10 sec.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=787.5,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Basic Recruit. Tutorial/early-game; no PvP relevance.",
)
register_character(_SKILL)
