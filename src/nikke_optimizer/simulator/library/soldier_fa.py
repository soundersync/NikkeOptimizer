"""Soldier FA — B2 Iron SG Elysion. Basic Recruit self-tank/lifesteal.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit: chance-on-damage-taken self DEF, lifesteal S2,
and self-Max-HP burst.

**Source description (S1)**:

    There is a 10% chance of activating when attacked. Affects self.
    DEF ▲ 9.09% for 10 sec.

**Source description (S2)**:

    Affects self. Recover 20.19% of attack damage as HP over 8 sec.

**Source description (Burst)**:

    Affects self. Max HP ▲ 112.5% for 10 sec.
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
    character_name="Soldier FA",
    skill1=(
        SkillEffect(
            description="10% chance on damage taken: self DEF +9.09% for 10 sec.",
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="10% chance per hit taken",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=9.09,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: self recovers 20.19% of attack damage as HP "
                "over 8 sec (lifesteal)."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.524,
                    duration_seconds=8.0,
                    notes=(
                        "lifesteal — 20.19% of attack damage / 8 sec; "
                        "approx 2.52% per sec."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: self Max HP +112.5% for 10 sec.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=112.5,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Basic Recruit. Tutorial/early-game; no PvP relevance.",
)
register_character(_SKILL)
