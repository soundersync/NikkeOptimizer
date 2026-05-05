"""Biscuit — Electric RL B2, defensive support / cover-rebuild healer.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Activates at the end of Full Burst. Affects all Attacker allies.
    Critical Rate of normal attack ▲ 5.77% for 10 sec. Constantly
    recovers 1.53% of caster's final Max HP every 1 sec for 10 sec.

**Source description (S2)**:

    When a Defender ally's HP falls below 50%: invincible for 5 sec
    (2 activations per battle). Recovers 23.26% of caster's final
    Max HP (2 activations per battle).

**Source description (Burst)**:

    Affects 2 ally units whose cover has been destroyed. Rebuild
    cover with 93.6% HP.
    Affects all Supporter allies. ATK ▲ 43.08% for 10 sec. Restores
    55.44% of attack damage as HP for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Role,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Biscuit",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst end: all Attacker allies Crit Rate +5.77% "
                "for 10 sec; regen 1.53% of caster's Max HP / sec for "
                "10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.ATTACKER,
                    ),
                    magnitude=5.77,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.ATTACKER,
                    ),
                    magnitude=1.53,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "When Defender ally's HP < 50%: invincible 5 sec + "
                "23.26% Max HP heal. 2 activations per battle each."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Defender ally HP < 50% (max 2 / battle)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.DEFENDER,
                    ),
                    magnitude=23.26,
                    notes="capped at 2 activations / battle (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: rebuild cover with 93.6% HP for 2 cover-destroyed "
                "allies; all Supporter allies ATK +43.08% and 55.44% "
                "damage→HP lifesteal for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.SUPPORTER,
                    ),
                    magnitude=43.08,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric RL B2 — defensive support / supporter-only buffer. "
        "Niche; the Supporter-filter on burst limits her offensive "
        "value. Better in stall-comp defense than in burst attack."
    ),
)
register_character(_SKILL)
