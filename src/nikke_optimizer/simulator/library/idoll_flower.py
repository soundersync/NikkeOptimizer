"""iDoll Flower — B1 Wind RL Tetra. Basic Recruit ATK debuffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit RL: ATK debuffs on last-bullet and periodic top-ATK,
single-target burst nuke with Attract (taunt).

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects the target.
    ATK ▼ 16.52% for 5 sec.

**Source description (S2)**:

    Affects 1 enemy unit(s) with the highest ATK. ATK ▼ 39.37% for 5 sec.

**Source description (Burst)**:

    Affects 1 enemy unit(s) with the highest ATK. Deals 330.61% of final
    ATK as damage. Attract for 2 sec.
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
    character_name="iDoll Flower",
    skill1=(
        SkillEffect(
            description="On last-bullet hit: target ATK -16.52% for 5 sec.",
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=16.52,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Periodic: highest-ATK enemy ATK -39.37% for 5 sec.",
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ENEMIES, count=1),
                    magnitude=39.37,
                    duration_seconds=5.0,
                    notes="targets highest-ATK enemy",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 330.61% of ATK to highest-ATK enemy + Attract "
                "(taunt) for 2 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=3.3061,
                    notes="targets highest-ATK enemy",
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=1.0,
                    duration_seconds=2.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Basic Recruit. Tutorial/early-game; no PvP relevance.",
)
register_character(_SKILL)
