"""Mihara — B3 Water AR Missilis. Highway-to-Hell stacking carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Mihara's identity is the Highway-to-Hell state machine — first burst
grants HtH 1 (ATK +15.56% 45 sec), second burst grants HtH 2 (Crit Rate
+11.28% 45 sec). Burst extends Full Burst -5 sec (debuff!) but stacks
+266.4% AOE damage during HtH 2.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects self.
    Critical Damage ▲ 18.7% for 10 sec.

**Source description (S2)**:

    Activates when using Burst Skill. Affects self.
    Highway to Hell 1: ATK ▲ 15.56% for 45 sec.

    Activates when using Burst Skill during Highway to Hell 1.
    Affects self. Highway to Hell 2: Critical Rate ▲ 11.28% for 45 sec.

**Source description (Burst)**:

    Affects all allies. Full Burst Time ▼ 5 sec.

    Affects all enemies. Deals 399.6% of final ATK as damage.

    Activates during Highway to Hell 2. Affects all enemies.
    Deals 266.4% of final ATK as additional damage.
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
    character_name="Mihara",
    skill1=(
        SkillEffect(
            description=(
                "On last bullet: self Crit Damage +18.7% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=18.7,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On burst use: self Highway to Hell 1 — ATK +15.56% "
                "for 45 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="not in HtH state",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.56,
                    duration_seconds=45.0,
                    notes="'Highway to Hell 1' state — gates HtH 2",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use during HtH 1: self HtH 2 — Crit Rate "
                "+11.28% for 45 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="in Highway to Hell 1",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=11.28,
                    duration_seconds=45.0,
                    notes="'Highway to Hell 2' state — gates burst bonus",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Full Burst -5 sec (DEBUFF); all "
                "enemies take 399.6% of ATK; during HtH 2, +266.4% "
                "additional."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    notes=(
                        "actually 'Full Burst Time -5 sec' — a DEBUFF, "
                        "not a buff. DSL has no FULL_BURST_TIME_REDUCE "
                        "kind. 0-mag with note flag — Mihara shortens "
                        "the team's burst window to extend her own AR rotation."
                    ),
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.996,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.664,
                    notes=(
                        "Highway to Hell 2 conditional bonus — DSL has "
                        "no state-machine triggers; encoded as second "
                        "damage instance with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Mihara is a 2-burst-cycle stacker — first burst sets HtH 1 "
        "(ATK), second burst escalates to HtH 2 (Crit Rate + 266.4% "
        "AOE bonus). Her FB Time -5 sec is a tradeoff: longer burst "
        "rotations for her, shorter Full Burst for the team."
    ),
)
register_character(_SKILL)
