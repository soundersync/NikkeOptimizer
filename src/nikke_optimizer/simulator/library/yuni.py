"""Yuni — Fire RL B2, defender / CC-burst with charge-speed team buff.

Encoded from the live ``Character`` skill descriptions in the DB.
Yuni is a B2 defender — small charge-speed buff for the team on Full
Burst, small DEF/healing/ammo buff on Full Charge attacks, and a burst
that immobilizes (stuns) enemies for 5 sec while dealing modest damage.

**Source description (S1)**:

    ■ Affects all allies. Activates when entering Full Burst. Charging
    speed ▲ 8.97% for 10 sec.

**Source description (S2)**:

    ■ Affects all allies. Cast when attacking during Full Charge.
    DEF ▲ 2.77% for 10 sec. Restores 2.77% of attack damage as HP for
    10 sec. Max Ammunition Capacity ▲ 1 rounds for 5 sec.

**Source description (Burst)**:

    ■ Affects enemies within attack range. Deals 348.73% of final ATK
    as damage. Immobilizes the target(s) for 5 sec.
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
    character_name="Yuni",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Charge Speed +8.97% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=8.97,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge attack: all allies DEF +2.77% for 10 "
                "sec, lifesteal 2.77% for 10 sec, and Max Ammo +1 "
                "rounds for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.77,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.77,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'restores 2.77% of attack damage as "
                        "HP' — lifesteal-style; HEAL_PER_SECOND proxy"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.0,
                    duration_seconds=5.0,
                    notes="flat +1 round (not %); DSL gap, encoded as 1%",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: enemies in range take 348.73% of ATK and are "
                "Immobilized (stunned) for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.4873,
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.0,
                    duration_seconds=5.0,
                    notes=(
                        "actually 'Immobilize' (stun, prevents action); "
                        "DSL has no STUN kind — encoded as TAUNT proxy"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire RL B2 — utility defender with team charge-speed buff and "
        "a 5-sec AOE stun on burst. PvP-relevant for CC-heavy comps; "
        "the stun on burst is the standout ability — denies enemy "
        "burst-chain timing if landed at the right moment."
    ),
)
register_character(_SKILL)
