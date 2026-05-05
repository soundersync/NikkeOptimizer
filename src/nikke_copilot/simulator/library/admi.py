"""Admi — B2 Wind SR. Defensive supporter — damage-taken reduction
+ team Crit Damage / reload buff.

Encoded from the live ``Character`` skill descriptions in the DB.
Admi's identity is the high-ATK ally damage reduction (S2) plus
charge-damage buff via passive (S1) and Crit Damage / Reload Speed
team buff via burst. Niche tank-supporter.

**Source description (S1)**:

    On attacked 20×: all allies Charge Damage Multiplier +9.59% for 20s

**Source description (S2)**:

    2 highest-ATK allies: Damage Taken -28.65% for 10s

**Source description (Burst)**:

    All allies: Reload Speed +50.91% for 10s
    All allies: Crit Damage +28.34% for 10s
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
    character_name="Admi",
    skill1=(
        SkillEffect(
            description="When attacked 20x: all allies Charge Damage +9.59% 20s",
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                notes="every 20 damage-received events",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=9.59,
                    duration_seconds=20.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Top 2 ATK allies: Damage Taken -28.65% 10s (S2 ticker)",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="S2 ticks on its own cooldown",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=28.65,
                    duration_seconds=10.0,
                    notes="Damage Taken -28.65% — captured as DEF buff",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies Reload Speed +50.91% + Crit Damage +28.34% (10s)",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=50.91,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=28.34,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SR B2 defensive supporter. -28.65% Damage Taken on top "
        "ATK allies + team crit/reload on burst. Underrated mixed "
        "support — reload buff helps RL/SG comps."
    ),
)
register_character(_SKILL)
