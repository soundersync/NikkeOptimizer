"""Quiry — B3 Wind RL Elysion. Defender-comp support.

Encoded from the live ``Character`` skill descriptions in the DB. Quiry
is the Defender-class amplifier — buffs HP/ATK/Crit on Defender-tagged
allies and heals the team on burst. Niche pick for Defender-heavy comps.

**Source description (S1)**:

    Activates when hitting a target with Full Charge. Affects target.
    ATK ▼ 8.94% of caster's ATK for 3 sec.

    Activates when attacking with Full Charge. Affects 2 Defender ally
    units. ATK ▲ 5.81% of caster's ATK for 3 sec.

**Source description (S2)**:

    Activates when entering battle. Affects 2 Defender ally units.
    Max HP ▲ 11.63% continuously.

**Source description (Burst)**:

    Affects all allies. Recovers 6.96% of caster's final Max HP every
    1 sec for 10 sec.

    Affects all Defender allies. Critical Rate ▲ 19.9% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Role,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Quiry",
    skill1=(
        SkillEffect(
            description=(
                "On full charge hit: target's ATK -8.94% (of Quiry's "
                "ATK) for 3 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=8.94,
                    duration_seconds=3.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On full charge attack: 2 Defender allies ATK +5.81% "
                "of caster's ATK for 3 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.DEFENDER,
                    ),
                    magnitude=5.81,
                    duration_seconds=3.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="actually '2 Defender allies' — DSL no count limit",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: 2 Defender allies Max HP +11.63% "
                "continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.DEFENDER,
                    ),
                    magnitude=11.63,
                    duration_seconds=999.0,
                    notes="actually '2 Defender allies' — DSL no count limit",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies regen 6.96% of caster Max HP/sec "
                "for 10 sec; Defender allies Crit Rate +19.9% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=6.96,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.DEFENDER,
                    ),
                    magnitude=19.9,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Quiry is the rare Defender-class amplifier — buffs HP/ATK/Crit "
        "on tank-tagged allies and heals everyone on burst. Pairs "
        "natively with Defender-heavy comps (Bay / Anchor / Centi)."
    ),
)
register_character(_SKILL)
