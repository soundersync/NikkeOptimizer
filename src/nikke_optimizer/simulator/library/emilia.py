"""Emilia — B3 Water RL Abnormal (Re:Zero collab).

Encoded from the live ``Character`` skill descriptions in the DB.
Emilia is the Freezing Witch slow-charge nuker — her burst trades
charge speed (-300%) for a single 1300.53% Charge Damage payout.

**Source description (S1)**:

    Activates when attacking with Full Charge. Affects self.
    Charge Speed ▲ 13.01% for 1 round.
    Charge Damage ▲ 2.01% for every unit in the final Max Ammunition
    Capacity. Lasts for 1 round.

**Source description (S2)**:

    Activates when attacking with Full Charge. Affect target.
    Deals Fixed Damage to the main body equal to 58.99% of the damage
    dealt by self.

    Activates when entering Full Burst. Affects self.
    Max Ammunition Capacity ▲ 3 round(s) for 10 sec.

**Source description (Burst)**:

    Affects self. Explosion Range ▲ 101.24% for 10 sec.
    Freezing Witch Function: Decreases Charge Speed and increases
    Charge Damage for 1 shot.
        Effect 1: Charge Speed ▼ 300%.
        Effect 2: Charge Damage ▲ 1300.53%.
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
    character_name="Emilia",
    skill1=(
        SkillEffect(
            description=(
                "On full charge: self Charge Speed +13.01% and "
                "Charge Damage +2.01% per unit Max Ammo for 1 round."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.01,
                    duration_seconds=2.0,
                    notes="actually '1 round' — DSL gap (rounds vs seconds)",
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.01,
                    duration_seconds=2.0,
                    notes=(
                        "actually '+2.01% per unit Max Ammo' — cross-stat "
                        "scaling. DSL gap; encoded as base value, "
                        "simulator must multiply by ammo count."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On full charge: target takes 58.99% of damage as "
                "fixed damage to main body."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.5899,
                    notes=(
                        "actually 'Fixed Damage to main body equal to "
                        "58.99% of damage dealt' — cross-stat (damage→damage). "
                        "DSL gap; DEAL_TRUE_DAMAGE proxy."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: self Max Ammo +3 for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.0,
                    duration_seconds=10.0,
                    notes="actually '+3 rounds' flat ammo bonus",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Explosion Range +101.24% 10 sec; next "
                "shot Charge Speed -300% but Charge Damage +1300.53%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=101.24,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Explosion Range +101.24%' — DSL has "
                        "no AOE_RADIUS effect kind. BUFF_ATK proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Charge Speed -300% for 1 shot' — "
                        "negative magnitude rejected by DSL invariants. "
                        "0-mag with note flag (must be paired with the "
                        "+1300.53% Charge Damage on the same shot)."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1300.53,
                    duration_seconds=10.0,
                    notes=(
                        "Freezing Witch single-shot bonus — '1 shot' "
                        "duration is encoded as 10 sec. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Emilia is the Freezing Witch nuker — slow charge for one "
        "single 1300.53% Charge Damage payout. Pairs with charge-speed "
        "buffers (Liter, Crown, Naga shield-flagged ATK) and Rem (her "
        "collab partner). Max Ammo bonus extends her burst window."
    ),
)
register_character(_SKILL)
