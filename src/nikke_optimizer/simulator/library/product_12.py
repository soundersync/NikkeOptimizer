"""Product 12 — B3 Fire MG Missilis. Basic Recruit AOE attacker.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit with a single-target nuke (S2) and AOE burst.

**Source description (S1)**:

    Affects self. Activates after 200 normal attack(s). ATK ▲ 8.28% for 5 sec.

**Source description (S2)**:

    Affects 1 enemies with the lowest HP. Deals 109.09% of final ATK as damage.

**Source description (Burst)**:

    Affects enemies within attack range. Deals 720% of final ATK as damage.
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
    character_name="Product 12",
    skill1=(
        SkillEffect(
            description="Every 200 normal attacks: self ATK +8.28% for 5 sec.",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=200),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=8.28,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Periodic: 109.09% of ATK to lowest-HP enemy.",
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP),
                    magnitude=1.0909,
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
