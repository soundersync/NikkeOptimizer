"""Trony — B3 Fire SR Missilis. T.Rony Bomber accumulator.

Encoded from the live ``Character`` skill descriptions in the DB.
Trony's signature is the Cumulative Damage Skill (T.Rony Bomber): she
attaches a meta-debuff to a target that accumulates 50% of damage
dealt and detonates as AOE distributed damage at cap (1536% of ATK).

**Source description (S1)**:

    Activates when hitting the target with Full Charge. Affects the
    target if there are no enemies in T.Rony Bomber status.
    Cumulative Damage Skill for 5 sec.
    Function: Accumulates part of damage inflicted by the caster.
    Upon reaching the maximum accumulated damage, deal damage to
    enemies before ending.
        Effect 1: Maximum Accumulated Damage is 1536% of caster's final ATK.
        Effect 2: Accumulates 50% of damage dealt by self.
        Effect 3: Deals distributed damage to all nearby enemies upon
                  reaching the maximum accumulated damage.

**Source description (S2)**:

    Activates when attacking with Full Charge for 5 time(s). Affects self.
    Distributed Damage ▲ 51.84% for 10 sec.

    Activates when hitting the target with Full Charge for 5 time(s).
    Affects the target. DEF ▼ 9.59% for 10 sec.

**Source description (Burst)**:

    Affects Self. ATK ▲ 101.37% for 10 sec.
    Accumulated damage ratio of the Cumulative Damage Skill ▲ 62.83% for 10 sec.
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
    character_name="Trony",
    skill1=(
        SkillEffect(
            description=(
                "On Full Charge hit (no T.Rony Bomber active): apply "
                "Cumulative Damage Skill — accumulates 50% of damage "
                "dealt for 5 sec, detonates at 1536% cap."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge hit + no T.Rony Bomber active",
            ),
            effects=(
                # The detonation payload at cap.
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=15.36,
                    notes=(
                        "T.Rony Bomber: accumulates 50% of damage; "
                        "detonates at 1536% cap. 5-sec window. DSL gap "
                        "(DAMAGE_ACCUMULATOR)."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 5 Full Charges: self Distributed Damage +51.84% "
                "for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="5th full-charge attack landed",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=51.84,
                    duration_seconds=10.0,
                    notes="actually Distributed Damage; ATK proxy",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 5 Full Charges: target DEF -9.59% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="5th full-charge attack landed",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=9.59,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self ATK +101.37% for 10 sec; Cumulative Damage "
                "Skill accumulates +62.83% more (boosts T.Rony Bomber "
                "payload)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=101.37,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "Accumulated damage ratio +62.83% — boosts "
                        "T.Rony Bomber capture. DSL gap "
                        "(ACCUMULATOR_RATIO)."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Trony's T.Rony Bomber turns sustained DPS into AOE bursts via "
        "the Cumulative Damage Skill. Pairs well with high-DPS attackers "
        "(Modernia, SBS) that feed her accumulator quickly."
    ),
)
register_character(_SKILL)
