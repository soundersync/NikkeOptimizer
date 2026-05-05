"""Trina — Electric RL B2, Electric AR-comp specialist.

Encoded from the live ``Character`` skill descriptions. Trina's S2
gates major buffs on Electric-Code rifle allies; her burst includes
a "1 enemy alive" boss-room conditional that's irrelevant in PvP 5v5.

**Source description (S1)**:

    Activates after Full Burst ends. Affects all allies. Recovers
    4.06% of caster's Max HP every 1 sec for 5 sec.

**Source description (S2)**:

    Battle start (if self alive): Electric Code rifle allies Max HP
    +44.98% of caster's Max HP continuously.
    Battle start: leftmost Electric Code rifle ally invulnerable for 2 sec.

**Source description (Burst)**:

    All allies: Max HP +20.14% of caster's Max HP for 10 sec, Attack
    Damage +20.9% for 10 sec.
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
    character_name="Trina",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst end: all allies regen 4.06% of caster's Max "
                "HP / sec for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=4.06,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: Electric-Code rifle allies Max HP +44.98% "
                "of caster's Max HP continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=44.98,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes=(
                        "actually filtered to Electric-code rifle allies "
                        "only — encoded as ALL_ALLIES proxy (DSL gap "
                        "on multi-filter target)"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Max HP +20.14% of caster's Max HP and "
                "Attack Damage +20.9% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.14,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.9,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric RL B2 — Electric-code rifle support. Most of her power "
        "depends on the team being Electric-code AR/SR; otherwise she "
        "reduces to a baseline B2 with the burst Max-HP + Attack Damage "
        "team buff."
    ),
)
register_character(_SKILL)
