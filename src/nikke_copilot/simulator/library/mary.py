"""Mary — Water SG B1, sustain-focused healer.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    On last bullet hit: lowest-HP ally heals 8.4% of caster's Max HP.

**Source description (S2)**:

    Full Burst entry: all allies HP Potency +23.78% for 15 sec.

**Source description (Burst)**:

    Above 50% HP: all allies DEF +19.8% for 10 sec.
    All allies: heal 39.6% of caster's Max HP.
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
    character_name="Mary",
    skill1=(
        SkillEffect(
            description=(
                "On last-bullet hit: lowest-HP ally heals 8.4% of "
                "caster's Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=8.4,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Burst entry: all allies HP Potency +23.78% for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=23.78,
                    duration_seconds=15.0,
                    notes="actually 'HP Potency' (heal amplifier; DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: above 50% HP — all allies DEF +19.8% for 10 sec; "
                "all allies heal 39.6% of caster's Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=19.8,
                    duration_seconds=10.0,
                    notes="conditional on caster HP > 50%",
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=39.6,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SG B1 — sustain-focused healer. Niche; outshone by "
        "Mary: Bay Goddess in current PvP."
    ),
)
register_character(_SKILL)
