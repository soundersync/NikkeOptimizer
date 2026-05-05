"""Crow — B3 Fire SMG. ATK-debuff defender / sniper-finisher.

Encoded from the live ``Character`` skill descriptions in the DB.
Crow is an unusual B3 Defender — her S1 ATK debuff on FB entry +
last-bullet additional damage make her a debuff/finisher hybrid.
Burst is a single-target nuke on the highest-ATK enemy.

**Source description (S1)**:

    On entering Full Burst: all enemies — ATK -19.93% for 10s

**Source description (S2)**:

    Last bullet hits target: target — 89.09% of final ATK additional damage
    Last bullet hits target: self — DEF +12.72% for 5s

**Source description (Burst)**:

    Highest-ATK enemy: 915.75% of final ATK damage
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
    character_name="Crow",
    skill1=(
        SkillEffect(
            description="On FB entry: all enemies ATK -19.93% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=19.93,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Last bullet: target 89.09% additional + self DEF +12.72% 5s",
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.8909,
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.72,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: highest-ATK enemy 915.75% damage",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=9.1575,
                    notes="targets highest-ATK — ENEMY_HIGHEST_HP as proxy",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire SMG B3 hybrid — ATK debuff on FB entry + last-bullet "
        "finisher + 9.16x ATK single-target burst. Niche but useful "
        "vs Wind defenders thanks to Fire > Wind."
    ),
)
register_character(_SKILL)
