"""Neon: Vision Eye — Electric RL B3, Firepower-gauge sustain carry.

Encoded from the live ``Character`` skill descriptions. Neon:VE has a
"Firepower Gauge" state machine that fills via her own attacks and
gates a Super Firepower mode on burst use. Headline effects encoded;
state-machine details flagged inline.

**Source description (S1)**:

    On being attacked while not in Healthy Body: invulnerable + debuff
    immunity for 3 sec each. 5 activations per battle.
    Healthy Body: HP Potency ▲ 10.26% for 20 sec (passive on full charge).

**Source description (S2)**:

    Battle start: Firepower Gauge +100.
    On normal attack while in Firepower Charge: Firepower Gauge +2.
    On Firepower Charge end: Firepower Gauge +N.

**Source description (Burst)**:

    Below 100 gauge: charges Firepower Gauge for 10 sec.
    At 100 gauge: Super Firepower mode (high-tier self-buff package).
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
    character_name="Neon: Vision Eye",
    skill1=(
        SkillEffect(
            description=(
                "On being attacked: self invulnerable for 3 sec + debuff "
                "immunity. Max 5 activations per battle."
            ),
            trigger=Trigger(kind=TriggerKind.ON_DAMAGE_TAKEN),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=3.0,
                    notes="invulnerability (DSL gap); 5 activations / battle",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Healthy Body state: HP Potency +10.26% for 20 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Healthy Body active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=10.26,
                    duration_seconds=20.0,
                    notes="actually 'HP Potency' (heal amplifier; DSL gap)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: Firepower Gauge +100 (kicks self into "
                "Firepower Charge state)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    notes="Firepower Gauge mechanic, not Burst Gauge (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: charges Firepower Gauge for 10 sec; at 100 gauge, "
                "Super Firepower mode (self buff package)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes=(
                        "Super Firepower bundles ATK + Reload + AmmoCap "
                        "+ Crit + Pierce on real character; encoded as "
                        "single ATK buff placeholder (DSL gap)"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric RL B3 — Firepower-Gauge sustain carry. Heavily "
        "state-machine driven; simulator under-credits her until "
        "Firepower Gauge support lands. Niche in PvP."
    ),
)
register_character(_SKILL)
