"""Vesti: Tactical Upgrade — Fire RL B3, true-damage carry.

Encoded from the live ``Character`` skill descriptions. Vesti:TU's
S2 deals true damage on every Full Charge hit, and her burst
amplifies true damage further (60% for 10 sec).

**Source description (S1)**:

    Activates when performing Full Charge attacks, if self is not in
    Missile Guide status. Affects self. Missile Guide: Charge Speed ▲
    100% for 3 round(s). Charge Damage ▲ 58.5% for 3 round(s).
    Activates when reloading to max ammunition. Affects self. Removes
    Missile Guide.

**Source description (S2)**:

    Activates when landing Full Charge attacks. Affects target(s).
    Deals 266.6% of final ATK as true damage.
    Activates when landing Full Charge attacks if self is in Battle
    Formation status. Affects self. ATK ▲ 20% for 3 sec.
    Activates when landing Full Charge attacks if target(s) is in
    Explosive Round status. Affects self. Projectile explosion damage
    ▲ 20% for 3 sec.

**Source description (Burst)**:

    Affects self. Explosion Radius ▲ 100% for 10 sec. True Damage ▲
    60% for 10 sec.
    Affects all enemies (including parts). Deals 492.3% of final ATK
    as Burst Skill true damage.
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
    character_name="Vesti: Tactical Upgrade",
    skill1=(
        SkillEffect(
            description=(
                "Full Charge attack while not in Missile Guide: self "
                "Charge Speed +100% and Charge Damage +58.5% for 3 "
                "rounds."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack while not in Missile Guide",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=3.0,
                    notes="actually 3 rounds, not seconds (DSL gap)",
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=58.5,
                    duration_seconds=3.0,
                    notes="actually 3 rounds, not seconds (DSL gap)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Charge hit: target takes 266.6% of ATK as true "
                "damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=2.666,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Charge hit while in Battle Formation: self ATK "
                "+20% for 3 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack while in Battle Formation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.0,
                    duration_seconds=3.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Explosion Radius +100% (no-op for damage "
                "model) and True Damage +60% for 10 sec; deals 492.3% "
                "of ATK as Burst-Skill true damage to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.923,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire RL B3 — true-damage / DEF-bypass carry. Strong vs Helm/"
        "Centi/Blanc shield comps; the burst's 60% true-damage amp "
        "and 492.3% ATK true-damage payload make her a top counter "
        "to high-DEF defenders."
    ),
)
register_character(_SKILL)
