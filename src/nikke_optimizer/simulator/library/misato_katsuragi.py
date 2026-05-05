"""Misato Katsuragi — B1 Iron SMG Abnormal (Eva collab). Anti-shield support.

Encoded from the live ``Character`` skill descriptions in the DB. Misato
is a B1 SMG support — Shooting Manual stacks build hit rate, gates a
team-wide +150% Damage to Shield buff, and her burst regens the team.

**Source description (S1)**:

    Activates after landing 60 normal attacks. Affects self.
    Shooting Manual: Hit Rate ▲ 5.04%, stacks up to 3 times and lasts
    for 5 sec.

    Activates after landing 120 normal attacks. Affects 1 ally with
    the lowest HP percentage. Recovers 8.04% of caster's final Max HP
    as HP.

**Source description (S2)**:

    Only activates when in Shooting Manual status. Affects all allies.
    Damage dealt to Shield ▲ 150% continuously.
    (It only affects the damage dealt to the shield, not to the Rapture itself.)

    Only activates when Shooting Manual is fully stacked. Affects self.
    HP Potency ▲ 30.05% continuously.

**Source description (Burst)**:

    Affects all allies. Recovers 5.06% of caster's final Max HP every
    sec for 5 sec continuously.
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
    character_name="Misato Katsuragi",
    skill1=(
        SkillEffect(
            description=(
                "Every 60 normal attacks: self Shooting Manual — Hit "
                "Rate +5.04% (stacks 3x, 5 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=5.04,
                    duration_seconds=5.0,
                    stacks_max=3,
                    notes=(
                        "'Shooting Manual' state — gates her S2 anti-"
                        "shield buff."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 120 normal attacks: lowest-HP ally heals 8.04% "
                "of caster Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=8.04,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "While Shooting Manual active: all allies Damage to "
                "Shield +150% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self has Shooting Manual stacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SHIELD_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=150.0,
                    duration_seconds=999.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Shooting Manual fully stacked: self HP Potency "
                "+30.05% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Shooting Manual at 3 stacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.05,
                    duration_seconds=999.0,
                    notes="'HP Potency +30.05%' — heal-amplifier; HEAL_PER_SECOND proxy",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies regen 5.06% of caster Max HP/sec "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.06,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Misato is a B1 anti-shield support — once Shooting Manual "
        "stacks, the team's shield damage doubles (+150%). Pairs with "
        "shield-gated content and PvP teams that benefit from a "
        "burst-window team regen."
    ),
)
register_character(_SKILL)
