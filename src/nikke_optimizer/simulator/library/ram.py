"""Ram — B1 Wind SR Abnormal. ATK debuff + team shield support.

Encoded from the live ``Character`` skill descriptions in the DB.
Ram is a budget anti-DPS sniper B1: she applies an ATK debuff via
counter-based normal-attack stacks, accelerates her own burst when
Full Burst ends with a squadmate alive, and her burst grants the team
a small Max-HP-scaled shield.

**Source description (S1)**:

    Activates after landing 5 normal attack(s). Affects the target(s).
    ATK ▼ 7.95% for 5 sec.
    Activates when Full Burst ends with an ally from the same squad
    still on the battlefield. Affects self. Cooldown of Burst Skill ▼
    20.16 sec.

**Source description (S2)**:

    Affect self. Max HP ▲ 40.72% without restoring HP for 10 sec.
    Affect 2 allies with the lowest remaining HP. DEF ▲ 11.34% of
    caster's DEF for 5 sec.

**Source description (Burst)**:

    Affects all allies. Generates a Shield with 10.08% of the caster's
    final Max HP for 10 sec.
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
    character_name="Ram",
    skill1=(
        SkillEffect(
            description="Every 5 normal attacks: target ATK -7.95% for 5 sec.",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=7.95,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst end with squadmate alive: self burst "
                "cooldown -20.16 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_END,
                condition="squadmate from same squad still alive",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.16,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: self Max HP +40.72% (no heal) for 10 sec; "
                "2 lowest-HP allies DEF +11.34% of caster's DEF for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.72,
                    duration_seconds=10.0,
                    notes="'Max HP +X% without restoring HP'",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=2),
                    magnitude=11.34,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies get a shield equal to 10.08% of "
                "caster's Max HP for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.08,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Ram is a niche B1 SR with squad-conditional burst CD reset. "
        "Decent in mono-Abnormal comps where her squadmate trigger "
        "fires consistently."
    ),
)
register_character(_SKILL)
