"""Eunhwa — Fire SR B2, last-bullet DEF-shred sniper.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    On last-bullet hit (cast after firing): self Charge Damage +37.28%
    for 2 shots, Charge Speed +15.53% for 2 rounds.

**Source description (S2)**:

    On last-bullet hit: target DEF -29% for 5 sec.

**Source description (Burst)**:

    10 highest-ATK enemies: 85.62% ATK damage, DEF -2.43% for 15 sec.
    All allies: Crit Rate +4.65% for 15 sec.
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
    character_name="Eunhwa",
    skill1=(
        SkillEffect(
            description=(
                "On last-bullet hit: self Charge Damage +37.28% (2 "
                "shots), Charge Speed +15.53% (2 rounds)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=37.28,
                    duration_seconds=2.0,
                    notes="actually 2 shots not 2 sec (DSL gap)",
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.53,
                    duration_seconds=2.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On last-bullet hit: target DEF -29% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=29.0,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 85.62% ATK damage to 10 highest-ATK enemies, "
                "DEF -2.43% for 15 sec; all allies Crit Rate +4.65% "
                "for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.8562,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=4.65,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire SR B2 — last-bullet DEF-shred sniper. Niche; outshone by "
        "Eunhwa: Tactical Upgrade in current PvP."
    ),
)
register_character(_SKILL)
