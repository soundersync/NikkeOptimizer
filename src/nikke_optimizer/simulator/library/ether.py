"""Ether — B1 Electric SG Missilis. Shield + sustained-damage debuffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Ether's kit is anti-DOT focused: she reduces sustained damage taken
on the lowest-HP ally and burst-shields the back three. A niche pick
for matchups against burn/sustained-damage attackers.

**Source description (S1)**:

    Affects 1 ally with the lowest HP. Sustained Damage ▼ 52.5% for 5 sec.

**Source description (S2)**:

    Affects 3 enemies with the highest DEF. Deals 56.32% of final ATK as damage.
    Affects one enemy. Activates during Full Burst. DEF ▼ 9.38% for 6 sec.

**Source description (Burst)**:

    Affects 3 allied unit(s) with the lowest HP. Creates a Shield equal
    to 96% of the caster's Max HP for 5 sec.
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
    character_name="Ether",
    skill1=(
        SkillEffect(
            description=(
                "Periodic: lowest-HP ally Sustained Damage taken -52.5% "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=52.5,
                    duration_seconds=5.0,
                    notes=(
                        "'Sustained Damage ▼' on ally — DSL has no "
                        "DEBUFF_SUSTAINED_DAMAGE_TAKEN; encoded as note."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: deals 56.32% of ATK to 3 highest-DEF enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES, count=3),
                    magnitude=0.5632,
                    notes="3 highest-DEF enemies (target kind approximation)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "During Full Burst: one enemy DEF -9.38% for 6 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMY_FRONT),
                    magnitude=9.38,
                    duration_seconds=6.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 3 lowest-HP allies get a shield equal to 96% of "
                "Ether's Max HP for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=3),
                    magnitude=96.0,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Ether is a niche anti-DOT defender — only meaningful in "
        "matchups with sustained-damage carries (Modernia, Maxwell, A2)."
    ),
)
register_character(_SKILL)
