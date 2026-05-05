"""Leona — B2 Water SG Tetra. Shotgun-comp Roar buffer.

Encoded from the live ``Character`` skill descriptions in the DB. Leona's
identity is the Roar stacking system + shotgun-specific buffs — she
amplifies pellet count, hit rate, and crit for an all-SG team.

**Source description (S1)**:

    Activates after 5 normal attacks. Affects all allies.
    Roar: Critical Rate ▲ 2.62%, stacks up to 5 times and lasts for 5 sec.

    Activates after 15 normal attacks. Affects all allies with a Shotgun.
    Maximum Effective Range ▲ 20% for 10 sec.

**Source description (S2)**:

    Activates when entering Full Burst. Affects all allies.
    Hit Rate ▲ 20.28% for 10 sec.

    Activates when entering Full Burst. Affects 2 ally units with the
    highest ATK and a Shotgun. Increases number of pellets by 5 for 10 sec.

**Source description (Burst)**:

    Affects all allies. Critical Damage ▲ 34.64% for 10 sec.

    Activates when the caster's Roar is fully stacked. Affects all
    allies with a Shotgun. Critical Rate ▲ 21.32% for 10 sec.
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
    WeaponClass,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Leona",
    skill1=(
        SkillEffect(
            description=(
                "Every 5 normal attacks: all allies Roar Crit Rate "
                "+2.62% (stacks 5x, 5 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.62,
                    duration_seconds=5.0,
                    stacks_max=5,
                    notes="'Roar' stacking buff — burst gates on max stacks",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 15 normal attacks: all SG allies Max Range "
                "+20% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=15),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=20.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Max Effective Range +20%' on SG allies "
                        "— BUFF_HIT_RATE proxy (no RANGE kind in DSL)"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Hit Rate +20.28% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.28,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: 2 highest-ATK SG allies get "
                "+5 pellets for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALLY_HIGHEST_ATK,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually '+5 pellets' on 2 highest-ATK SG allies "
                        "— DSL has no PELLET_COUNT kind. 0-mag flag."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Crit Damage +34.64% for 10 sec; "
                "if Roar at max stacks, all SG allies Crit Rate "
                "+21.32% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=34.64,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=21.32,
                    duration_seconds=10.0,
                    notes="Roar-fully-stacked conditional — DSL no stack-state trigger",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Leona is the SG-comp specialist — pellet count, range, hit "
        "rate, and crit damage all stack on shotgun-leaning teams. "
        "Pairs natively with Anis: Sparkling Summer / Drake / Privaty: "
        "Unkind Maid (all SG-burst-stage carries)."
    ),
)
register_character(_SKILL)
