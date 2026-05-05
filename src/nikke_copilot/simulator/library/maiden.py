"""Maiden (base) — Electric SG B3, taunt-based revenge carry.

Encoded from the live ``Character`` skill descriptions. Maiden's S1
gives ATK on incoming damage; her burst opens with team taunt and a
huge crit-damage self-buff.

**Source description (S1)**:

    Activates after being attacked 20 times. Affects self. Revenge:
    ATK ▲ 26.66% for 20 sec.

**Source description (S2)**:

    Affects all enemies. Taunt for 10 sec.
    Affects self. Critical Damage ▲ 152.84% for 10 sec.

**Source description (Burst)**:

    Affects all enemies. Deals 457.87% of final ATK as damage.
    Affects same targets when in Revenge: 457.87% of ATK as additional
    damage.
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
    character_name="Maiden",
    skill1=(
        SkillEffect(
            description=(
                "Every 20 incoming attacks: self Revenge — ATK +26.66% "
                "for 20 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_DAMAGE_TAKEN, every_n_hits=20),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=26.66,
                    duration_seconds=20.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Self Crit Damage +152.84% for 10 sec; all enemies "
                "taunted for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=152.84,
                    duration_seconds=10.0,
                    notes=(
                        "actually conditional (likely on burst use); "
                        "encoded as ALWAYS placeholder"
                    ),
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 457.87% ATK damage to all enemies; +457.87% "
                "additional damage if in Revenge state."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.5787,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.5787,
                    notes="conditional on Revenge state active (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SG B3 — taunt + revenge crit carry. Niche; relies on "
        "taking enough damage to stack Revenge before her burst. "
        "Outclassed by Maiden: Ice Rose for most PvP comps."
    ),
)
register_character(_SKILL)
