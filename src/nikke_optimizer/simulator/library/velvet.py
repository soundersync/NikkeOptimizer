"""Velvet — Wind SR B2, ammo-pouch buffer with charge-damage team support.

Encoded from the live ``Character`` skill descriptions in the DB.
Velvet's identity is the ammo-pouch state machine — she steals enemy
bullets at battle start, then expends pouch ammo to self-buff and
team-buff. During Full Burst she sprays a low-damage SMG-style weapon
with an attack-damage amp.

**Source description (S1)**:

    ■ Activates at the start of battle and when entering Burst Stage
    2. Bullet Snatch: Steals 5% of enemies' bullets. Fills self ammo
    pouch with 6000 rounds (cap 6000). Continuous & undispellable.
    ■ Activates on Full Charge while NOT in Full Burst. Expends 100
    pouch rounds. Self ATK ▲ 30.5% and Attack Damage ▲ 30.5% for 3 sec.

**Source description (S2)**:

    ■ Activates on Full Charge during Full Burst. Expends 300 pouch
    rounds. All allies: ATK +25.2% of caster's ATK and Charge Damage
    +100.8% for 3 sec.
    ■ Activates after landing 50 normal attack(s) during Full Burst.
    Expends 300 pouch rounds. Self Attack Damage +15.03% for 5 sec;
    target takes 400.92% of final ATK as additional damage.

**Source description (Burst)**:

    ■ Affects self. Changes the weapon in use: Damage 7% of final ATK,
    Duration 10 sec. Attack Damage +34.52% for 10 sec.
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
    character_name="Velvet",
    skill1=(
        SkillEffect(
            description=(
                "Battle start / B2 entry: steal 5% of enemies' bullets "
                "and fill self ammo pouch with 6000 rounds (cap 6000)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes=(
                        "Bullet Snatch — fills ammo pouch with 6000 "
                        "rounds (cap 6000); refreshed on B2 entry; "
                        "DSL has no AMMO_POUCH state machine"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Charge while NOT in Full Burst: expend 100 pouch "
                "rounds; self ATK +30.5% and Attack Damage +30.5% for 3 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge attack outside Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.5,
                    duration_seconds=3.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.5,
                    duration_seconds=3.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Full Charge during Full Burst: expend 300 pouch rounds; "
                "all allies ATK +25.2% of caster's ATK and Charge Damage "
                "+100.8% for 3 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge attack during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=25.2,
                    duration_seconds=3.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=100.8,
                    duration_seconds=3.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 50 normal-attack hits during Full Burst: expend "
                "300 pouch; self Attack Damage +15.03% for 5 sec; target "
                "takes 400.92% of ATK as additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=50,
                condition="during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.03,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=4.0092,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon change — Damage 7% of ATK per shot, "
                "10 sec duration. Self Attack Damage +34.52% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=34.52,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.07,
                    notes=(
                        "actually weapon-change: 7% per shot for 10 sec; "
                        "headline burst payload, low per-shot but rapid"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SR B2 — ammo-pouch buffer. Steals enemy bullets at battle "
        "start. Provides team Charge Damage +100.8% and ATK +25.2% of "
        "caster's ATK during Full Burst. Niche but unique B2; pairs "
        "with SR/RL charge-damage carries."
    ),
)
register_character(_SKILL)
