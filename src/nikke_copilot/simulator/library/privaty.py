"""Privaty — B3 Water AR Elysion. Last-bullet stun-amplifier.

Encoded from the live ``Character`` skill descriptions in the DB.
Privaty's signature is the stunned-target damage bonus on S2 — when
her own burst stuns enemies, her last-bullet payload spikes from
85.79% to 1089% of ATK.

**Source description (S1)**:

    Affects all allies. Cast when entering Full Burst.
    ATK ▲ 23.61% for 10 sec.
    Reloading Speed ▲ 51.16% for 10 sec.
    Max Ammunition Capacity ▼ 50.66% for 10 sec.

**Source description (S2)**:

    Activates when the last bullet hits the target. Affects the target.
    Deals 85.79% of final ATK as Additional Damage.

    Affects the enemy hit by the last round of ammunition if they are Stunned.
    Deals 1089% of final ATK as Additional Damage.

**Source description (Burst)**:

    Affects all enemies. Deals 457.87% of final ATK as damage. Stuns for 3 sec.
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
    character_name="Privaty",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies ATK +23.61%, Reload "
                "+51.16%, but Max Ammo -50.66% for 10 sec."
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
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Max Ammo -50.66%' — debuff. The "
                        "smaller mag + faster reload means more "
                        "last-bullet triggers for S2."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On last bullet: target takes 85.79% of ATK additional "
                "damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.8579,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On last bullet vs a Stunned target: 1089% of ATK extra "
                "damage (massive amplification)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_LAST_AMMO,
                condition="target is Stunned",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=10.89,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all enemies take 457.87% of ATK damage and are "
                "Stunned for 3 sec — the stun feeds her S2's massive "
                "1089% bonus."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.5787,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=3.0,
                    notes=(
                        "actually 'Stun for 3 sec' — DSL has no STUN "
                        "effect kind. Captured as 0-mag DEBUFF_DEFENSE "
                        "with the duration set as a placeholder."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Privaty's identity is the burst → stun → last-bullet amplifier "
        "loop: her burst stuns all enemies, then her S2 last-bullet "
        "fires 1089% damage on each stunned enemy. Pairs especially "
        "well with reload-speed buffers (Liter S1, Volume S2) that "
        "accelerate her last-bullet cadence."
    ),
)
register_character(_SKILL)
