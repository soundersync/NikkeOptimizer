"""Snow White: Innocent Days — Iron AR B3, Pilgrim attacker.

Encoded from the live ``Character`` skill descriptions in the DB.
SW:ID is a hit-count-based AR carry — every 30 normal attacks stacks
max-ammo and triggers AOE; her burst removes the hit-count requirement,
boosts ATK +97.2%, and grants unlimited ammo for the Full Burst window.

**Source description (S1)**:

    ■ Activates after landing 30 normal attack(s). Affects self. Max
    ammunition capacity ▲ 25.66%, stacks up to 5 time(s) and last for
    5 sec.
    ■ Activates after landing 30 normal attack(s). Affects enemies
    within attack range. Deals 188.68% of final ATK as damage.

**Source description (S2)**:

    ■ Activates after landing 50 normal attack(s). Affects all
    enemies. Deals 61.69% of final ATK as damage.
    ■ Activates when using Burst Skill. Affects self. Attack damage ▲
    21.12% for 10 sec.

**Source description (Burst)**:

    ■ Affects self. Hit count required for Skill 2 ▼ 20 time(s) for 10
    sec. ATK ▲ 97.2% for 10 sec. Grants unlimited ammunition for 10
    sec.
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
    character_name="Snow White: Innocent Days",
    skill1=(
        SkillEffect(
            description=(
                "Every 30 normal-attack hits: self Max Ammo +25.66% "
                "(stacks 5x, 5 sec) and AOE deals 188.68% of ATK."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=30),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.66,
                    duration_seconds=5.0,
                    stacks_max=5,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.8868,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 50 normal-attack hits: all enemies take 61.69% "
                "of ATK as AOE damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=50,
                notes="hit threshold drops to 30 during burst (S2 hit req ▼20)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.6169,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use: self Attack Damage +21.12% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.12,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self ATK +97.2%, unlimited ammo, and S2 hit "
                "requirement -20 (so AOE fires every 30 hits) for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=97.2,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=999.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'unlimited ammunition' — encoded as "
                        "absurdly large ammo buff; simulator should "
                        "recognize as no-reload mode"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes=(
                        "S2 hit-count requirement ▼20 — encoded as "
                        "reload speed proxy; simulator should re-trigger "
                        "S2 every 30 hits during burst"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron AR B3 Pilgrim — hit-count-stacking carry. Best paired "
        "with Liter (burst gen) and Crown / Blanc (ATK / damage buffs). "
        "Burst window is the damage spike — unlimited ammo + ATK +97.2%."
    ),
)
register_character(_SKILL)
