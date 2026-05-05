"""Mary: Bay Goddess — B1 Water SR Tetra. Cumulative-activation healer/buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Mary: Bay Goddess uses the same cumulative-activation pattern as Liter
S1 / Volume S2 — effects scale across successive Full Burst windows.

**Source description (S1)** (cumulative):

    On Full Burst entry — recovers HP/sec for 5 sec.
        Once: 1.05% of caster's max HP/sec
        Twice: 3.69% of caster's max HP/sec
        Three times: 6.86% of caster's max HP/sec

**Source description (S2)** (cumulative, Water-code only):

    On burst use — Water-code allies "Damage as strong element" buff.
        Once: +20.85% for 3 sec
        Twice: +13.88% for 5 sec
        Three times: +8.36% for 10 sec

**Source description (Burst)**:

    Affects all Water Code allies. ATK ▲ 23.23% for 3 sec.

    Affects all allies. Max HP ▲ 27.87% of caster's final max HP as HP
    for 10 seconds.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Mary: Bay Goddess",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies recover 6.86% max HP/sec "
                "for 5 sec (third-tier; cumulative 1.05/3.69/6.86)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                notes="effect scales with cumulative activation count",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=6.86,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On burst: all Water-code allies strong-element damage "
                "+8.36% for 10 sec (third-tier; cumulative)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                notes="effect scales with cumulative activation count",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=8.36,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: Water-code allies ATK +23.23% (3s); all allies "
                "Max HP +27.87% (10s)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=23.23,
                    duration_seconds=3.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=27.87,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Mary: Bay Goddess is the Water-code answer to Liter — "
        "cumulative-activation healing + element-conditional team ATK "
        "buff. Pairs with Water-element attackers (SW:HA, Privaty, "
        "Phantom)."
    ),
)
register_character(_SKILL)
