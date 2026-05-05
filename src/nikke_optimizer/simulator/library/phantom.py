"""Phantom — B3 Water AR Elysion. Calling Card / Thief's Dagger DPS.

Encoded from the live ``Character`` skill descriptions in the DB.
Phantom's loop: hit a target → apply Calling Card debuff + stack
Thief's Dagger Hit Rate; at 3 stacks → bonus damage on the marked
target + ramp self Distributed Damage. Niche but high-output.

**Source description (S1)**:

    Activates when hitting a Rapture with a normal attack if the
    Rapture is not in Calling Card status. Affects the target.
    Calling Card: DEF ▼ 32.19% for 5 sec.

    Activates when hitting a Rapture with a normal attack if the
    Rapture is not in Calling Card status. Affects self.
    Thief's Dagger: Hit Rate ▲ 25.75%, stacks up to 3 time(s)
    and lasts for 5 sec.

    Activates when hitting a target with a normal attack if the target
    is in Calling Card status. Affects self.
    Attack damage ▲ 75.17% for 1 round(s).

**Source description (S2)**:

    Activates when Thief's Dagger is fully stacked. Affects target(s)
    in Calling Card status after stacks are removed.
    Deals 84.33% of final ATK as additional damage.
    Calling Card status is removed after the effect is triggered.

    Activates when Thief's Dagger is fully stacked. Affects self after
    stacks are removed.
    Distributed Damage ▲ 12.86% continuously, stacks up to 3 time(s).
    Stacks are removed after Burst Skill is cast.

    Activates after landing 10 normal attack(s). Affects self.
    ATK ▲ 85.12% for 5 sec. Distributed Damage ▲ 31.92% for 10 sec.

**Source description (Burst)**:

    Affects all enemies. Deals 1457.28% of final ATK as Distributed Damage.
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
    character_name="Phantom",
    skill1=(
        SkillEffect(
            description=(
                "Hitting an unmarked target: applies Calling Card "
                "(target DEF -32.19% for 5 sec) + stacks Thief's Dagger "
                "Hit Rate +25.75% on self (max 3, 5 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="hit a target NOT in Calling Card status",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=32.19,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.75,
                    duration_seconds=5.0,
                    stacks_max=3,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Hitting a Calling Card target: self Attack Damage "
                "+75.17% for 1 round."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="target IS in Calling Card status",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=75.17,
                    duration_seconds=1.0,
                    notes="actually 'for 1 round', not 1 sec",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Thief's Dagger fully stacked → Calling Card target takes "
                "84.33% of ATK + self Distributed Damage +12.86% (×3 stacks)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Thief's Dagger at 3 stacks (max)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.8433,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.86,
                    duration_seconds=86400.0,
                    stacks_max=3,
                    notes="Distributed Damage; cleared on burst use",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 10 normal attacks: self ATK +85.12% (5s) + "
                "Distributed Damage +31.92% (10s)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=85.12,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=31.92,
                    duration_seconds=10.0,
                    notes="actually Distributed Damage; ATK proxy",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 1457.28% of ATK Distributed Damage to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=14.5728,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Phantom's Calling Card → Thief's Dagger loop turns sustained "
        "fire into massive ATK + Distributed Damage stacks. Niche but "
        "potent in PvP attack comps with reload-speed support."
    ),
)
register_character(_SKILL)
