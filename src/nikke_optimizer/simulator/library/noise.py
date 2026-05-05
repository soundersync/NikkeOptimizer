"""Noise — Electric RL B1, defensive support.

Encoded from the live ``Character`` skill descriptions in the DB.
Noise is a niche B1 RL focused on team durability — damage reduction,
taunt, and a Burst-window Max HP buff with sustained healing.

**Source description (S1)**:

    Activates when attacked 20 time(s). Affects all allies. Damage
    taken ▼ 10.66% for 20 sec.

**Source description (S2)**:

    Affects the target(s) when attacking with full charge. Taunt for
    2 sec.
    Affects self. Max HP ▲ 24.86% for 1.8 sec.

**Source description (Burst)**:

    Affects all allies. Constantly recovers 2.47% of caster's final
    Max HP every 1 sec for 10 sec. Maximum HP ▲ 49.5% for 10 sec.
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
    character_name="Noise",
    skill1=(
        SkillEffect(
            description=(
                "After being attacked 20 times: all allies' damage taken "
                "-10.66% for 20 sec (defensive trigger)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN, every_n_hits=20,
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.66,
                    duration_seconds=20.0,
                    notes="actually 'damage taken' debuff — encoded as DEF buff",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Charge attack: target taunted for 2 sec; self Max "
                "HP +24.86% for 1.8 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.0,
                    duration_seconds=2.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=24.86,
                    duration_seconds=1.8,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies regen 2.47% of caster's Max HP per "
                "second for 10 sec; Max HP +49.5% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.47,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=49.5,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric RL B1 — defensive utility (damage reduction, sustained "
        "healing, taunt). Niche pick for stall-heavy defense comps; "
        "less competitive than Tia/Liter for offensive lineups."
    ),
)
register_character(_SKILL)
