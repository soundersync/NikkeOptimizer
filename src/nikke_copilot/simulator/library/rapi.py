"""Rapi (base) — B3 Fire AR Elysion. Single-target taunt-and-burn.

Encoded from the live ``Character`` skill descriptions in the DB. Base
Rapi is a compact single-target carry — taunt + nuke S2 + bigger
nuke + self ATK buff burst.

**Source description (S1)**:

    Activates when attacked 20 time(s). Affects self.
    ATK ▲ 21.81% for 20 sec.

**Source description (S2)**:

    Affects 1 enemy with the highest ATK. [Target] Deals 528.97% of
    final ATK as damage. Taunt for 5 sec.

**Source description (Burst)**:

    Affects 1 enemy with the highest ATK. [Target] Deals 657.72% of
    final ATK as damage.

    Affects self. ATK ▲ 60.75% for 10 sec.
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
    character_name="Rapi",
    skill1=(
        SkillEffect(
            description=(
                "Every 20 hits taken: self ATK +21.81% for 20 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_DAMAGE_TAKEN),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.81,
                    duration_seconds=20.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: highest-ATK enemy takes 528.97% of ATK + "
                "taunted onto Rapi for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=5.2897,
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=5.0,
                    notes="taunts highest-ATK enemy onto Rapi",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: highest-ATK enemy takes 657.72% damage; self "
                "ATK +60.75% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=6.5772,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.75,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Base Rapi is a budget anti-tank: taunt + 528% S2 + 657% burst "
        "+ self ATK buff. Useful in PvE; outclassed in PvP by her "
        "Red Hood form."
    ),
)
register_character(_SKILL)
