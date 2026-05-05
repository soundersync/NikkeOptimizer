"""Jackal — B1 Iron RL Missilis. Single-target burst-DR amplifier.

Encoded from the live ``Character`` skill descriptions in the DB. Jackal's
identity is the burst-skill damage amplifier on her own burst — any
ally with "Affects 1 enemy unit" in their description deals +38.91%
extra damage. Pairs natively with Maiden: Ice Rose, Modernia, Helm,
and other single-target nukers.

**Source description (S1)**:

    Activates when attacked 10 time(s). Affects 1 enemy unit with the
    highest Max HP. Damage Taken ▲ 9.09% for 10 sec. ATK ▼ 9.09% for
    10 sec.

**Source description (S2)**:

    Activates when entering battle. Affects self and 2 ally unit(s)
    with the highest ATK. Shares damage taken for 120 sec.
    DEF ▲ 8.27% for 120 sec.

**Source description (Burst)**:

    Affects all allies. Burst Skill damage of skills with "Affects 1
    enemy unit(s)" in the description ▲ 38.91% for 15 sec.
    DEF ▲ 14.69% for 10 sec.
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
    character_name="Jackal",
    skill1=(
        SkillEffect(
            description=(
                "Every 10 hits taken: highest-HP enemy takes "
                "+9.09% damage and -9.09% ATK for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_DAMAGE_TAKEN, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=9.09,
                    duration_seconds=10.0,
                    notes="'Damage Taken +9.09%' — DEBUFF_DEFENSE proxy",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=9.09,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self + 2 highest-ATK allies share damage "
                "taken and gain DEF +8.27% for 120 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=8.27,
                    duration_seconds=120.0,
                    notes="self + 2 highest-ATK allies (3 total)",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=0.0,
                    duration_seconds=120.0,
                    notes=(
                        "actually 'shares damage taken for 120 sec' — "
                        "no SHARE_DAMAGE effect kind. Captured as "
                        "0-mag BUFF_DEFENSE with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies' single-target burst skills deal "
                "+38.91% damage for 15 sec; DEF +14.69% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_BURST_SKILL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=38.91,
                    duration_seconds=15.0,
                    notes=(
                        "applies only to 'Affects 1 enemy unit' burst "
                        "skills — DSL has no per-burst-target filter; "
                        "simulator must inspect each ally's burst spec"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.69,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Jackal is the rare B1 single-target-burst amplifier. Her burst "
        "boosts any ally whose skill says 'Affects 1 enemy unit' (Maiden: "
        "Ice Rose's nuke, Helm's nuke, Modernia's S2). Pairs natively "
        "with the burst-stage-1 MP-charge plays."
    ),
)
register_character(_SKILL)
