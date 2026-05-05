"""Liter — B1 Iron SMG support, Missilis. Cooldown-reduction burst-gen.

Encoded from the live ``Character.skill1_description`` /
``skill2_description`` / ``burst_description`` fields scraped from
Prydwen. Refer to those fields for the canonical text — this DSL
translation aims to preserve the structural mechanics.

**Source description (S1)**:

    Activates when entering Full Burst. Affects all allies. Effect
    changes according to the activation time(s). Previous effects
    triggers repeatedly.
        Once:        Cooldown of Burst Skill ▼ 2.34 sec.
        Twice:       Cooldown of Burst Skill ▼ 2.7 sec.
        Three times: Cooldown of Burst Skill ▼ 3.17 sec.

    Activates when using Burst Skill. Affects all allies. Effect
    changes according to the activation time(s). Previous effects
    triggers repeatedly.
        Once:        Max Ammunition Capacity ▲ 45.17% for 5 sec.
        Twice:       Critical Damage ▲ 12.46% for 5 sec.
        Three times: ATK ▲ 14.42% for 5 sec.

**Source description (S2)**:

    Affects 2 ally unit(s) with the lowest cover HP.
    Cover's HP recovers by 52.5%.

**Source description (Burst)**:

    Affects all allies. ATK ▲ 66% for 5 sec.

The "activation time(s)" mechanic is encoded as the THIRD activation
only — the description says previous effects also trigger repeatedly,
so by the third Full Burst the team has the full stack. Earlier Full
Bursts only trigger the lower-tier effects; the simulator will apply
the per-activation logic when it implements stateful triggers.
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
    character_name="Liter",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: reduce burst-skill cooldown for all "
                "allies (3.17 sec at the third activation; previous effects "
                "trigger repeatedly so the team accumulates full reduction)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                notes="effect scales with cumulative activation count (1st/2nd/3rd)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.17,  # seconds — third-activation tier
                    notes="cumulative: 2.34 + 2.7 + 3.17 across 3 Full Bursts",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Liter's burst use: ally team gets stacking buffs — "
                "ammo capacity, then crit damage, then ATK across "
                "successive activations."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                notes="effect scales with cumulative activation count (1st/2nd/3rd)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=45.17,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=12.46,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.42,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Cover-heal the 2 allies with the lowest cover HP. "
                "Always-on; this is the ambient heal pulse, not a "
                "triggered effect."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=2),
                    magnitude=52.5,
                    notes="cover HP, not character HP — distinct mechanic",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "All allies gain ATK ▲ 66% for 5 sec. The canonical "
                "B1 burst-gen ATK swing — paired with her S1 burst-cooldown "
                "loop, this is what enables fast team rotations."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=66.0,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Liter's value comes from the S1+Burst combo: her burst applies a "
        "team ATK buff while S1 reduces everyone's burst cooldown, "
        "enabling double-burst rotations within a single PvP match."
    ),
)
register_character(_SKILL)
