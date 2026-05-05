"""Grave — Fire AR B2, multi-stage Overheat / Pierce carry.

Encoded from the live ``Character`` skill descriptions. Grave's S2
has a 3-stage state machine ("Overheat I/II/III") that progresses on
every 30 / 60 normal attack hits during her Prediction-mode burst.
We encode the headline effects per stage with notes flagging the
state-machine gap.

**Source description (S1)**:

    Activates when Prediction status ends. Affects self. Removes 100%
    of bullets. Heat Emission: Reload Ratio ▼ 50%. Removes Heat
    Emission under certain conditions.
    Activates only when in Heat Emission status. Affects self.
    Recovers 2% of final Max HP every 1 sec continuously.
    Activates only when in Heat Emission status. Affects all allies.
    Burst Gauge filling speed ▲ 38.96% continuously. Pierce Damage ▲
    48.4% continuously.

**Source description (S2)**:

    Activates after landing 15 normal attack(s). Affects self.
    Overheat 1: ATK ▲ 15.48%. Removed upon reloading to max ammunition.
    Activates when normal attack hits after Prediction status takes
    effect. Affects self. Changes according to the number of hits.
    30 times (in Prediction + Overheat I): Overheat II ATK ▲ 20.66%
    continuously.
    60 times (in Prediction + Overheat II): Overheat III Attack
    Damage ▲ 30.8% continuously.

**Source description (Burst)**:

    Affects self. Prediction: Current HP ▼ 1% every 1 sec, lasts for
    10 sec. Grants unlimited ammunition for 10 sec. Gains Pierce for
    10 sec. Pierce Damage ▲ 52.8% for 10 sec. Critical Rate ▲ 85.19%
    for 10 sec.
    Affects all allies. Attack Damage ▲ 48.2% for 10 sec. Pierce
    Damage ▲ 39.98% for 10 sec. Max Ammunition Capacity ▲ 3 rounds
    for 10 sec.
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
    character_name="Grave",
    skill1=(
        SkillEffect(
            description=(
                "While in Heat Emission status: self regen 2% of Max HP "
                "per second."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Heat Emission status active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.0,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While in Heat Emission status: all allies Burst Gauge "
                "fill +38.96% and Pierce Damage +48.4% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Heat Emission status active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=38.96,
                    notes="actually 'gauge fill speed +38.96%' (continuous)",
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=48.4,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 15 normal attacks: self enters Overheat I, "
                "ATK +15.48%. Removed on reload to max."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=15),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.48,
                    duration_seconds=86400.0,
                    notes="state: removed on full reload (DSL gap)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "30 hits in Prediction+Overheat I: Overheat II — "
                "self ATK +20.66% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Prediction + Overheat I + 30 hits → Overheat II",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.66,
                    duration_seconds=86400.0,
                    notes="staged: requires Prediction + Overheat I (DSL gap)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "60 hits in Prediction+Overheat II: Overheat III — "
                "self Attack Damage +30.8% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Prediction + Overheat II + 60 hits → Overheat III",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.8,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst — Prediction: self HP -1%/sec, unlimited ammo, "
                "Pierce, Pierce Damage +52.8%, Crit Rate +85.19% for "
                "10 sec. All allies: Attack Damage +48.2%, Pierce "
                "Damage +39.98%, Max Ammo +3 rounds for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=52.8,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=85.19,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=48.2,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=39.98,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire AR B2 — pierce-damage support / multi-stage carry. The "
        "Overheat I/II/III progression is encoded as separate "
        "conditional triggers; the simulator under-credits her until "
        "state-machine support lands. Heat-Emission gauge-fill makes "
        "her a viable B2 alternative for non-Crown comps."
    ),
)
register_character(_SKILL)
