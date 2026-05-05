"""Laplace — B3 Iron RL Missilis. Hero Vision weapon-change carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Laplace's burst changes her weapon to a 5-second sustained-fire mode
(897% initial + 14.52% DOT) with built-in Pierce; her S1 Hero Vision
stacks build the burst's true-damage bonus.

**Source description (S1)**:

    Activates when attacking with Full Charge. Affects self.
    Hero Vision: Explosion Range up 3.57%, stacks up to 5 times and
    lasts for 5 sec.

**Source description (S2)**:

    Activates when the last bullet hits the target. Affects target.
    Deals 81.66% of final ATK as additional damage.

    Activates when hitting Boss Parts. Affects target.
    Deals 14.78% of final ATK as additional damage.

**Source description (Burst)**:

    Affects Self. Change the weapon in use:
        Initial Damage: 897.6% of final ATK.
        Damage Over Time: 14.52% of final ATK.
        Lasts for 5 sec.
        Additional Effect: Pierce.
        Attention: Unable to take cover when using Burst Skill.

    Affects the same enemy unit(s) when Hero Vision is fully stacked.
    Deals 11.9% of final ATK as true damage.
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
    character_name="Laplace",
    skill1=(
        SkillEffect(
            description=(
                "On full charge: self Hero Vision — Explosion Range "
                "+3.57% (stacks 5x, 5 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.57,
                    duration_seconds=5.0,
                    stacks_max=5,
                    notes=(
                        "actually 'Explosion Range +3.57%' — DSL has "
                        "no AOE_RADIUS kind. BUFF_ATK proxy. "
                        "'Hero Vision' state — gates burst true-damage."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On last bullet: target takes 81.66% of ATK additional "
                "damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.8166,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Boss Parts hit: target takes 14.78% of ATK "
                "additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="hits boss parts",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.1478,
                    notes="boss-parts conditional — PvE concept; near-zero in PvP",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon-change for 5 sec (897.6% initial "
                "+ 14.52% DOT, Pierce); +11.9% true damage on Hero "
                "Vision-fully-stacked targets."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=8.976,
                    notes=(
                        "weapon-change initial damage. DSL has no "
                        "WEAPON_CHANGE / BURST_DURATION kinds; 'no cover' "
                        "drawback also unencoded."
                    ),
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.1452,
                    duration_seconds=5.0,
                    notes="weapon-change DOT 14.52% per sec for 5 sec",
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.119,
                    notes=(
                        "Hero Vision-fully-stacked conditional. DSL "
                        "has no stack-state trigger."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=5.0,
    notes=(
        "Laplace is a unique 5-sec burst-duration carry — her weapon "
        "change drops cover but pumps out 897% + 14.52%/sec sustained "
        "with built-in Pierce. Pairs with full-charge supports "
        "(Crown ATK, Liter charge speed) and Hero Vision is built up "
        "via her own normal-attack rotation."
    ),
)
register_character(_SKILL)
