"""Brid: Silent Track — B2 Fire SG Elysion. Anti-Wind defense-debuff support.

Encoded from the live ``Character`` skill descriptions in the DB.
B:ST's identity is anti-Wind tagging — her S1 + S2 stack Damage Taken
debuffs on Wind-code enemies, and her burst delivers a flat ATK +66.52%
to all allies (cross-stat, except self).

**Source description (S1)**:

    On Full Burst entry:
      - All Wind Code enemies: Damage Taken ▲ 15.12% for 10 sec
      - All enemies: 636% of ATK damage

**Source description (S2)**:

    Every 10 normal attacks: 1 Wind-code lowest-HP enemy Damage Taken +12.12% 10s
    Every 5 normal attacks: 1 lowest-HP enemy 675% of ATK damage

**Source description (Burst)**:

    All allies (except self): ATK +66.52% of caster's ATK for 10 sec
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Brid: Silent Track",
    skill1=(
        SkillEffect(
            description="On Full Burst: Wind enemies +15.12% Damage Taken 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(
                        kind=TargetKind.ALL_ENEMIES,
                        filter_element=Element.WIND,
                    ),
                    magnitude=15.12,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=6.36,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Every 10 hits: Wind low-HP enemy +12.12% Damage Taken 10s",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(
                        kind=TargetKind.ENEMY_LOWEST_HP,
                        filter_element=Element.WIND,
                    ),
                    magnitude=12.12,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description="Every 5 normal hits: low-HP enemy 675% damage",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP),
                    magnitude=6.75,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies (except self) ATK +66.52% of caster's ATK 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=66.52,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="excludes self — DSL gap",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes="Anti-Wind defense-debuff B2 + flat-ATK team buffer.",
)
register_character(_SKILL)
