"""Privaty (Treasure) — Water AR B3, designated-target burst executor.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Full Burst entry: all allies ATK +23.61%, Reload Speed +51.16%,
    Max Ammo -50.66%, Attack Damage +20.16% for 10 sec.

**Source description (S2)**:

    On last-bullet hit: target Damage Taken +10.01% for 10 sec, takes
    256.17% ATK additional damage.
    On last-bullet hit on Designated Target: 1687% ATK additional damage.

**Source description (Burst)**:

    Self: Superior Elemental Code Attack Damage +130% for 10 sec.
    All enemies: 1407.64% ATK Burst-Skill damage. Stuns 3 sec.
    Designated Target: ATK -5.02% for 10 sec.
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
    character_name="Privaty (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst entry: all allies ATK +23.61%, Reload Speed "
                "+51.16%, Attack Damage +20.16% for 10 sec (Max Ammo "
                "-50.66% trade-off)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=23.61,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=51.16,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.16,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On last-bullet hit on Designated Target: target takes "
                "1687% ATK additional damage. Otherwise: 256.17% ATK + "
                "Damage Taken +10.01% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=2.5617,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=16.87,
                    notes="conditional on Designated Target (DSL gap)",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=10.01,
                    duration_seconds=10.0,
                    notes="actually 'Damage Taken +10%' (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Superior Elemental Code Attack Damage +130% "
                "for 10 sec; 1407.64% ATK Burst damage to all enemies "
                "(stun 3 sec); Designated Target ATK -5.02% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=130.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=14.0764,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water AR B3 — Treasure variant of Privaty. Massive burst "
        "payload + team-wide ATK / reload buffs. The designated-target "
        "1687%-ATK additional damage on her S2 last-bullet hit makes "
        "her a dedicated single-target nuker."
    ),
)
register_character(_SKILL)
