"""Asuka Shikinami Langley: Wille — B3 Wind MG Eva-collab attacker
with Annihilation State machine.

Encoded from the live ``Character`` skill descriptions in the DB.
Asuka:Wille is the Wille-form Eva collab — a state-machine attacker
that toggles into "Annihilation State" via burst, trading normal
attack damage for cross-stat ATK and MG re-fitting. Her S1 stacks
"Anti A.T. Field" Damage Taken on enemies during Annihilation, and
the burst's secondary effect mirrors those stacks for a finisher.

**Source description (S1)**:

    Every 50 normal attacks: target — 471.86% of ATK as additional damage

    Annihilation State only: every 10 shots, 2 enemies nearest crosshair
    take 15.62% damage AND apply Anti A.T. Field — Damage Taken +0.83%
    per stack (max 30, 30 sec)

**Source description (S2)**:

    On entering Full Burst (Annihilation State only): self Attack Damage
    +30.97% for 10 sec
    On using Annihilation: self Emergency Repair —
      MG heating up speed -100% for 3 sec
      Clears 100% of ammo
      Constantly recovers 3.77% of caster's max HP every 1 sec for 3 sec
      Fixes recharge speed +60% for 1 shot

**Source description (Burst)**:

    Self Annihilation State for 9 sec:
      Normal Attack Damage Multiplier -40%
      Reloads 21% of magazine
      ATK +46.8% of caster's ATK for 9 sec
      Attack Damage +36% for 9 sec
    On Annihilation State end: targets afflicted with Anti A.T. Field —
    6.62% of final ATK additional damage. Mirrors stack count. Removes
    Anti A.T. Field.
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
    character_name="Asuka Shikinami Langley: Wille",
    skill1=(
        SkillEffect(
            description="Every 50 normal hits: target 471.86% additional damage",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=50),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=4.7186,
                ),
            ),
        ),
        SkillEffect(
            description="Annihilation State, every 10 shots: 2 nearest 15.62% + Anti A.T. Field stack",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=10,
                condition="Annihilation State active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=0.1562,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=0.83,
                    duration_seconds=30.0,
                    stacks_max=30,
                    notes="Anti A.T. Field: Damage Taken +0.83% per stack",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On FB entry (Annihilation only): self Attack Damage +30.97% 10s",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="Annihilation State active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.97,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description="On Annihilation use: self Emergency Repair (heal + MG cooldown)",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                notes="Emergency Repair fires on burst (which enters Annihilation)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.77,
                    duration_seconds=3.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.0,
                    duration_seconds=3.0,
                    notes="Recharge speed +60% for 1 shot — duration approximated",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: self enters Annihilation State 9s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=46.8,
                    duration_seconds=9.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=36.0,
                    duration_seconds=9.0,
                ),
                # Normal-attack -40% multiplier — DSL has no "ATTACK_DMG_NEGATIVE"
                # variant; captured as note. Trade-off vs the above buffs.
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=9.0,
                    notes=(
                        "Annihilation also imposes Normal Attack Damage "
                        "Multiplier -40% for 9s — DSL gap (negative buff "
                        "channel)."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description="On Annihilation end: A.T. Field targets 6.62% × stacks",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Annihilation State ends",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0662,
                    notes=(
                        "6.62% × Anti A.T. Field stack count, then removes "
                        "the debuff. Up to 30 stacks → ~198% effective."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind MG B3 Eva collab. State-machine attacker — burst toggles "
        "Annihilation State (cross-stat ATK +46.8% + Attack Damage +36% "
        "for 9s, but normal-damage -40%). Stacks Anti A.T. Field DEF "
        "debuff during Annihilation and detonates on state exit."
    ),
)
register_character(_SKILL)
