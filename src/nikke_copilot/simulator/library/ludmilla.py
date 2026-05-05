"""Ludmilla — Water SMG B1, burst-DEF-buff support (base form).

Burst: 163.1% ATK damage to 10 highest-ATK enemies; if above 50% HP,
all allies DEF +12.93% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Ludmilla",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 163.1% ATK damage to 10 highest-ATK enemies; "
                "if above 50% HP: all allies DEF +12.93% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.631,
                    notes="actually 10 highest-ATK enemies",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=12.93,
                    duration_seconds=10.0,
                    notes="conditional on caster HP > 50%",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Water SMG B1 (base). Outshone by Ludmilla: Winter Owner in PvP.",
)
register_character(_SKILL)
