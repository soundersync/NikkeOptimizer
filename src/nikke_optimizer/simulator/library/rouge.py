"""Rouge — Electric SR B1, sustain support with multi-stage Coin states.

Encoded from the live ``Character`` skill descriptions. Rouge has
three sequential states (Sword Coin → Shield Coin → Double Sword Coin)
that each unlock additional team Max-HP buffs on burst.

**Source description (S1)**:

    Activates after 8 Full Charge attacks. Affects all allies. Max HP
    ▲ 5% of caster's Max HP without restoring HP, lasts 5 sec.
    Cooldown of Burst Skill ▼ 7 sec.

**Source description (S2)**:

    When assigned to back row: Sword Coin — self + 2 adjacent allies
    Attack Damage ▲ 6.65% continuously.
    After 30 Full Charge attacks: Shield Coin — same 3 allies
    Damage Taken ▼ 15.2% continuously.
    After using burst 5 times: Double Sword Coin — all allies (in
    Shield Coin state) Max HP ▲ 15.08% of caster's Max HP continuously.

**Source description (Burst)**:

    Affects all allies. ATK ▲ 15.07% of caster's ATK for 10 sec.
    In Sword Coin: all allies Max HP ▲ 10.15% of caster's Max HP
    (no heal) for 10 sec.
    In Shield Coin: all allies Max HP ▲ 20.1% of caster's Max HP for
    10 sec.
    In Double Sword Coin: all allies Max HP ▲ 30.02% of caster's Max
    HP (no heal) for 10 sec.
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
    character_name="Rouge",
    skill1=(
        SkillEffect(
            description=(
                "Every 8 Full Charge attacks: all allies Max HP +5% of "
                "caster's Max HP for 5 sec. Burst Skill cooldown -7 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="8 Full Charge attacks accumulated",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.0,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Back-row assignment: Sword Coin — self + 2 adjacent "
                "allies Attack Damage +6.65% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                condition="back-row assignment",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=3),
                    magnitude=6.65,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies ATK +15.07% of caster's ATK for 10 sec; "
                "state-based Max HP boost (Sword Coin: +10.15%, Shield "
                "Coin: +20.1%, Double Sword Coin: +30.02% of caster's Max "
                "HP for 10 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.07,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.1,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes=(
                        "state-machine: 10.15% (Sword Coin) / 20.1% "
                        "(Shield Coin) / 30.02% (Double Sword Coin). "
                        "Encoded with Shield Coin tier as the typical "
                        "mid-match value (DSL gap)"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SR B1 — sustain-focused support with a Sword/Shield/"
        "Double-Sword Coin state ladder driving team Max-HP buffs. "
        "Position-conditional (back row) is a DSL gap; encoded as if "
        "always assigned to back row."
    ),
)
register_character(_SKILL)
