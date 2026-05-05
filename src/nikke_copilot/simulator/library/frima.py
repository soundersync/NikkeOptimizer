"""Frima — B1 Iron SR. DEF debuffer + max-HP team buff support.

Encoded from the live ``Character`` skill descriptions in the DB.
Frima is a budget alternative B1 — every 4 hits applies DEF debuff,
Full Charge attacks heal team Max HP slightly, burst targets 10
high-DEF enemies and Max HP boosts all allies.

**Source description (S1)**:

    Every 4 normal hits: target — DEF -15.84% for 10s

**Source description (S2)**:

    Full Charge: all allies Max HP +6.09% for 5s

**Source description (Burst)**:

    10 highest-DEF enemies: 101.66% damage; DEF -9.86% for 10s
    All allies: Max HP +30.26% for 4s
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
    character_name="Frima",
    skill1=(
        SkillEffect(
            description="Every 4 hits: target DEF -15.84% 10s",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=4),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=15.84,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Full Charge: all allies Max HP +6.09% 5s",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full-charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=6.09,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: 10 high-DEF enemies 101.66% + DEF -9.86% 10s + allies Max HP +30.26%",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=1.0166,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=9.86,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.26,
                    duration_seconds=4.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SR B1 budget supporter. DEF-debuff focus + small team "
        "Max HP boosts. Out-tier'd by Liter / Tia / Dorothy in PvP "
        "but a reasonable filler in early-game rosters."
    ),
)
register_character(_SKILL)
