"""Bready — B3 Water SR. Sustained-damage / distributed-damage
state-machine attacker.

Encoded from the live ``Character`` skill descriptions in the DB.
Bready toggles between Lingering Taste (sustained-damage focus) and
Recommended Taste (distributed-damage focus). Both apply Charge Speed
-20% as trade-off. Burst doubles down on whichever state is active.

**Source description (S1)**:

    On entering Full Burst: self ATK +70.01% for 10s
    On gaining Sustained-damage buff: self Lingering Taste — Charge
    Speed -20% for 50s; removes Recommended Taste
    On gaining Distributed-damage buff (no sustained): self
    Recommended Taste — Charge Speed -20% for 50s; removes Lingering

**Source description (S2)**:

    3 Full Charge in Lingering: target Damage Taken +10.2% 5s; +
    Aftertaste 150.04% sustained / 1s for 5s
    Full Charge in Recommended: self Attack Damage +60.01% 5s
    Full Charge in Recommended: all enemies — 265.07% distributed dmg

**Source description (Burst)**:

    Self: Attack Damage +60.19% for 10s
    In Lingering: self Aftertaste Effect +349.8% for 10s
    In Recommended: self ATK +70.09% for 10s
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
    character_name="Bready",
    skill1=(
        SkillEffect(
            description="On FB entry: self ATK +70.01% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=70.01,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="3 Full Charge in Lingering: target +10.2% DT + Aftertaste DOT 5s",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=3,
                condition="full-charge in Lingering Taste",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=10.2,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.5004,
                    duration_seconds=5.0,
                    notes="Aftertaste: 150.04% / 1s sustained DOT",
                ),
            ),
        ),
        SkillEffect(
            description="Full Charge in Recommended: self Attack Damage +60.01% 5s + 265% distributed",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full-charge in Recommended Taste",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.01,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.6507,
                    notes="distributed damage — captured as base damage",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: self Attack Damage +60.19% + state-conditional buffs (10s)",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.19,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=349.8,
                    duration_seconds=10.0,
                    notes="Aftertaste Effect (Lingering only)",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=70.09,
                    duration_seconds=10.0,
                    notes="ATK +70.09% (Recommended only)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SR B3 sustained / distributed dual-state attacker. "
        "Lingering favors sustained-damage builds, Recommended favors "
        "burst windows. Charge Speed -20% from either state is a "
        "permanent trade-off."
    ),
)
register_character(_SKILL)
