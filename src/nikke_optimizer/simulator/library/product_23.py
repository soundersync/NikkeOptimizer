"""Product 23 — B2 Wind SG Missilis. Basic Recruit self-DEF + DEF debuff.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit with self-DEF on last-bullet, lifesteal S2,
and an AOE DEF debuff burst.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects self.
    DEF ▲ 8.1% for 10 sec.

**Source description (S2)**:

    Affects self. Recover 16.15% of attack damage as HP over 10 sec.

**Source description (Burst)**:

    Affects 2 enemy unit(s) with the highest ATK. DEF ▼ 48.75% for 5 sec.
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
    character_name="Product 23",
    skill1=(
        SkillEffect(
            description="On last-bullet hit: self DEF +8.1% for 10 sec.",
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=8.1,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: self recovers 16.15% of attack damage as HP "
                "over 10 sec (lifesteal)."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.615,
                    duration_seconds=10.0,
                    notes=(
                        "lifesteal — heal = 16.15% of attack damage; DSL "
                        "has no LIFESTEAL kind; encoded as HEAL_PER_SECOND."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: top-2 ATK enemies DEF -48.75% for 5 sec.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES, count=2),
                    magnitude=48.75,
                    duration_seconds=5.0,
                    notes="top-2 highest-ATK enemies",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Basic Recruit. Tutorial/early-game; no PvP relevance.",
)
register_character(_SKILL)
