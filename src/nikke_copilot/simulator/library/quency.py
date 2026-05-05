"""Quency — B2 Electric SMG Missilis. HP-Duplicate top-2 ATK supporter.

Encoded from the live ``Character`` skill descriptions in the DB.
Quency's S1 'duplicates' a fraction of the highest-HP ally's HP onto
herself (turning her into an effective tank when paired with high-HP
allies); her S2 + burst buff the team's top-2 ATK members.

**Source description (S1)**:

    Activates after 60 normal attack(s). Affects self.
    Duplicate 12.42% HP of ally with the highest HP, lasts for 10 sec.

**Source description (S2)**:

    Affects 2 ally unit(s) with the highest ATK. ATK ▲ 16.11% for 5 sec.

**Source description (Burst)**:

    Affects 2 ally unit(s) with the highest ATK.
    Max HP ▲ 43.87% for 5 sec. Critical Damage ▲ 29.9% for 10 sec.
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
    character_name="Quency",
    skill1=(
        SkillEffect(
            description=(
                "Every 60 normal attacks: self duplicates 12.42% of "
                "highest-HP ally's HP for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.42,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Duplicate 12.42% HP of highest-HP "
                        "ally' — borrows from a different stat. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: top-2 ATK allies ATK +16.11% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=16.11,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: top-2 ATK allies Max HP +43.87% (5s) + Crit "
                "Damage +29.9% (10s)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=43.87,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=29.9,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Quency is a budget B2 supporter — concentrates buffs on the "
        "team's top-2 ATK while gaining HP from the highest-HP ally. "
        "Pairs naturally with defenders that boost team Max HP "
        "(Bay, Ade, Tia)."
    ),
)
register_character(_SKILL)
