"""Frima (Treasure) — Iron SR B1, Wake-Up true-damage support.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    On Full Charge hit: target Sleepy — DEF -4%, max 5 stacks, 10 sec.
    On Sleepy fully stacked (after 6 hits): self Wake Up — normal
    attacks deal true damage for 10 sec.

**Source description (S2)**:

    On Full Charge attack: all allies Max HP +6.09% for 5 sec.
    In Wake Up: all allies True Damage +28.16% for 5 sec.

**Source description (Burst)**:

    10 highest-DEF enemies: 101.66% ATK damage, DEF -9.86% for 10 sec.
    All allies: Max HP +30.26% for 4 sec.
    In Wake Up: all allies True Damage +49.97% for 10 sec.
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
    character_name="Frima (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "On Full Charge hit: target Sleepy — DEF -4%, max 5 "
                "stacks, 10 sec each."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=4.0,
                    duration_seconds=10.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge attack: all allies Max HP +6.09% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=6.09,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Charge while in Wake Up: all allies True Damage "
                "+28.16% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Wake Up + Full Charge",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=28.16,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 10 highest-DEF enemies take 101.66% ATK damage "
                "+ DEF -9.86% for 10 sec; all allies Max HP +30.26% for "
                "4 sec; in Wake Up: all allies True Damage +49.97% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.0166,
                    notes="actually 10 highest-DEF enemies",
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.26,
                    duration_seconds=4.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=49.97,
                    duration_seconds=10.0,
                    notes="conditional on Wake Up state (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SR B1 (Treasure) — Wake-Up true-damage support. Strong "
        "anti-shield / anti-stall pick once Wake Up is active."
    ),
)
register_character(_SKILL)
