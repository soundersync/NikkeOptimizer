"""Helm: Aquamarine — B2 Iron AR Elysion. Anti-Electric burst-CD support.

Encoded from the live ``Character`` skill descriptions in the DB. The
Aquamarine alt form trades base Helm's nuke-burst for a cumulative
team burst-CD reduction + anti-Electric stacking damage debuff.

**Source description (S1)**:

    Activates after landing 30 normal attack(s). Affects the target.
    Deals 131.34% of final ATK as additional damage.

    Activates when entering Full Burst. Affects all allies.
    Effect changes according to the number of activation time(s).
    Previous effects triggers repeatedly:
        Once:        Burst Skill cooldown ▼ 1.82 sec.
        Twice:       Burst Skill cooldown ▼ 2.2 sec.
        Three times: Burst Skill cooldown ▼ 2.6 sec.

**Source description (S2)**:

    Affects 1 enemy unit randomly. Deals 105.58% of final ATK as damage.

    Affects the same target when they belong to Electric Code.
    Damage Taken ▲ 5.64%, stacks up to 5 times and lasts for 5 sec.

**Source description (Burst)**:

    Affects all enemies. Deals 164.73% of final ATK as damage.

    Affects the same target(s) when they belong to Electric Code.
    Deals 164.73% of final ATK as additional damage.
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
    character_name="Helm: Aquamarine",
    skill1=(
        SkillEffect(
            description=(
                "Every 30 normal attacks: target takes 131.34% of ATK."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=30),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.3134,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: all allies burst CD -2.6 sec "
                "(third-tier; cumulative 1.82/2.2/2.6)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                notes="cumulative activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.6,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: 1 random enemy takes 105.58% of ATK damage."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=1),
                    magnitude=1.0558,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When the random target is Electric-code: stacks Damage "
                "Taken +5.64% (max 5, 5 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="target is Electric-code enemy",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=1),
                    magnitude=5.64,
                    duration_seconds=5.0,
                    stacks_max=5,
                    notes="actually 'Damage Taken +5.64%'; DEBUFF_DEFENSE proxy",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all enemies take 164.73% damage; Electric-code "
                "enemies take an extra 164.73%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.6473,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ENEMIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=1.6473,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Helm: Aquamarine is the team-CD-reduction alt form (different "
        "from base Helm's anti-tank nuke). Strong in Electric matchups "
        "and any team that benefits from faster burst rotations."
    ),
)
register_character(_SKILL)
