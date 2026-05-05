"""Pepper — B1 Wind SG Missilis. Last-bullet healer + buff stack-extender.

Encoded from the live ``Character`` skill descriptions in the DB.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects 1 allied
    unit(s) with the lowest HP percentage. Restores HP equal to 4.45%
    of caster's final Max HP.

    Activates when the last bullet hits the target. Affects all allies.
    Refresh Heart: HP Potency ▲ 6.53%, stacks up to 5 time(s) and lasts for 15 sec.

**Source description (S2)**:

    Affects 1 enemy unit(s) with the highest ATK.
    Deals 160% of final ATK as damage. ATK ▼ 3.55% for 5 sec.

**Source description (Burst)**:

    Affects 1 enemy unit(s) with the highest ATK. Deals 1237.5% of final ATK as damage.

    Affects all allies. Increases stack count of buffs by 1.

    Activates when "Refresh Heart" is fully stacked. Affects all allies.
    Restores HP equal to 27.22% of caster's final Max HP.
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
    character_name="Pepper",
    skill1=(
        SkillEffect(
            description=(
                "On last bullet: 1 lowest-HP ally heals 4.45% of "
                "Pepper's max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=1),
                    magnitude=4.45,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On last bullet: all allies stack Refresh Heart "
                "(HP Potency +6.53%, max 5, 15 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=15.0,
                    stacks_max=5,
                    notes="HP Potency +6.53% per stack — heal-amplifier; DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: highest-ATK enemy takes 160% of ATK + ATK "
                "-3.55% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=1.6,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=3.55,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: highest-ATK enemy takes 1237.5% damage; all "
                "allies +1 stack count; if Refresh Heart fully stacked "
                "→ all allies heal 27.22%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=12.375,
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=27.22,
                    notes=(
                        "conditional on Refresh Heart fully stacked. "
                        "ALSO 'stack count of buffs +1' — same gap as Soda."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Pepper is a B1 healer with single-target heal + Refresh Heart "
        "stack mechanic. Burst combines anti-tank nuke + team super-heal "
        "+ stack-count meta-buff (same as Soda) for stack-leaning comps."
    ),
)
register_character(_SKILL)
