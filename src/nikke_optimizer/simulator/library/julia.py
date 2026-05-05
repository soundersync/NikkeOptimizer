"""Julia — Iron AR B3, anti-high-DEF carry with Crescendo stacks.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Affects self. Critical Rate ▲ 26.04% for 10 sec.

**Source description (S2)**:

    Activates when last bullet hits target. Affects self. Crescendo:
    Critical Damage ▲ 24.79%, max 5 stacks, 15 sec.

**Source description (Burst)**:

    Affects 5 highest-DEF enemies. Deals 544.5% of final ATK as damage.
    Affects same targets when Crescendo is fully stacked. Deals 544.5%
    of final ATK as additional damage.
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
    character_name="Julia",
    skill1=(
        SkillEffect(
            description=(
                "Self Crit Rate +26.04% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=26.04,
                    duration_seconds=10.0,
                    notes="passive — encoded as ALWAYS",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On last bullet hit: self Crescendo — Crit Damage +24.79%, "
                "max 5 stacks, 15 sec each."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=24.79,
                    duration_seconds=15.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 544.5% ATK damage to 5 highest-DEF enemies; "
                "+544.5% additional when Crescendo fully stacked."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=5.445,
                    notes="actually 5 highest-DEF enemies",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=5.445,
                    notes="conditional on Crescendo fully stacked",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron AR B3 — anti-high-DEF carry. Crescendo stacks on last-"
        "bullet hits (rare in fast-firing AR), but the burst payload "
        "is huge against high-DEF defender comps once stacks build."
    ),
)
register_character(_SKILL)
