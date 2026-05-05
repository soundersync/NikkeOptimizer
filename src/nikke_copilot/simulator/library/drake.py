"""Drake — B3 Fire SG Missilis. Hit-Rate + ATK team buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
A compact kit centered on team Hit-Rate + ATK buff at Full Burst entry,
with a 10-hit AOE secondary fire and a beefy AOE burst.

**Source description (S1)**:

    Activates at the beginning of Full Burst. Affects all allies.
    Hit Rate ▲ 11.85% for 10 sec. ATK ▲ 11.85% for 10 sec.

**Source description (S2)**:

    Activates after 10 hits. Affects 3 enemy unit(s) with the lowest
    remaining HP. Deals 98.55% of final ATK as damage.

**Source description (Burst)**:

    Affects enemies within the attack range.
    Deals 1254% of final ATK as damage.

    Affects self. Max Ammunition Capacity ▲ 72.18% for 10 sec.
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
    character_name="Drake",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Hit Rate +11.85% and "
                "ATK +11.85% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.85,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.85,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 10 normal attacks: 3 lowest-HP enemies take "
                "98.55% of ATK damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP, count=3),
                    magnitude=0.9855,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: enemies in range take 1254% of ATK damage; self "
                "Max Ammo +72.18% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=12.54,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=72.18,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Drake is a budget B3 attacker — her S1 Hit Rate buff is "
        "particularly nice for SR/MG attackers (Maxwell, SBS) whose "
        "shots can otherwise miss. AOE burst is solid against multiple "
        "enemies."
    ),
)
register_character(_SKILL)
