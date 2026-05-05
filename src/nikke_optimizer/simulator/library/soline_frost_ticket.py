"""Soline: Frost Ticket — Water SG B1, ticket-based sustain support.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    At battle start or burst: issues 1 ticket (max 2). Continuous.
    Ticket effect: Max HP ▲ ticket count × 10% of caster's Max HP
    (no heal).
    Full Burst entry: all allies' burst skill cooldown -7.48 sec.

**Source description (S2)**:

    When any squad HP < 15%: target with tickets recovers 12.27% of
    caster's Max HP. Ticket count -1.
    Battle start: all allies First Train Discount for 6 sec.

**Source description (Burst)**:

    All allies recover 32.26% of caster's Max HP.
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
    character_name="Soline: Frost Ticket",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: issue 1 ticket — Max HP +10% of caster's "
                "Max HP per ticket (max 2 tickets)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    stacks_max=2,
                    notes="ticket-based stacking; max 2",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst entry: all allies burst skill CD -7.48 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.48,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "When squad ally HP < 15%: target with tickets heals "
                "12.27% of caster's Max HP, ticket -1."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="squad ally HP < 15% + has tickets",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=12.27,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies recover 32.26% of caster's Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=32.26,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SG B1 — ticket-based sustain support. Strong stall comp "
        "anchor with team Max-HP buffs and emergency heals. Burst-CD "
        "reduction makes her a viable B1 in stall-defense lineups."
    ),
)
register_character(_SKILL)
