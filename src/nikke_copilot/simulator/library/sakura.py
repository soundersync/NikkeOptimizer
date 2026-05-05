"""Sakura — B1 Fire SR Tetra. DEF-stacking team supporter.

Encoded from the live ``Character`` skill descriptions in the DB.
Sakura's signature is the Cherry Blossom Tea stacking DEF buff
(+8.15% × 10 stacks = +81.5% team DEF) plus her unique anti-Wind
damage-reduction burst (90.72% reduction, once per battle).

**Source description (S1)**:

    Activates after 3 normal attack(s). Affects all allies.
    Cherry Blossom Tea: 8.15% of DEF, stacks up to 10 time(s) and lasts for 15 sec.

**Source description (S2)**:

    Affects all allies. When attacking an enemy projectile, damage to
    that projectile ▲ 7.74% permanently.

    Activates when entering Full Burst. Affects all allies.
    Burst Skill cooldown ▼ 4.84 sec.

**Source description (Burst)**:

    Affects all allies. Damage dealt by Wind code enemies ▼ 90.72%,
    lasts for 30 sec. Activates 1 time(s) per battle.
    ATK ▲ 23.76% of caster's ATK, lasts for 10 sec.

    Affects all allies when Cherry Blossom Tea is fully stacked.
    Damage to interruption part ▲ 23.54%, lasts for 30 sec.
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
    character_name="Sakura",
    skill1=(
        SkillEffect(
            description=(
                "Every 3 normal attacks: all allies gain Cherry Blossom "
                "Tea stack (+8.15% DEF, max 10, 15 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=3),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=8.15,
                    duration_seconds=15.0,
                    stacks_max=10,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies burst CD -4.84 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=4.84,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies anti-Wind damage taken -90.72% (30s, "
                "1×battle), plus all allies ATK +23.76% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=90.72,
                    duration_seconds=30.0,
                    notes=(
                        "actually 'Damage dealt by Wind code enemies "
                        "-90.72%' — element-conditional damage taken "
                        "reduction. 1× per battle. DSL gap."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=23.76,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Burst, when Cherry Blossom Tea is fully stacked: all "
                "allies 'Damage to interruption part' +23.54% (30s, "
                "PvE-only)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Cherry Blossom Tea at 10 stacks (max)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=23.54,
                    duration_seconds=30.0,
                    notes="'Damage to interruption part' — PvE-only",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Sakura's anti-Wind 90.72% damage reduction (1× per battle) is "
        "a unique counter to Wind-element attack comps (e.g. SBS, "
        "Asuka). Pair with Wind-meta opponents and her S1 DEF stacks "
        "make the team near-invulnerable to that match-up."
    ),
)
register_character(_SKILL)
