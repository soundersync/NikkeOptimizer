"""iDoll Ocean — B1 Water SMG Tetra. Basic Recruit healer.

Encoded from the live ``Character`` skill descriptions in the DB.
Basic R-rarity Recruit SMG healer: last-bullet & periodic heal on
lowest-HP ally, team heal burst.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects 1 ally
    unit(s) with the lowest HP. Recovers 4.86% of the caster's final
    Max HP as HP.

**Source description (S2)**:

    Affects 1 ally unit(s) with the lowest HP. Recovers 9.69% of the
    caster's final Max HP as HP.

**Source description (Burst)**:

    Affects all allies. Recovers 29.7% of the caster's final Max HP as HP.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="iDoll Ocean",
    skill1=(
        SkillEffect(
            description=(
                "On last-bullet hit: lowest-HP ally heals 4.86% of "
                "caster's Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=4.86,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: lowest-HP ally heals 9.69% of caster's Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=9.69,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies heal 29.7% of caster's Max HP.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=29.7,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Basic Recruit. Tutorial/early-game; no PvP relevance.",
)
register_character(_SKILL)
