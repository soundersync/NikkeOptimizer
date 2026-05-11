"""Neve — B3 Water SG Tetra. Self-buff Pierce attacker.

Encoded from the live ``Character`` skill descriptions in the DB.
Neve is a selfish DPS Shotgun: her S1 nukes the lowest-HP enemy on
cooldown, her S2 grants self Pierce + ATK during Full Burst, and her
burst is purely self-Crit/Hit Rate.

**Source description (S1)**:

    Affects 1 enemy unit(s) with the lowest remaining HP. Deals 145.45%
    of final ATK as damage.

**Source description (S2)**:

    Activates when entering Full Burst. Affects self. Deals for Pierce
    for 2 round(s). ATK ▲ 124.8% for 2 round(s).

**Source description (Burst)**:

    Affects self. Critical Rate ▲ 31.95% for 20 sec. Hit Rate ▲ 22.04%
    for 20 sec.
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
    character_name="Neve",
    skill1=(
        SkillEffect(
            description=(
                "Periodic: 145.45% of ATK to lowest-HP enemy."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP),
                    magnitude=1.4545,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst start: self gains Pierce + ATK +124.8% "
                "for 2 rounds."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                    notes="2 rounds — approximated as Full Burst window",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=124.8,
                    duration_seconds=10.0,
                    notes="2 rounds — approximated as Full Burst window",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Crit Rate +31.95% and Hit Rate +22.04% "
                "for 20 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=31.95,
                    duration_seconds=20.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=22.04,
                    duration_seconds=20.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Neve is a fully-selfish B3 Shotgun DPS. Her Pierce + 124% ATK "
        "self-buff during Full Burst is the headline; Crit/Hit Rate "
        "burst extends her uptime."
    ),
)
register_character(_SKILL)
