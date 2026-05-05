"""Yulha — B3 Fire SR Tetra. Calm-state crit carry.

Encoded from the live ``Character`` skill descriptions in the DB. Yulha's
identity is the Calm state — built up from damage taken, drives a Crit
Rate +24.53% buff and the doubled-burst payout. Her S2 saves the team
by ATK-buffing and damage-sharing the 5 lowest-HP allies.

**Source description (S1)**:

    Activates when attacked 30 times. Affects self.
    Calm: Critical Rate ▲ 24.53% for 20 sec.

**Source description (S2)**:

    Affects 5 allies with the lowest HP. ATK ▲ 90.75% for 5 sec.
    Shares damage taken for 10 sec.

**Source description (Burst)**:

    Affects all enemies. Deals 457.87% of final ATK as damage.

    Affects the same targets when under Calm status.
    Deals 457.87% of final ATK as damage.
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
    character_name="Yulha",
    skill1=(
        SkillEffect(
            description=(
                "Every 30 hits taken: self Calm — Crit Rate +24.53% "
                "for 20 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                every_n_hits=30,
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=24.53,
                    duration_seconds=20.0,
                    notes="'Calm' state — gates her burst doubling",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: 5 lowest-HP allies ATK +90.75% 5 sec; "
                "share damage taken 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=90.75,
                    duration_seconds=5.0,
                    notes=(
                        "actually '5 lowest-HP allies' — given a 5-team "
                        "size this is effectively ALL_ALLIES."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'shares damage taken for 10 sec' — "
                        "DSL has no SHARE_DAMAGE kind. 0-mag with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all enemies take 457.87%; if Calm, +457.87% "
                "additional."
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
                    notes=(
                        "Calm-state conditional — DSL has no "
                        "state-machine triggers; encoded as second "
                        "damage instance with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Yulha is a damage-tanking SR carry — Calm state stacks from "
        "30 hits taken (extends a 20-sec window) and then her burst "
        "double-tap fires for 915.74% AOE total. Pairs with damage-"
        "sharing tanks (Jackal, Centi) and the broader 'damage taken' "
        "ecosystem."
    ),
)
register_character(_SKILL)
