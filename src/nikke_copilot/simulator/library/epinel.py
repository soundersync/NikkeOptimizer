"""Epinel — Wind SMG B3, kill-stacking burst-gen carry.

Encoded from the live ``Character`` skill descriptions. Epinel is a
classic kill-stacking carry — her S1 stacks ATK on kills, fueling a
high-damage burst.

**Source description (S1)**:

    Activates when killing an enemy. Affects self. Total Noob:
    ATK ▲ 13.86%, max 5 stacks, 15 sec.

**Source description (S2)**:

    Activates when last bullet hits target. Affects self.
    Critical Rate ▲ 5.05% for 5 sec. Critical Damage ▲ 6.4% for 5 sec.

**Source description (Burst)**:

    Affects all enemies. Deals 457.87% of final ATK as damage.
    When Total Noob is fully stacked: +457.87% additional damage to
    same targets.
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
    character_name="Epinel",
    skill1=(
        SkillEffect(
            description=(
                "On enemy kill: self Total Noob — ATK +13.86%, max 5 "
                "stacks, 15 sec each."
            ),
            trigger=Trigger(kind=TriggerKind.ON_KILL),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.86,
                    duration_seconds=15.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On last-bullet hit: self Crit Rate +5.05% and Crit "
                "Damage +6.4% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=5.05,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.4,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 457.87% ATK damage to all enemies; +457.87% "
                "additional when Total Noob fully stacked."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.5787,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.5787,
                    notes="conditional on Total Noob fully stacked (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SMG B3 — kill-stack carry. PvP usage hinges on getting "
        "kills to stack Total Noob before her burst; in 5v5 stall "
        "matchups her stacks may not build fast enough for the second "
        "burst payload to fire."
    ),
)
register_character(_SKILL)
