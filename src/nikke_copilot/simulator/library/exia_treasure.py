"""Exia (Treasure) — Electric SR B1, anti-DEF / damage-taken support.

Burst: top-10 highest-DEF enemies take 122.32% ATK damage + DEF -2.71%
for 5 sec. At Collect Hacking Code max stacks: same targets take
+122.32% ATK additional + Damage Taken +18.04% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Exia (Treasure)",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 122.32% ATK damage to high-DEF enemies, DEF "
                "-2.71% for 5 sec; +122.32% additional + Damage Taken "
                "+18.04% if Collect Hacking Code fully stacked."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.2232,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.71,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.2232,
                    notes="conditional on Collect Hacking Code max stacks",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Electric SR B1 (Treasure). Anti-stall / DEF-shred sniper.",
)
register_character(_SKILL)
