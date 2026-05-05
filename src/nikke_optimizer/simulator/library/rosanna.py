"""Rosanna — Electric MG B1, niche stealth-attacker / buff-stripper.

Encoded from the live ``Character`` skill descriptions. Rosanna has
"Concealment" (single-target-immunity) plus a Frenzy ATK stack that
piles up when allies fall. Niche on offense, decent self-buff baseline.

**Source description (S1)**:

    After 120 normal attacks: self Concealment for 10 sec. Crit Rate ▲
    19.34% for 10 sec.
    After 10 normal attacks: 2 highest-ATK enemies have 5 buffs
    dispelled (1 per battle).

**Source description (S2)**:

    Battle start: self Concealment for 5 sec.
    When ally falls: self Frenzy — ATK ▲ 22.61%, max 10 stacks, lasts
    30 sec. Fills Burst Gauge by 36.54%.

**Source description (Burst)**:

    Affects 2 Attacker enemies. 1310.4% of ATK as damage.
    Same targets if in Concealment: +561.6% additional damage.
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
    character_name="Rosanna",
    skill1=(
        SkillEffect(
            description=(
                "Every 120 normal attacks: self Concealment + Crit Rate "
                "+19.34% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=19.34,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 10 normal attacks: 2 highest-ATK enemies have 5 "
                "buffs dispelled (max 1 activation per battle)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=5.0,
                    notes="dispels 5 buffs; once-per-battle cap (DSL gap)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self Concealment for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=5.0,
                    notes="Concealment — single-target-immunity (DSL gap)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When an ally falls: self Frenzy — ATK +22.61% for 30 sec "
                "(max 10 stacks), gain 36.54% burst gauge."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any ally goes out of action",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=22.61,
                    duration_seconds=30.0,
                    stacks_max=10,
                ),
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=36.54,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 1310.4% ATK damage to 2 Attacker enemies; "
                "while in Concealment, +561.6% additional damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=13.104,
                    notes="filtered to Attacker enemies (DSL gap)",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric MG B1 — niche stealth attacker. Frenzy ATK stack "
        "kicks in only when allies fall, so she's a defensive comeback "
        "tool more than a steady-state buffer. Cleanse is rare in "
        "PvP; encoded but rarely impactful in practice."
    ),
)
register_character(_SKILL)
