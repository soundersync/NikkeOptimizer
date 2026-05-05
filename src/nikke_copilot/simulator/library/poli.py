"""Poli — B2 Water SG. Tank defender with team shield + ATK on burst.

Encoded from the live ``Character`` skill descriptions in the DB.
Poli is the budget B2 defender — small ATK passive, DEF buff for
the 2 lowest-HP allies (with damage sharing), and a team-wide shield
+ ATK buff on burst. Common in early-game defense rosters.

**Source description (S1)**:

    Every 5 normal hits: all allies ATK +5.46% for 10s

**Source description (S2)**:

    Self + 2 lowest-HP allies (except caster): DEF +23.51% for 10s
    Same: shares damage taken for 10s

**Source description (Burst)**:

    All allies: shield 22.27% of caster's max HP for 10s
    All allies: ATK +44.55% for 10s
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
    character_name="Poli",
    skill1=(
        SkillEffect(
            description="Every 5 hits: all allies ATK +5.46% 10s",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.46,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Self + 2 lowest-HP allies: DEF +23.51% + share damage 10s",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="S2 ticks on its own cooldown",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=3),
                    magnitude=23.51,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies shield 22.27% caster max HP + ATK +44.55% 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=22.27,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=44.55,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SG B2 budget defender. Team shield + ATK buff on burst. "
        "Out-tier'd by Centi / Blanc in PvP, but a reasonable filler "
        "for early-game rosters."
    ),
)
register_character(_SKILL)
