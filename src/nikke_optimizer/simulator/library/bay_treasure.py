"""Bay (Treasure) — B2 Fire RL Tetra. Treasure-form Bay with cover rebuild.

Encoded from the live ``Character`` skill descriptions in the DB. The
Treasure form keeps Bay's damage-share core but adds: passive cover
heal on Full Charge, cover rebuild on B1 entry if destroyed, and a
1×battle cover-rebuild burst clause.

**Source description (S1)**:

    Activates when using Burst Skill, only if self is alive. Affects
    all allies. Proportionally shares damage taken continuously.
    DEF ▲ 10.13% of caster's DEF continuously.

    Activates when performing Full Charge attacks. Affects all allies
    (except self). Recovers 4% of caster's final Max HP.

**Source description (S2)**:

    Activates when using Burst Skill, only if self is alive. Affects
    self's cover. Proportionally shares damage taken continuously.

    Activates when Full Burst ends. Affects self.
    Continuously recovers Cover's HP equal to 2.88% of caster's final
    Max HP every 1 sec for 5 sec.

    Activates when entering Burst Stage 1 and self's cover has been
    destroyed. Affects self. Recovers 20% of caster's final Max HP.

**Source description (Burst)**:

    Affects self if self's cover has been destroyed. Rebuild Cover
    with 20% HP. Activates once per battle.

    Affects self. Max HP of Cover ▲ 18% of caster's Max HP for 20 sec.

    Affects all allies. Damage Taken ▼ 8.87% for 10 sec.
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
    character_name="Bay (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "Post-burst: all allies share damage taken + DEF +10.13%."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Bay survives the burst cast",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.13,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                    notes="ALSO 'damage share' — DSL gap",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge attack: all allies (except self) recover "
                "4% of Bay's max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=4.0,
                    notes="actually 'all allies except self' — DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst end: self cover-HP regen 2.88%/sec for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.88,
                    duration_seconds=5.0,
                    notes="cover HP recovery (drives Tia/Naga loop)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On B1 entry with cover destroyed: self recovers 20% of "
                "max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="entering Burst Stage 1 with cover destroyed",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: rebuilds destroyed cover at 20% HP (1×battle), "
                "self Cover Max HP +18% (20s), all allies Damage Taken "
                "-8.87% (10s)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=18.0,
                    duration_seconds=20.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="Cover Max HP +18% of caster's Max HP",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=8.87,
                    duration_seconds=10.0,
                    notes="actually 'Damage Taken -8.87%'",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Bay (Treasure) is the Champion-tier upgrade — adds passive "
        "Full-Charge cover heal + cover rebuild on B1 entry, making "
        "her near-immortal in extended fights."
    ),
)
register_character(_SKILL)
