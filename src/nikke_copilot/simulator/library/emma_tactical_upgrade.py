"""Emma: Tactical Upgrade — B1 Fire MG. True-damage team buffer +
auto-Taunter.

Encoded from the live ``Character`` skill descriptions in the DB.
E:TU's identity is the Environment Setup field that boosts Damage
Taken on enemies + heal-over-time on allies, the auto-Taunt on enemy
appearance, and her Burst's cross-stat ATK + Environment Setup
enhancement. Strong in mixed Fire team comps — Damage Taken and
True Damage buffs scale with all attackers.

**Source description (S1)**:

    On battle start: Environment Setup — all enemies Damage Taken
    +3.9% for 10s; all allies recover 2.32% caster max HP / 1s for 10s
    Recurring 30s
    On enemy appears: self Exposure (undispellable) — Taunt all enemies

**Source description (S2)**:

    LT Formation (passive, while alive):
      Same-squad allies: Crit Damage +23.51% (continuous)
      All allies: Projectile Explosion Damage +2.32% (continuous)
    Self in AS Formation:
      All allies: True Damage +30.97% (continuous)
      All allies: Projectile Explosion Damage +3.09% (continuous)
      Self: Exposure activation disabled
      Self: Environment Setup recurring interval -20s

**Source description (Burst)**:

    All allies: ATK +40.07% of caster's ATK for 10s
    Self in Environment Setup: Enhances Environment Setup
      Damage Taken multiplier ×100% (enemies)
      HP restored potency +29.04% (allies)
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
    character_name="Emma: Tactical Upgrade",
    skill1=(
        SkillEffect(
            description="At battle start: Environment Setup — enemies +3.9% DT, allies HP regen 10s",
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.9,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.32,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
        SkillEffect(
            description="On enemy appears: self Taunt all enemies (Exposure)",
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                notes="Exposure — undispellable, persists",
            ),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    duration_seconds=999.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="LT Formation: allies Crit Damage +23.51% + Explosion Damage +2.32% (continuous)",
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=23.51,
                    duration_seconds=999.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.32,
                    duration_seconds=999.0,
                    notes="Projectile Explosion Damage — captured as parts-dmg proxy",
                ),
            ),
        ),
        SkillEffect(
            description="AS Formation (self): allies True Damage +30.97% (continuous)",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self in AS Formation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.97,
                    duration_seconds=999.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.09,
                    duration_seconds=999.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: allies ATK +40.07% of caster ATK 10s + Environment Setup boost",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.07,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=7.8,
                    duration_seconds=10.0,
                    notes=(
                        "Environment Setup ×100% multiplier — Damage Taken "
                        "doubles (3.9% → 7.8%). 10s duration."
                    ),
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.99,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="HP restored potency +29.04% — boost on existing regen",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire MG B1 supporter — True Damage buff + Environment Setup "
        "Damage Taken field + auto-Taunt. Strong in Fire-only comps "
        "thanks to LT Formation crit-damage buff being squad-only."
    ),
)
register_character(_SKILL)
