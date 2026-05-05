"""Scarlet: Black Shadow — B3 Wind RL hyper-DPS, Pilgrim. The 'SBS comp' anchor.

Encoded from the live ``Character`` skill descriptions in the DB. SBS's
identity is the escalating S1 — every 3 full-charge attacks unlock a
bigger payload (250% → 500% → 750%), and her burst lowers the count
required so all three tiers can fire within a single Full Burst window.

**Source description (S1)**:

    Activates when attacking with Full charge. Effect changes according
    to the number of attack time(s). Effect of each phase does not stack.
        Three times: Affects 1 enemy unit(s) with the lowest DEF.
            Deals 250.47% of final ATK as additional damage.
        Six times:   Affects enemies within attack range.
            Deals 500% of final ATK as distributed damage.
        Nine times:  Affects all enemies.
            Deals 750.47% of final ATK as distributed damage.

**Source description (S2)**:

    Activates when entering Full burst. Affects Self.
    Max ammo Capacity increased by 60% for 10 seconds.
    Reload 100% of magazine.

**Source description (Burst)**:

    Affects self. Changes Full charge attack count required for Skill 1
    to 1 time/2 times/3 times for 10 seconds.
    ATK ▲ 115.12% for 10 sec.
    Charge damage ▲ 150.12% for 10 sec.

**DSL gaps**:

  * "Changes attack count required" mutates a counter mid-rotation —
    no DSL kind for this. Encoded as a note on the burst.
  * "Effect of each phase does not stack" is exclusive-OR semantics
    that the DSL can't model directly; encoded as 3 separate
    SkillEffects with conditional triggers.
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
    character_name="Scarlet: Black Shadow",
    skill1=(
        SkillEffect(
            description=(
                "Every 3 Full Charges: deals 250.47% of ATK to lowest-DEF enemy."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="3rd full-charge attack landed (S1 phase 1)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP),
                    magnitude=2.5047,
                    notes=(
                        "actually 'lowest DEF enemy'; ENEMY_LOWEST_HP "
                        "is a near-equivalent in PvP (low DEF ≈ squishy)"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 6 Full Charges: deals 500% of ATK distributed "
                "across enemies in range."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="6th full-charge attack landed (S1 phase 2)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 9 Full Charges: deals 750.47% of ATK distributed "
                "across all enemies (the big payload)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="9th full-charge attack landed (S1 phase 3)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=7.5047,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry: self ammo +60% for 10 sec, plus "
                "magazine 100% reload."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=1.0,
                    notes=(
                        "actually instant 'reload 100% of magazine' — "
                        "encoded as instant-reload-speed proxy"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: changes S1 attack-count requirements from "
                "3/6/9 to 1/2/3 for 10 sec. Self ATK +115.12% and "
                "Charge Damage +150.12% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=115.12,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=150.12,
                    duration_seconds=10.0,
                ),
                # Attack-count mutation — no DSL kind.
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "S1 attack-count requirements drop to 1/2/3 "
                        "(from 3/6/9) for 10 sec — DSL has no "
                        "MUTATE_TRIGGER_COUNTER kind. The simulator "
                        "must reset SBS's S1 counter and reduce its "
                        "thresholds while burst is active."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "SBS's burst window is THE moment all three S1 phases fire — "
        "with the 1/2/3 attack count, 3 full charges trigger phases 1, "
        "2, AND 3 (250% + 500% + 750% = 1500% of ATK in burst payload). "
        "Pair with Naga (whose burst gives +47% ATK on shield apply) "
        "and Crown (universal shield) for the canonical SBS comp."
    ),
)
register_character(_SKILL)
