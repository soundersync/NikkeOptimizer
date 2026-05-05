"""Neon: Blue Ocean — Water MG B3, multi-stage element-damage carry.

Encoded from the live ``Character`` skill descriptions. Neon:BO has
a 3-phase progression on burst use that boosts Damage to Parts and
"Damage as strong element" (== element advantage damage).

**Source description (S1)**:

    On burst use: self Parts Damage +12.4% for 20 sec (each phase
    triggers repeatedly, all 3 phases give the same value).

**Source description (S2)**:

    On Burst Stage 3 entry: self Damage as strong element +20.56% (or
    +20.2%) for 10 sec, phased.

**Source description (Burst)**:

    Self weapon swap (33% ATK, 7 sec).
    When target is Fire-code: +11% ATK additional damage.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Neon: Blue Ocean",
    skill1=(
        SkillEffect(
            description=(
                "On burst use: self Parts Damage +12.4% for 20 sec "
                "(re-applies each phase, max 3 phases per battle)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.4,
                    duration_seconds=20.0,
                    stacks_max=3,
                    notes="phased — fires once per burst (1, 2, 3)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Burst Stage 3 entry: self Damage as strong element "
                "+20.56% for 10 sec (phased, +20.2% on later phases)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Burst Stage 3 entry",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.56,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon swap (33% ATK, 7 sec); target with "
                "Fire-code takes +11% ATK additional damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ENEMIES,
                        filter_element=Element.FIRE,
                    ),
                    magnitude=0.11,
                    notes="Fire-code targets only; +11% ATK additional",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water MG B3 — anti-Fire / parts-damage carry. Multi-stage "
        "phases are encoded with stage-1 magnitudes (DSL gap). Best vs "
        "Fire-element opponents."
    ),
)
register_character(_SKILL)
