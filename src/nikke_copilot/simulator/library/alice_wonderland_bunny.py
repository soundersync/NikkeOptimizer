"""Alice: Wonderland Bunny — B1 Water SMG. Re-Enter Burst Stage 1
supporter with team gauge-fill speedup and ammo regen.

Encoded from the live ``Character`` skill descriptions in the DB.
A:WB's identity is the unique "burst again" mechanic via her own
re-enter Burst Stage 1, plus a +10% gauge-fill speed buff on the
Full Burst exit and Carrot Party stack-amp interactions.

**Source description (S1)**:

    Every 60 normal hits: all allies recover 7.4% of caster's max HP
    Every 60 normal hits: Carrot Party — Damage to interruption part
    +2% per stack (max 5, 5 sec)
    Every 90 normal hits: all Water Code allies stack count of buffs +1

**Source description (S2)**:

    On Full Burst end: all allies Burst Gauge filling speed +10% for 5s
    On entering Full Burst: all allies Max Ammo +40% for 15s, Reload 40%

**Source description (Burst)**:

    All allies: Re-enter Burst Skill Stage 1
    All allies: recover 27% of caster's max HP
    On Carrot Party fully stacked: all allies HP Potency +150% for 15s
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Alice: Wonderland Bunny",
    skill1=(
        SkillEffect(
            description="Every 60 hits: all allies heal + Carrot Party stack",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.4,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.0,
                    duration_seconds=5.0,
                    stacks_max=5,
                    notes="Carrot Party — interrupt-part dmg +2%/stack",
                ),
            ),
        ),
        SkillEffect(
            description="Every 90 hits: Water allies stack count +1",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=90),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes="Stack count +1 meta-buff — DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On FB exit: all allies Burst Gauge fill speed +10% 5s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    duration_seconds=5.0,
                    notes="gauge-fill rate +10% — buff over time",
                ),
            ),
        ),
        SkillEffect(
            description="On FB start: all allies Max Ammo +40% 15s, Reload 40%",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.0,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.0,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: Re-Enter Stage 1 + heal + (if Carrot maxed) HP Pot +150%",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=27.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=150.0,
                    duration_seconds=15.0,
                    notes=(
                        "HP Potency +150% (conditional on Carrot Party "
                        "fully stacked). Captured as BUFF_HP."
                    ),
                ),
                # Re-enter Burst Stage 1 — DSL gap, captured as note.
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=100.0,
                    notes=(
                        "Re-Enter Burst Stage 1 — refunds team burst "
                        "gauge for an immediate second chain. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SMG B1 supporter — pioneering Re-Enter Burst Stage 1 "
        "mechanic enables back-to-back Full Burst chains. Critical for "
        "double-burst comps and high-DPS attackers that need extra burst "
        "windows."
    ),
)
register_character(_SKILL)
