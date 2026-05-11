"""Guilty — B2 Wind SG Missilis Real Kindness. ATK-mirror self-buff carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Guilty is a self-buffing Wind SG whose signature is duplicating the
team's highest-ATK ally as a stacking self-buff, supporting Wind
allies via buff-stack +1, and bursting a high-DEF target with a
DEF-reduction follow-up at max stacks.

**Source description (S1)**:

    Every 6 normal attacks: self Mind If I Borrow This? — Duplicate
    8.81% ATK of ally with the highest ATK, stacks ×5, 10 sec.

**Source description (S2)**:

    Every 12 normal attacks: all Wind type allies, stack count of
    buffs ▲ 1. ATK ▲ 4.13% for 10 sec.

**Source description (Burst)**:

    Affects 1 enemy with the highest DEF. Deals 284.32% ATK.
    Same target if Mind If I Borrow This? fully stacked: DEF -20.25%
    for 5 sec. Deals 277.71% of final ATK as additional damage.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Guilty",
    skill1=(
        SkillEffect(
            description=(
                "Every 6 normal attacks: self ATK +8.81% of highest-"
                "ATK ally's ATK (stacks ×5, 10 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=6),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=8.81,
                    duration_seconds=10.0,
                    stacks_max=5,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "Mind If I Borrow This? — scales off the team's "
                        "highest-ATK ally's ATK, not caster's own. DSL "
                        "lacks ALLY_HIGHEST_ATK as a scaling source — "
                        "encoded as caster's ATK proxy."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 12 normal attacks: Wind allies buff stack +1 + "
                "ATK +4.13% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=12),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WIND,
                    ),
                    magnitude=4.13,
                    duration_seconds=10.0,
                    notes="stack count of buffs +1 (meta-buff, DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: highest-DEF enemy takes 284.32% ATK; if Mind "
                "If I Borrow This? fully stacked, also DEF -20.25% 5s "
                "and +277.71% additional damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=2.8432,
                    notes="highest-DEF enemy (DSL has no HIGHEST_DEF target)",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=20.25,
                    duration_seconds=5.0,
                    notes="conditional on Mind If I Borrow This? 5/5 stacks",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=2.7771,
                    notes="conditional follow-up at full stacks",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SG B2 — single-target self-buff finisher. Mind If I "
        "Borrow This? mirrors the team's highest-ATK ally as self-"
        "buff, paying off heavily when teamed with a Wind hyper-DPS. "
        "Burst is high-DEF anti-tank with conditional DEF shred."
    ),
)
register_character(_SKILL)
