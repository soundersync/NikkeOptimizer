"""Centi (Treasure) — B2 Iron RL Missilis. Treasure Centi with auto S2.

Encoded from the live ``Character`` skill descriptions in the DB.
The Treasure form adds: auto-S2 cast at battle start, shield-break heal
proc, and a Max-HP self-buff added to her burst. Otherwise mirrors
base Centi.

**Source description (S1)**:

    Activates at the start of battle. Affects self.
    Forcefully uses Skill 2.

    Activates when landing a Full Charge attack. Affects self.
    Cooldown of Skill 2 ▼ 9.16%.

    Activates when the shield created by Centi is destroyed. Affects
    all allies. Recovers 9.7% of caster's final Max HP as HP.

**Source description (S2)**:

    Affects all allies. Creates a Shield equal to 7% of caster's final
    Max HP for 5 sec.

**Source description (Burst)**:

    Affects 5 enemy unit(s) with the lowest remaining HP.
    Deals 145.46% of final ATK as damage. DEF ▼ 14.54% for 10 sec.

    Affects self. Max HP ▲ 5% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Centi (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "On battle start: forcefully cast S2 (instant team shield)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.0,
                    duration_seconds=5.0,
                    notes="auto S2 cast at battle start",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge hit: self S2 cooldown -9.16%."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    notes=(
                        "actually 'Cooldown of Skill 2 -9.16%' — DSL "
                        "gap (REDUCE_SKILL_COOLDOWN)"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Centi's shield is destroyed: all allies recover "
                "9.7% of Centi's max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_SHIELD_BREAK),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=9.7,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic team shield: 7% of Centi's max HP for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="fires on S2's own timer; accelerated by S1",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.0,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 5 lowest-HP enemies → 145.46% damage + DEF "
                "-14.54% (10s); self Max HP +5% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP, count=5),
                    magnitude=1.4546,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP, count=5),
                    magnitude=14.54,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=5.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Centi (Treasure) is base Centi + auto-cast S2 at battle start "
        "+ shield-break team heal + small self Max HP burst buff. "
        "Pure upgrade for defense comps that already run Centi."
    ),
)
register_character(_SKILL)
