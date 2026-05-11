"""Kurumi — B1 Iron AR Abnormal. Hack DoT debuffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Kurumi applies "Hacked" sustained damage to targets via normal-attack
counter and on her own burst use. Niche but interesting as a DoT
applier in mono-Iron Anomaly comps.

**Source description (S1)**:

    Activates after landing 36 normal attack(s). Affects the target.
    Hacked: Deals 52.24% of final ATK as sustained damage every 1 sec
    for 5 sec.
    Activates when using Burst Skill. Affects all enemies. Hacked: Deals
    52.24% of final ATK as sustained damage every 1 sec for 5 sec.

**Source description (S2)**:

    Activates during Full Burst after landing 36 normal attack(s) while
    the target is in Hacked status. Affects the target. Deals 86.17%
    of final ATK as additional damage.

**Source description (Burst)**:

    Affects all enemies. Damage Taken ▲ 18.06% for 10 sec.
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
    character_name="Kurumi",
    skill1=(
        SkillEffect(
            description=(
                "Every 36 normal attacks: target takes 52.24% of ATK as "
                "sustained damage / sec for 5 sec (Hacked status)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=36),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.5224,
                    duration_seconds=5.0,
                    notes="Hacked: 52.24% / 1s DOT — DSL uses INFLICT_BURN as generic DOT",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use: all enemies Hacked (52.24% / 1s DOT) for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.5224,
                    duration_seconds=5.0,
                    notes="Hacked: 52.24% / 1s DOT",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "During Full Burst, every 36 normal attacks vs Hacked "
                "target: 86.17% of ATK as additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=36,
                condition="during Full Burst AND target has Hacked status",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.8617,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all enemies take +18.06% damage for 10 sec.",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=18.06,
                    duration_seconds=10.0,
                    notes=(
                        "'Damage Taken ▲' — DSL has no DEBUFF_DAMAGE_TAKEN "
                        "kind; encoded as DEBUFF_DEFENSE approximation."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Kurumi's Hacked DOT is her main contribution — fits anti-tank "
        "comps where extended damage-taken windows matter. "
        "Damage Taken ▲ is approximated as a DEF debuff."
    ),
)
register_character(_SKILL)
