"""Helm (Treasure) — B3 Water SR. Treasure-form Helm with Charge
Damage finisher.

Encoded from the live ``Character`` skill descriptions in the DB.
H(T) is a single-target SR carry — last-bullet team Crit, full-charge
team heal + gauge fill, FB entry +27.87% Attack Damage to allies, and
a massive 8236.8% burst on the highest-ATK enemy plus +158.4% Charge
Damage Multiplier for 10 rounds.

**Source description (S1)**:

    Last bullet hits target: all allies — Critical Rate of normal attacks
    +14.64% for 5s
    Full Charge: all allies recover 0.59% caster max HP + Burst Gauge +14.31%

**Source description (S2)**:

    All allies: Damage to Interruption Parts +3.08% (continuous)
    On entering Full Burst: all allies — Attack Damage +27.87% for 10s
    Full Charge hits target: target — 178.98% additional damage

**Source description (Burst)**:

    Highest-ATK enemy: 8236.8% of final ATK damage
    All allies: recover 54.45% of attack damage as HP for 10s
    Self: Charge Damage Multiplier +158.4% for 10 rounds
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
    character_name="Helm (Treasure)",
    skill1=(
        SkillEffect(
            description="Last bullet: allies Crit Rate +14.64% 5s",
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.64,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description="Full Charge: allies heal 0.59% caster max HP + Burst Gauge +14.31%",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full-charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.59,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.31,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Passive: allies +3.08% Damage to Interruption Parts",
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.08,
                    duration_seconds=999.0,
                ),
            ),
        ),
        SkillEffect(
            description="On FB entry: allies Attack Damage +27.87% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=27.87,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description="Full Charge hits: target 178.98% additional damage",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full-charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.7898,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: highest-ATK enemy 8236.8% + heal lifesteal + self Charge Dmg",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=82.368,
                    notes="targets highest-ATK; ENEMY_HIGHEST_HP as proxy",
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=54.45,
                    duration_seconds=10.0,
                    notes="lifesteal — 54.45% of attack damage as HP",
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=158.4,
                    duration_seconds=15.0,
                    notes="10 rounds — duration approx as 15s",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Treasure-form Helm — Water SR B3 single-target carry. "
        "8236.8% burst is one of the largest single-target nukes in "
        "the game. FB entry +27.87% Attack Damage applies to all "
        "allies; full-charge gauge gen helps the team rotate."
    ),
)
register_character(_SKILL)
