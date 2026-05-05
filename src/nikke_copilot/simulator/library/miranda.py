"""Miranda — B1 Fire SMG. SMG-comp synergy supporter with single-target
ATK/Crit-Damage burst.

Encoded from the live ``Character`` skill descriptions in the DB.
Miranda's identity is the SMG-comp Hit Rate buff (S1 stacks with all
SMG allies), team Crit Damage on FB entry, and a focused single-ally
ATK + Crit Damage burst targeting the highest-ATK ally.

**Source description (S1)**:

    Every 30 normal hits: all allies Hit Rate +5.44% for 5s
    Every 30 normal hits: all SMG allies Hit Rate +3.79% for 5s

**Source description (S2)**:

    On FB entry: all allies Critical Damage +32.99% for 10s

**Source description (Burst)**:

    1 highest-ATK ally (except caster): ATK +40.4% for 10s
    Same: Critical Damage +56.23% for 10s
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
    character_name="Miranda",
    skill1=(
        SkillEffect(
            description="Every 30 hits: all allies Hit Rate +5.44% 5s",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=30),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.44,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SMG,
                    ),
                    magnitude=3.79,
                    duration_seconds=5.0,
                    notes="SMG allies get an extra +3.79% (stacks with the team-wide buff)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On FB entry: all allies Crit Damage +32.99% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=32.99,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: top-ATK ally ATK +40.4% + Crit Dmg +56.23% 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=40.4,
                    duration_seconds=10.0,
                    notes="excludes self — DSL gap",
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=56.23,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire SMG B1 budget supporter. Crit Damage focus + SMG-comp "
        "Hit Rate boost. Niche — largely out-tier'd by Liter / Tia "
        "in modern PvP."
    ),
)
register_character(_SKILL)
