"""Guillotine: Winter Slayer — B3 Water AR Elysion. Hero-Level scaling carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Winter Slayer's identity is the Hero Level system — built up by EXP
stacks (gained on body-only hits + every 3 core hits), each level
escalates Damage as Strong Element + ATK on Water-code allies.

**Source description (S1)**:

    Activates every time EXP stacks 10. Affects self.
    Hero Level Up: Reaches a maximum of Level 11.
    Hero Level Up Reward: Reloads 10.26%.
    Hero Level Up Reward: Recovers 2.44% of caster's final Max HP.

    Activates when Hero levels up. Affects all Water Code allies.
    Damage as strong element ▲ 1.16% * Hero Level continuously.
    ATK ▲ 0.91% of caster's ATK * Hero Level continuously.

**Source description (S2)**:

    Activates after landing 6 normal attacks without hitting the core.
    Affects self. EXP: ATK ▲ 1.81%, stacks up to 100 times continuously.

    Activates when hitting the Core for 3 times. Affects self.
    EXP: ATK ▲ 1.81%, stacks up to 100 times continuously.

    Activates when Hero Level is 2 or above. Affects self.
    Damage as strong element ▲ 7.46% continuously.

**Source description (Burst)**:

    Affects all Water Code allies.
    Attack Damage ▲ 10.14% for 10 sec.
    Damage as strong element ▲ 18.75% for 10 sec.

    Affects 1 enemy unit with the highest Max HP.
    Deals continuous damage equal to 20.87% of final ATK * Hero Level
    every sec for 10 sec.
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
    character_name="Guillotine: Winter Slayer",
    skill1=(
        SkillEffect(
            description=(
                "Every 10 EXP stacks: Hero Level +1 (max 11), self "
                "reload 10.26%, heal 2.44% Max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="EXP reaches 10/20/30/.../110",
                notes="cumulative — Hero Level state machine, max 11",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=10.26,
                    duration_seconds=999.0,
                    notes="actually 'Reloads 10.26%' — instant reload chunk",
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.44,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Hero Level up (3rd-tier, max 11): all Water "
                "allies DamageAsStrong +12.76%, ATK +10.01% of caster's "
                "ATK continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Hero Level >= 11 (max)",
                notes=(
                    "Hero Level cumulative — encoded at max value. "
                    "Per-level scaling: 1.16% × 11 = 12.76% DamageAsStrong, "
                    "0.91% × 11 = 10.01% ATK."
                ),
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=12.76,
                    duration_seconds=999.0,
                    notes=(
                        "'Damage as strong element +1.16% × Hero Level' "
                        "— at max Lv 11"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=10.01,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="'ATK +0.91% × Hero Level' at max Lv 11",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 6 body-hit normals OR every 3 core hits: self "
                "EXP +1 stack (ATK +1.81%, max 100)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=6),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.81,
                    duration_seconds=999.0,
                    stacks_max=100,
                    notes=(
                        "'EXP' state — accumulates from body-only hits "
                        "(every 6) and core hits (every 3); drives the "
                        "Hero Level system. DSL doesn't model body-vs-core."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Hero Level >= 2: self DamageAsStrong +7.46% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Hero Level >= 2",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=7.46,
                    duration_seconds=999.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: Water allies Attack Damage +10.14%, "
                "DamageAsStrong +18.75% 10 sec; highest-HP enemy DOTed "
                "by 20.87%/sec × Hero Level 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=10.14,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=18.75,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=2.2957,
                    duration_seconds=10.0,
                    notes=(
                        "'20.87% × Hero Level per sec' — at max Lv 11 "
                        "= 229.57%. INFLICT_BURN proxy for sustained "
                        "single-target damage."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Winter Slayer is the Hero-Level scaling AR carry — EXP stacks "
        "from body+core hits, leveling up gives team-wide DamageAsStrong "
        "+ ATK boosts on Water-code allies. Pairs with Water-code teams "
        "(Anchor, Anis: SS, Privaty, base Privaty) and her own ramp-up "
        "favors longer fights."
    ),
)
register_character(_SKILL)
