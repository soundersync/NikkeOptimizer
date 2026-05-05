"""Raven — Iron RL B3, sustained-damage carry with parts focus.

Encoded from the live ``Character`` skill descriptions. Raven's
gameplay loop centers on Full Charge attacks that stack a sustained
DoT, plus an "A.N. Mode" state on burst that boosts that DoT.

**Source description (S1)**:

    Activates when performing Full Charge attacks. Affects 1 enemy
    unit nearest to the crosshair. Deals 68.46% of final ATK as
    sustained damage every 1 sec, stacks up to 10 time(s) and lasts
    for 5 sec.
    Activates when entering Full Burst. Affects self. ATK ▲ 47.52%
    of caster's ATK for 10 sec.

**Source description (S2)**:

    Activates when entering battle. Affects self. Vital Attack:
    Damage to Parts ▲ 21.12% for 5 sec.
    Activates when entering Full Burst. Affects self. Vital Attack:
    Damage to Parts ▲ 21.12% for 5 sec.
    Activates when an ally or self destroys an enemy's part. Affects
    self if not in A.N.Mode. Single Point Attack: Sustained damage ▲
    47.32% for 15 sec. Removes Vital Attack.

**Source description (Burst)**:

    Affects all enemies (including parts). Deals 492.3% of final ATK
    as Burst Skill damage.
    Affects self. A.N. Mode: Removes Single Point Attack. Sustained
    damage ▲ 89.44% for 10 sec.
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
    character_name="Raven",
    skill1=(
        SkillEffect(
            description=(
                "Full Charge attack: nearest enemy takes 68.46% ATK as "
                "sustained damage every 1 sec, max 10 stacks, 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.6846,
                    duration_seconds=5.0,
                    stacks_max=10,
                    notes="sustained DoT, 1/sec ticks (DSL gap on tick rate)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst entry: self ATK +47.52% of caster's ATK "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=47.52,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self Vital Attack — Damage to Parts +21.12% "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.12,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst entry: self Vital Attack — Damage to Parts "
                "+21.12% for 5 sec (refreshes)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.12,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When ally or self destroys part (and self not in A.N. "
                "Mode): self Single Point Attack — Sustained Damage "
                "+47.32% for 15 sec. Removes Vital Attack."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ally/self destroys enemy part (Single Point Attack)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=47.32,
                    duration_seconds=15.0,
                    notes="state-machine: removes Vital Attack (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 492.3% ATK Burst-Skill damage to all enemies "
                "(including parts); self enters A.N. Mode (Sustained "
                "Damage +89.44% for 10 sec, removes Single Point Attack)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.923,
                ),
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=89.44,
                    duration_seconds=10.0,
                    notes="A.N. Mode state — removes Single Point Attack",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron RL B3 — sustained-damage / parts-focused carry. The "
        "Vital Attack ↔ Single Point Attack ↔ A.N. Mode state machine "
        "is encoded as separate triggers; the simulator under-credits "
        "her until state-machine support lands."
    ),
)
register_character(_SKILL)
