"""Brid — B3 Water AR Tetra. Single-target attacker keyed on
defender clearance.

Encoded from the live ``Character`` skill descriptions in the DB.
Brid (base form) is a budget B3 single-target attacker — periodic
self ATK buff, S2 hits the tankiest enemy, and her burst doubles up
when the target is at max HP. Designed as an opener — best vs
fresh defenders before they take chip damage.

**Source description (S1)**:

    Self: ATK +18.52% for 10 sec (every 30 normal attacks)

**Source description (S2)**:

    Highest-DEF enemy: 211.2% of final ATK damage

**Source description (Burst)**:

    Highest-DEF enemy: 1440% of final ATK damage
    Same target if at Max HP: 1440% of final ATK additional damage
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
    character_name="Brid",
    skill1=(
        SkillEffect(
            description="Every 30 normal hits: self ATK +18.52% for 10s",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=30),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=18.52,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Highest-DEF enemy: 211.2% damage (S2 ticker)",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="S2 fires on its own cooldown",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=2.112,
                    notes="ENEMY_HIGHEST_HP as proxy for highest-DEF",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: highest-DEF enemy 1440% (×2 if max HP)",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=14.4,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=14.4,
                    notes="conditional bonus 1440% if target at Max HP",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water AR B3. Budget single-target opener — burst doubles when "
        "the target is fresh (max HP). Niche but real value as a defender "
        "popper in arena openings."
    ),
)
register_character(_SKILL)
