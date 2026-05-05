"""Crust — B2 Water RL. Maillard/Blanching state-machine team-buffer
+ DEF support.

Encoded from the live ``Character`` skill descriptions in the DB.
Crust toggles between Maillard (post-normal-attack streak) and
Blanching (post-Full-Charge streak) states. Each state grants
cross-stat ATK to all allies (+10% of caster's ATK), and Reliable
Cooking layers cross-stat DEF on top. Burst grants Attack Damage
team-wide + state-conditional Distributed/Sustained damage amps.

**Source description (S1)**:

    Full Charge in Maillard: all allies Maillard duration +2.5s
    Full Charge in Blanching: all allies Blanching duration +2.5s
    After 3 normal hits (no Full Charge): all allies Maillard
      ATK +10% of caster's ATK for 10s; removes Blanching
    After 3 Full Charge hits >1s: all allies Blanching
      ATK +10% of caster's ATK for 10s; removes Maillard

**Source description (S2)**:

    After 3 normal/Full Charge hits: allies w/o Reliable Cooking →
      Reliable Cooking: DEF +10% of caster's DEF for 10s; dispel 1
    On entering Full Burst: targets in Maillard or Blanching →
      ATK +20% of caster's ATK for 10s

**Source description (Burst)**:

    All allies: Attack Damage +20% for 10s
    Allies in Maillard: Distributed Damage +60% for 10s
    Allies in Blanching: Sustained Damage +10% for 10s
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
    character_name="Crust",
    skill1=(
        SkillEffect(
            description="Every 3 normal hits: all allies Maillard ATK +10% caster ATK 10s",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=3),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="Maillard state — replaces Blanching",
                ),
            ),
        ),
        SkillEffect(
            description="Every 3 full-charge hits: all allies Blanching ATK +10% caster ATK 10s",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=3,
                condition="full-charge attacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="Blanching state — replaces Maillard",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Every 3 hits: allies Reliable Cooking — DEF +10% caster DEF 10s + cleanse",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=3),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                ),
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                ),
            ),
        ),
        SkillEffect(
            description="On FB entry: Maillard/Blanching allies ATK +20% caster ATK 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="conditional on Maillard/Blanching status",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: allies +20% Attack Damage + state-conditional amps",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=60.0,
                    duration_seconds=10.0,
                    notes=(
                        "Distributed Damage +60% (Maillard only) — captured "
                        "as pierce-dmg proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    duration_seconds=10.0,
                    notes="Sustained Damage +10% (Blanching only)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water RL B2 supporter. Maillard/Blanching state machine "
        "stacks cross-stat ATK + DEF buffs across the team. Burst "
        "delivers +20% Attack Damage + state-specific amps for "
        "Distributed (Maillard) or Sustained (Blanching) damage."
    ),
)
register_character(_SKILL)
