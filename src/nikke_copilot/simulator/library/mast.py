"""Mast — Electric SMG B2, crit-damage support / DEF-shred sub-DPS.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Activates when crit attack hits 2 times. Affects target. Sea
    Breeze: DEF ▼ 1.9% of caster's DEF, max 50 stacks, 3 sec.
    Activates when HP < 70%. Affects self + 2 highest-ATK allies.
    Critical Damage ▲ 50.94% continuously.

**Source description (S2)**:

    Activates at battle start. Affects self + 2 highest-ATK allies.
    Critical Rate ▲ 23.56% for 30 sec.

**Source description (Burst)**:

    Affects self and 2 highest-ATK allies (except caster). Max HP ▲
    86.2% of caster's Max HP for 7 sec. Critical Damage ▲ 25.19% for
    7 sec.
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
    character_name="Mast",
    skill1=(
        SkillEffect(
            description=(
                "Every 2 crit hits: Sea Breeze on target — DEF -1.9% of "
                "caster's DEF, max 50 stacks, 3 sec each."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=2),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.9,
                    duration_seconds=3.0,
                    stacks_max=50,
                    notes="actually % of caster's DEF (DSL gap on caster-scaled debuffs)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When self HP < 70%: self + top-2 ATK allies Crit Damage "
                "+50.94% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self HP < 70%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=3),
                    magnitude=50.94,
                    duration_seconds=86400.0,
                    notes="actually self + 2 highest-ATK allies",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self + top-2 ATK allies Crit Rate +23.56% "
                "for 30 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=3),
                    magnitude=23.56,
                    duration_seconds=30.0,
                    notes="actually self + 2 highest-ATK allies",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self + top-2 ATK allies Max HP +86.2% of caster's "
                "Max HP and Crit Damage +25.19% for 7 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=3),
                    magnitude=86.2,
                    duration_seconds=7.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=3),
                    magnitude=25.19,
                    duration_seconds=7.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=7.0,
    notes=(
        "Electric SMG B2 — crit-damage support / DEF-shred via Sea Breeze "
        "stacks. Most of her value goes to the highest-ATK 2 allies, so "
        "she pairs naturally with Crown-comp B3 carries."
    ),
)
register_character(_SKILL)
