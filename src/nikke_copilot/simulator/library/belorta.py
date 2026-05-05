"""Belorta — B2 Electric RL. AOE attacker with team charging-speed buff.

Encoded from the live ``Character`` skill descriptions in the DB.
Belorta's identity is multi-target hits — her S2 fires on >4-enemy
hits with a small DEF debuff, and her burst hits the entire range +
buffs all allies' charging speed.

**Source description (S1)**:

    On Full Charge: self Explosion Radius +9.55% for 5s

**Source description (S2)**:

    Normal attack hits >4 enemies: enemies hit — DEF -3.52% for 5s
    Same: 14.96% of final ATK additional damage

**Source description (Burst)**:

    Enemies in attack range: 192% of final ATK damage
    All allies: Charging Speed +2.82% for 10s
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
    character_name="Belorta",
    skill1=(
        SkillEffect(
            description="On Full Charge: self Explosion Radius +9.55% 5s",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                notes="full-charge attacks only",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=9.55,
                    duration_seconds=5.0,
                    notes="Explosion Radius — captured as parts-damage proxy",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Hit >4 enemies: enemies DEF -3.52% 5s + 14.96% additional damage",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition=">4 enemies hit by normal attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.52,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.1496,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: range 192% damage + allies Charging Speed +2.82% 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.92,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.82,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric RL B2 AOE attacker — multi-target hits + charging "
        "speed buff. Very niche due to small magnitudes; useful PvE add."
    ),
)
register_character(_SKILL)
