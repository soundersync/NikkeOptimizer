"""Flora — B2 Electric MG Missilis Botanic Garden. True Damage supporter.

Encoded from the live ``Character`` skill descriptions in the DB. Flora
buffs adjacent allies (self + 2 either side) with regen + heal-restored
stack on battle start, gives Electric allies a buff-stack +1 every 100
hits, and her burst applies a team heal + True Damage +42.39%.

**Source description (S1)**:

    Battle start (if self survives): self + 2 allies each side recover
    1% caster max HP per sec. HP restored ▲ 4% (stacks ×5, continuous).

    Every 100 normal attacks: all Electric Code allies, stack count of
    buffs ▲ 1.

**Source description (S2)**:

    When any adjacent ally HP < 90%: all allies gain a Shield 10.22%
    caster max HP for 10 sec.

    When any adjacent ally HP at max: all allies True Damage +30.97%
    for 5 sec.

**Source description (Burst)**:

    All allies recover 10.45% of caster's max HP.
    True Damage +42.39% for 10 sec.
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
    character_name="Flora",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: self + 2 allies each side recover 1% max "
                "HP/sec. HP restored +4% (×5 stacks, continuous)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=5),
                    magnitude=1.0,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="self + 2 each side = up to 5 adjacent",
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=5),
                    magnitude=4.0,
                    duration_seconds=999.0,
                    stacks_max=5,
                    notes=(
                        "HP restored +4% potency stack ×5 — modifier "
                        "on heal potency. DSL gap (HEAL_POTENCY)."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 100 normal attacks: Electric Code allies, stack "
                "count of buffs +1."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=100),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "Stack count of buffs +1 — meta-buff that adds "
                        "a stack to existing buff effects. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "When adjacent ally HP < 90%: all allies shield 10.22% "
                "caster max HP 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any adjacent ally HP < 90%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.22,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When adjacent ally reaches max HP: all allies True "
                "Damage +30.97% 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any adjacent ally at max HP",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.97,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies recover 10.45% of caster's max HP; "
                "True Damage +42.39% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.45,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=42.39,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric MG B2 — niche True Damage supporter with adjacent-"
        "ally healing and Electric-element buff-stack manipulation. "
        "Best in Electric stack comps (e.g. Anis: Sparkling Summer) "
        "or as a B2 healer alternative."
    ),
)
register_character(_SKILL)
