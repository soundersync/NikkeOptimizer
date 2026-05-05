"""Ade — B2 Wind AR Tetra. Debuff-immunity + Max HP buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Ade's signature is Perfect Maid (debuff immunity, 1 stack), making her
counter to debuff-leaning opponents (Privaty stuns, Noah debuffs). Her
Max-HP buffs scale team durability.

**Source description (S1)**:

    Activates when entering battle. Affects all allies.
    Perfect Maid: Gain debuff immunity to 1 debuff(s) and stacks up
    to 1 times(s) continuously.

    Activates when own HP falls below 90%. Affects all allies.
    ATK ▲ 5.19% of caster's ATK for 5 sec.

**Source description (S2)**:

    Activates after 420 normal attack(s). Affects all allies.
    Perfect Maid: Gain debuff immunity to 1 debuff(s) and stacks up
    for 1 time continuously.

    Activates after 120 normal attack(s). Affects all allies.
    Max HP ▲ 15.62% of caster's Max HP without restoring HP, lasts for 5 sec.

**Source description (Burst)**:

    Affects all allies. Max HP ▲ 25.15% of caster's Max HP without
    restoring HP, lasts for 10 sec.
    ATK ▲ 10.15% of caster's ATK for 10 sec.

**DSL gaps**:

  * "Debuff immunity" — DSL has no IMMUNITY effect kind. Captured as
    note on a placeholder buff.
  * "Max HP without restoring HP" — distinct from BUFF_HP which heals.
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
    character_name="Ade",
    skill1=(
        SkillEffect(
            description=(
                "On battle start: all allies gain Perfect Maid (1 "
                "debuff immunity, 1 stack)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes=(
                        "Perfect Maid: 1 debuff immunity, 1 stack. "
                        "DSL gap (DEBUFF_IMMUNITY)."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Ade's HP falls below 90%: all allies ATK +5.19% "
                "for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Ade's HP < 90%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.19,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 420 normal attacks: Perfect Maid +1 stack."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=420),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes="adds another debuff immunity stack",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 120 normal attacks: all allies Max HP +15.62% "
                "(no heal) for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.62,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="'Max HP +X% of caster's Max HP without restoring HP'",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Max HP +25.15% (no heal), ATK +10.15% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=25.15,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="'Max HP +25.15% of caster's Max HP without HP restore'",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.15,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Ade's Perfect Maid is the canonical anti-debuff defender — "
        "she lets the team shrug off Privaty stuns / Noah debuffs / "
        "etc. Her HP buff stacking also makes her a soft tank for "
        "extended fights."
    ),
)
register_character(_SKILL)
