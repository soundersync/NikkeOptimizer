"""Snow Crane — B2 Water SR Pilgrim. HP-scaling support / shielder
with team Pierce conversion on burst.

Encoded from the live ``Character`` skill descriptions in the DB.
SC's identity is HP scaling: she grants all allies the ``Exclusive
Recovery Agreement`` buff (Max HP +10% of caster's max HP) and a
team shield on Full Burst entry. The ``Proof of Violation`` /
``Terminated Contract`` chain is a self-resilience switch — at 3
stacks of incoming-heal-induced violation she becomes immune and
self-heals 0.24%/sec. Burst is a flat team heal + self Pierce.

**Source description (S1)**:

    While not Terminated Contract: all allies — Exclusive Recovery
    Agreement: Max HP +10% of caster's max HP (continuous)

    On non-self recovery: self Proof of Violation: HP recovery
    potency -10% (continuous, max 3 stacks)

**Source description (S2)**:

    After 3 Full Charge attacks: allies in Exclusive Recovery
    Agreement — recover 1.32% of caster's final max HP

    On entering Full Burst: all allies — shield 9.5% of caster's
    final max HP for 10s

    On Proof of Violation max stacks: self — Terminated Contract:
    immune to Proof of Violation, recover 0.24% of caster's final
    max HP per 1s (continuous)

**Source description (Burst)**:

    All allies — recover 44.68% of caster's final max HP
    Self — gain Pierce for 10s
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
    character_name="Snow Crane",
    skill1=(
        SkillEffect(
            description="All allies: Max HP +10% of caster's max HP (continuous)",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                condition="not in Terminated Contract status",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.0,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="Exclusive Recovery Agreement",
                ),
            ),
        ),
        SkillEffect(
            description="On non-self recovery: self Proof of Violation -10% recovery (max 3)",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="recovery from another ally takes effect",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=10.0,
                    duration_seconds=999.0,
                    stacks_max=3,
                    notes=(
                        "Proof of Violation: HP recovery potency -10%. "
                        "DSL gap (HEAL_RECEIVED debuff); captured as "
                        "DEBUFF_DEFENSE for stacking accountancy."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Every 3 full-charge hits: ERA allies +1.32% caster max HP",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=3,
                notes="full-charge attacks only (SR mechanic)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.32,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="targets allies in Exclusive Recovery Agreement",
                ),
            ),
        ),
        SkillEffect(
            description="On Full Burst entry: all allies shield 9.5% caster max HP 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=9.5,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
        SkillEffect(
            description="At Proof of Violation max: self Terminated Contract (immunity + regen)",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Proof of Violation at 3 stacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.24,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes=(
                        "Terminated Contract: 0.24% caster max HP / 1s + "
                        "immunity to Proof of Violation. Immunity is a "
                        "DSL gap."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies recover 44.68% caster max HP + self Pierce 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=44.68,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SR B2 Pilgrim. HP-scaling team support: Max HP buff + "
        "Full Burst shield + flat heal burst. Pairs well with HP-scaling "
        "attackers (Maiden: Ice Rose, etc.) since her ERA buff is large."
    ),
)
register_character(_SKILL)
