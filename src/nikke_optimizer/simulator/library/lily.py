"""Lily — B2 Wind SMG Abnormal. Cover-repair support.

Encoded from the live ``Character`` skill descriptions in the DB.
Lily's gimmick is cover recovery — she heals allies' covers and
rebuilds destroyed ones on burst. Niche but the only character in the
game that can rebuild a downed cover.

**Source description (S1)**:

    Affects 1 random ally unit. ATK ▲ 20% of caster's ATK for 5 sec.

**Source description (S2)**:

    Affects all allies. Cover's HP recovers by 10%.

**Source description (Burst)**:

    Affects 1 random ally unit whose cover has been destroyed. Rebuild
    Cover with 30% HP. ATK ▲ 20% of caster's ATK for 10 sec.
    Affects 1 random ally unit if there is no ally unit whose cover has
    been destroyed. ATK ▲ 40% of caster's ATK for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Lily",
    skill1=(
        SkillEffect(
            description=(
                "Periodic: random ally gets ATK +20% of caster's ATK "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES, count=1),
                    magnitude=20.0,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="1 random ally — DSL uses ALL_ALLIES + count=1",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Periodic: all allies' covers recover 10% HP.",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="cover heal — DSL has no COVER_HEAL kind",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    notes="actually heals 'Cover HP', not member HP",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: random ally with destroyed cover gets cover "
                "rebuilt at 30% HP + ATK +20% of caster's ATK for 10 sec. "
                "Or, if no cover is destroyed, 1 random ally gets ATK "
                "+40% of caster's ATK for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES, count=1),
                    magnitude=30.0,
                    notes="rebuilds cover with 30% HP if destroyed",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES, count=1),
                    magnitude=40.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "20% if cover-rebuild branch fires, 40% otherwise. "
                        "Encoded as 40% upper bound."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Lily is the only cover-rebuilder in the game. Niche; PvP value "
        "is low because covers rarely survive 5 minutes anyway."
    ),
)
register_character(_SKILL)
