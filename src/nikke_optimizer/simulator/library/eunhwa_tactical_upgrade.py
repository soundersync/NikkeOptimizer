"""Eunhwa: Tactical Upgrade — Fire SR B2, weapon-swap true-damage carry.

Burst: weapon swap (105.6% ATK true-damage per shot, 300% on full
charge, 0.3s charge time, AOE bullets). Treasure-form upgrade; strong
single-target carry.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet, Effect, EffectKind, SkillEffect, Target, TargetKind,
    Trigger, TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Eunhwa: Tactical Upgrade",
    skill1=(),
    skill2=(),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: weapon swap — 105.6% ATK true damage per shot, "
                "300% on full charge, AOE Exploding Bullet."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.056,
                    notes="weapon-swap per-shot, 0.3s charge",
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=200.0,
                    duration_seconds=10.0,
                    notes="full-charge tier (300% / 100% baseline)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Fire SR B2 — true-damage anti-shield carry.",
)
register_character(_SKILL)
