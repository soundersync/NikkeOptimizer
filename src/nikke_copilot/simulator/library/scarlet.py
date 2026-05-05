"""Scarlet — B3 Electric AR Pilgrim. Self-stacking AOE burst nuker.

Encoded from the live ``Character`` skill descriptions in the DB. Base
Scarlet (distinct from SBS) — a low-HP self-buff carry whose burst
nukes all enemies. ATK self-stacks while taking small HP losses, and
crit conditionals fire when she dips below 60%/50% HP.

**Source description (S1)**:

    Activates after landing 10 normal attack(s). Affects self.
    ATK ▲ 23.15%, stacks up to 5 times and lasts for 5 sec.
    Current HP ▼ 4.01%

**Source description (S2)**:

    Affects the attacker. 30% chance of casting when attacked.
    [Target] Deals 138.24% of final ATK as damage.

    Affects self. Cast when HP falls below 60%.
    Critical Damage ▲ 6.61% continuously.

**Source description (Burst)**:

    Affects self. Cast when HP falls below 50%.
    Critical Rate ▲ 19.57% for 10 sec.

    Affects all enemies. Deals 849.15% of final ATK as damage.
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
    character_name="Scarlet",
    skill1=(
        SkillEffect(
            description=(
                "Every 10 normal attacks: self ATK +23.15% (stacks "
                "5x, 5 sec) and HP -4.01%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=23.15,
                    duration_seconds=5.0,
                    stacks_max=5,
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    notes=(
                        "actually 'Current HP -4.01%' — DSL has no "
                        "self-damage effect kind. 0-mag HEAL_HP_FLAT "
                        "with note flag (gates her S2/burst HP-low "
                        "conditionals)."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "30% chance on damage taken: attacker takes 138.24% "
                "of ATK damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="30% chance",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.3824,
                    notes="actually 'the attacker' — DSL has no ATTACKER target",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When HP < 60%: self Crit Damage +6.61% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self HP < 60%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.61,
                    duration_seconds=999.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all enemies take 849.15% of ATK; if HP < 50%, "
                "self Crit Rate +19.57% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=8.4915,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=19.57,
                    duration_seconds=10.0,
                    notes="HP < 50% conditional — DSL gap (encoded unconditionally)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Base Scarlet is the original Pilgrim AOE nuker — self-stacks "
        "ATK on attack cadence, scales harder when HP dips below 60% "
        "and 50% (rewarding aggressive play). Distinct from SBS, "
        "which is the dragon-comp Full-Charge phase carry."
    ),
)
register_character(_SKILL)
