"""Rei — B1 Water SMG Tetra School Circle. Decoy-based tank/sustainer.

Encoded from the live ``Character`` skill descriptions in the DB.
Rei's core mechanic is a Decoy avatar (created at battle start) that
soaks single-target damage; her S1 charges the team burst gauge on
hit and heals the decoy, and her burst self-Taunts, mitigates damage
taken, and channels regen into the decoy. Niche but useful as a
budget B1 with built-in distraction.

**Source description (S1)**:

    Every 60 normal attacks: all allies, charge Burst Gauge by 2.47%.
    Affects decoy when decoy exists: restore HP equal to 2.1% of
    caster's max HP.

**Source description (S2)**:

    Battle start: self Decoy — creates an Avatar with 96% caster max
    HP for 240 sec.

**Source description (Burst)**:

    Self: Attract 5 sec; Damage Taken -14.4% for 10 sec.
    Decoy (if exists): recover 2.27% of caster max HP per sec for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Rei",
    skill1=(
        SkillEffect(
            description=(
                "Every 60 normal attacks: all allies +2.47% burst gauge; "
                "heal decoy 2.1% caster max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.47,
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.1,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes=(
                        "actually heals the Decoy avatar (a separate "
                        "entity from the caster). DSL has no DECOY "
                        "target kind — proxy to SELF."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self Decoy — avatar with 96% caster max "
                "HP for 240 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=96.0,
                    duration_seconds=240.0,
                    notes=(
                        "Decoy is a tangible avatar that soaks single-"
                        "target damage; approximated as huge shield. "
                        "DSL gap (DECOY entity)."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Attract 5s + Damage Taken -14.4% 10s; "
                "decoy regen 2.27% caster max HP per sec for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=14.4,
                    duration_seconds=10.0,
                    notes="actually Damage Taken -14.4% (DT-reduction proxy)",
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.27,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="actually heals the Decoy, not caster",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SMG B1 — decoy-based tank/sustainer. The decoy soaks "
        "single-target damage like a free taunt; her burst extends "
        "the decoy's lifespan via regen and grants self DT-reduction. "
        "Niche pick but solid as a budget B1 in low-investment teams."
    ),
)
register_character(_SKILL)
