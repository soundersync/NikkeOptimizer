"""Volume — B1 Wind SMG Tetra. Cumulative-activation crit-damage support.

Encoded from the live ``Character`` skill descriptions in the DB.
Volume's S2 mirrors Liter's S1 structure (cumulative-activation
effects across successive Full Burst windows). She slots into Crown
comps as an alternative B1 when Liter isn't available.

**Source description (S1)**:

    Affects self when killing an enemy. ATK ▲ 12.6% for 5 sec.

**Source description (S2)** — cumulative-activation, exact mirror of
Liter's S1 structure:

    Activates when entering Full Burst. Affects all allies.
    Effect changes according to the number of activation time(s).
    Previous effects triggers repeatedly.
        Once:        Burst Skill cooldown ▼ 2.34 sec.
        Twice:       Burst Skill cooldown ▼ 2.7 sec.
        Three times: Burst Skill cooldown ▼ 3.17 sec.

    Activates when using Burst Skill. Affects all allies.
    Effect changes according to the number of activation time(s).
    Previous effects triggers repeatedly.
        Once:        Critical Damage ▲ 10.77% for 5 sec.
        Twice:       Critical Damage ▲ 12.46% for 5 sec.
        Three times: Critical Damage ▲ 14.42% for 5 sec.

**Source description (Burst)**:

    Affects all allies. Critical Chance ▲ 31.59% for 5 sec.

**Encoding**: same pattern as Liter — encode the third-tier value as
the headline magnitude with a note about the cumulative scaling.
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
    character_name="Volume",
    skill1=(
        SkillEffect(
            description=(
                "On enemy kill: self ATK +12.6% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_KILL),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.6,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry: team burst CD reduction "
                "(third-tier 3.17 sec; cumulative 1st/2nd/3rd: 2.34/2.7/3.17)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                notes="effect scales with cumulative activation count",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.17,
                    notes="cumulative: 2.34 + 2.7 + 3.17 across 3 Full Bursts",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Volume's burst: team Crit Damage buff (third-tier "
                "14.42%; cumulative 10.77/12.46/14.42)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                notes="effect scales with cumulative activation count",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.42,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Critical Chance +31.59% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=31.59,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Volume is the alt-B1 for crit-leaning attack comps — her S2 + "
        "burst stack +14.42% Crit Damage and +31.59% Crit Rate, which "
        "pairs especially well with Modernia (whose S2 also stacks "
        "Crit Damage) and SW:HA's stacking ATK."
    ),
)
register_character(_SKILL)
