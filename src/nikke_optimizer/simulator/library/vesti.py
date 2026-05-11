"""Vesti (base) — Water RL B3, Survival-Instinct stacking carry.

Encoded from the live ``Character`` skill descriptions in the DB. Base
Vesti precedes her Tactical Upgrade form: her identity is the Survival
Instinct state machine, which advances each burst use (SI1 → SI2 →
SI3) and stacks ATK / Crit Damage / Crit Rate buffs that persist for
45 sec. Her burst payload also scales with the SI phase.

**Source description (S1)**:

    ■ Activates when hitting a target with Full Charge. Affects self.
    Explosion Range ▲ 15.01% for 10 sec.

**Source description (S2)**:

    ■ Activates when using Burst Skill. Affects self. Survival
    Instinct 1: ATK ▲ 5.35% for 45 sec.
    ■ Activates when using Burst Skill during Survival Instinct 1.
    Affects self. Survival Instinct 2: Critical Damage ▲ 22.34% for
    45 sec. Previous effects trigger repeatedly.
    ■ Activates when using Burst Skill during Survival Instinct 2.
    Affects self. Survival Instinct 3: Critical Rate ▲ 15.51% for
    45 sec. Previous effects trigger repeatedly.

**Source description (Burst)**:

    ■ Affects self. Takes out two Missile Containers, dealing 15.56%
    of final ATK as damage to the enemy with the lowest HP every 1
    sec for 18 sec.
    ■ Affects all enemies. Effect changes according to the Survival
    Instinct's phase. Previous effects trigger repeatedly:
        Survival Instinct 1: Deals 210.62% of final ATK as damage.
        Survival Instinct 2: Deals 247.25% of final ATK as damage.
        Survival Instinct 3: Deals 302.19% of final ATK as damage.
    ■ Affects all allies. Full Burst Time ▼ 5 sec.
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
    character_name="Vesti",
    skill1=(
        SkillEffect(
            description=(
                "On Full Charge hit: self Explosion Range +15.01% for "
                "10 sec (cosmetic / AOE radius — no damage proxy)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Explosion Range +15.01%' — AOE radius "
                        "expansion, not damage; encoded as 0-magnitude "
                        "BUFF_CHARGE_DAMAGE placeholder"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On burst use: enter Survival Instinct 1 — self ATK "
                "+5.35% for 45 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="first burst use (SI0 → SI1)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=5.35,
                    duration_seconds=45.0,
                    notes="Survival Instinct 1; persists 45 sec",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use during SI1: enter Survival Instinct 2 — "
                "self Crit Damage +22.34% for 45 sec. SI1 still active."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="burst use during SI1 (SI1 → SI2)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=22.34,
                    duration_seconds=45.0,
                    notes="Survival Instinct 2; SI1 ATK +5.35% remains",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use during SI2: enter Survival Instinct 3 — "
                "self Crit Rate +15.51% for 45 sec. SI1 + SI2 active."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="burst use during SI2 (SI2 → SI3)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.51,
                    duration_seconds=45.0,
                    notes=(
                        "Survival Instinct 3; SI1 (ATK) + SI2 (Crit "
                        "Damage) both still active"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 2 Missile Containers deal 15.56% of ATK to "
                "lowest-HP enemy every sec for 18 sec; AOE damage "
                "scales with SI phase (210/247/302%); all allies Full "
                "Burst Time -5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP),
                    magnitude=0.1556,
                    notes=(
                        "Missile Containers: 15.56% of ATK every 1 sec "
                        "for 18 sec; DSL has no DOT-style sustained "
                        "damage — encoded as single instance"
                    ),
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.0219,
                    notes=(
                        "SI-phase scaling: 210.62% / 247.25% / 302.19% "
                        "at SI1 / SI2 / SI3; encoded at SI3 max value"
                    ),
                ),
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.0,
                    notes=(
                        "actually 'Full Burst Time -5 sec'; shortens "
                        "Full Burst window, encoded as cooldown proxy"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water RL B3 — Survival Instinct stacker. Buffs persist across "
        "bursts (ATK, Crit Damage, Crit Rate stack into 45-sec windows). "
        "Outdated by her Tactical Upgrade form for high-end PvP but "
        "still a viable counter to Iron-element teams."
    ),
)
register_character(_SKILL)
