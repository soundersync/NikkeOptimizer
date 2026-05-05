"""Nayuta — B2 Wind SMG Pilgrim. Memory Absorption stacker + weapon-change carry.

Encoded from the live ``Character`` skill descriptions in the DB. Nayuta
is one of the most complex skill sets in the game: battle-start
indomitability, Memory Absorption stacking buffs (3 cumulative tiers
on Hit Rate / ATK / Core damage), and a Memory Incineration weapon-change
burst (1.8 sec charge time, 275% / 250% per shot, unlimited ammo for 10 sec).

**Source description (S1)**:

    Activates at the start of battle. Affects self.
    Unchanging Heart: Gain Indomitability for 9 sec. 1x/battle.

    Activates when Memory Absorption takes effect. Affects all allies.
    Damage dealt when attacking core ▲ 25.15% for 5 sec.
    ATK ▲ 30.16% of caster's ATK for 5 sec.
    Equally shares HP recovery for 5 sec.

    Activates when Memory Absorption takes effect. Affects self.
    Recovers 25% of final max HP as HP.

    Activates when attacking with Full Charge.
    Affects all enemies if self is in Memory Incineration status.
    Deals 150% of final ATK as damage.

    Activates when the enemy is the stage target. Affects the same enemy.
    Deals 380.46% of final ATK as additional damage.

**Source description (S2)**:

    Activates every 3 sec. Affects self.
    Memory Absorption: Hit rate ▲ 1.4%, stacks up to 30 times and
    immune to stack count effects continuously. Undispellable.

    Activates when Memory Absorption takes effect. Affects self.
    Additional effects triggered according to stack count:
        Stage 1 (>2 stacks):  ATK ▲ 15.2% continuously.
        Stage 2 (>10 stacks): Attack damage ▲ 20.27% continuously.
        Stage 3 (>30 stacks): Core damage ▲ 21.05% continuously.

**Source description (Burst)**:

    Affects all allies. Attack damage ▲ 35.45% for 15 sec.

    Affects all enemies. Deals 645.33% of final ATK as Burst Skill damage.

    Affects self. Memory Incineration: Changes the weapon in use.
    Charge time: Fixed at 1.8 sec.
    Damage: 275.18% of final ATK.
    Full Charge damage: 250% of damage.
    Duration: 10 sec.
    Bonus: Unlimited ammunition for 10 sec.
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
    character_name="Nayuta",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: self Unchanging Heart — indomitability "
                "9 sec. 1x/battle."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                notes="1x per battle — DSL gap (no per-battle cap)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=9.0,
                    notes=(
                        "actually 'indomitability' — DSL has no "
                        "INDOMITABILITY kind. 0-mag BUFF_DEFENSE "
                        "with note flag."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Memory Absorption: all allies Core Damage +25.15%, "
                "ATK +30.16% of caster's ATK, share HP recovery 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Memory Absorption stack gained",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CORE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=25.15,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.16,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=5.0,
                    notes=(
                        "actually 'share HP recovery' — DSL has no "
                        "SHARE_HP_RECOVERY kind. 0-mag with note flag."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Memory Absorption: self heals 25% of Max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Memory Absorption stack gained",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On full charge in Memory Incineration: all enemies "
                "take 150% of ATK damage; +380.46% on stage target."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge in Memory Incineration",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.5,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=3.8046,
                    notes="'stage target' conditional — DSL gap (PvE concept)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 3 sec: self Memory Absorption — Hit Rate +1.4% "
                "(stacks 30x, undispellable, immune to stack effects)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=3.0,
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.4,
                    duration_seconds=999.0,
                    stacks_max=30,
                    notes=(
                        "'Memory Absorption' state — gates the 3 "
                        "cumulative tiers below."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Cumulative on Memory Absorption (3rd-tier): self ATK "
                "+15.2%, Attack Damage +20.27%, Core Damage +21.05% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Memory Absorption >30 stacks",
                notes="cumulative — encodes 3rd-tier value",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.2,
                    duration_seconds=999.0,
                    notes="tier 1 (>2 stacks): ATK +15.2%",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.27,
                    duration_seconds=999.0,
                    notes="tier 2 (>10 stacks)",
                ),
                Effect(
                    kind=EffectKind.BUFF_CORE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.05,
                    duration_seconds=999.0,
                    notes="tier 3 (>30 stacks)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Attack Damage +35.45% 15 sec; all "
                "enemies take 645.33%; self enters Memory Incineration "
                "(weapon change, 1.8s charge, 275%/250%, unlimited "
                "ammo, 10 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=35.45,
                    duration_seconds=15.0,
                    notes=(
                        "actually 'Attack Damage +35.45%' — distinct "
                        "from BUFF_ATK; DSL gap."
                    ),
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=6.4533,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "Memory Incineration weapon change: charge "
                        "time fixed 1.8s, normal damage 275.18%, full "
                        "charge 250% × that, unlimited ammo. DSL has "
                        "no WEAPON_CHANGE / SET_CHARGE_TIME kinds. "
                        "0-mag with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Nayuta is one of the most complex Pilgrims — Memory Absorption "
        "stacks for 90 seconds (30 stacks × 3 sec), driving 3 "
        "cumulative self-buffs, while her burst weapon-change ("
        "Memory Incineration) lets her chain 1.8-sec charges with "
        "unlimited ammo for 10 sec. Substantial DSL gaps documented."
    ),
)
register_character(_SKILL)
