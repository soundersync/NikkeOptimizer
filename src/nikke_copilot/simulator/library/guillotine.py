"""Guillotine — Electric MG B3, single-target executioner.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    After 30 normal attacks: self Crit Rate +9.28% for 10 sec, HP -2.01%.

**Source description (S2)**:

    After 150 normal attacks: self Crit Damage +14.69% for 5 sec.
    HP < 70%: self ATK +0.96% per 1% HP loss continuously.

**Source description (Burst)**:

    Highest-ATK enemy: 1237.5% of ATK as damage.
    Same target if HP < 50%: +1237.5% additional damage.
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
    character_name="Guillotine",
    skill1=(
        SkillEffect(
            description=(
                "Every 30 normal attacks: self Crit Rate +9.28% for "
                "10 sec (HP -2.01%)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=30),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=9.28,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 150 normal attacks: self Crit Damage +14.69% for "
                "5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=150),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=14.69,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When self HP < 70%: self ATK +0.96% per 1% HP lost "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self HP < 70%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.96,
                    duration_seconds=86400.0,
                    notes="scales with HP loss (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 1237.5% ATK damage to highest-ATK enemy; "
                "+1237.5% additional if target HP < 50%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=12.375,
                    notes="actually highest-ATK enemy filter",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=12.375,
                    notes="conditional on target HP < 50% (execute)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric MG B3 — single-target executioner with execute "
        "doubling at <50% target HP. Older meta; outshone by "
        "Guillotine: Winter Slayer in current PvP."
    ),
)
register_character(_SKILL)
