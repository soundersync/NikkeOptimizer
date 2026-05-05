"""Soda: Twinkling Bunny — B3 Iron SG Pilgrim. Stack-based attacker
with Full Burst Time extension.

Encoded from the live ``Character`` skill descriptions in the DB.
S:TB's identity is Golden Chip stacking (max 50): she accumulates
crit-damage stacks during Full Burst, then her S2 extends Full Burst
Time by 2-3s once she hits stack thresholds (10 / 20). The burst
both clears damage and self-buffs ATK / Hit Rate based on stack
count.

**Source description (S1)**:

    At battle start: self Golden Chip stacks +50.
    Every 3 normal attacks during Full Burst Time:
      self Golden Chip: Crit Damage +1.32% per stack (max 50)
      self + 1 highest-ATK ally (except self): Attack Damage +10.51% for 2 sec

**Source description (S2)**:

    On entering Burst Stage 3: all allies
      Stage 1 (Golden Chip ≥10): Time Extension I — FBT Duration +2s during FBT
      Stage 2 (Golden Chip ≥20): Time Extension II — FBT Duration +3s during FBT
    On normal attack during FBT: nearest enemy
      Stage 1: 52.04% of final ATK
      Stage 2: 85.02% of final ATK

**Source description (Burst)**:

    Onward, Soda! (Stage cascades, Golden Chip -17 after)
      Stage 1: all enemies — 628.7% of final ATK damage
      Stage 2 (chips ≥20): self Hit Rate +38.91% for 15s
      Stage 3 (chips ≥30): self ATK +65.25% for 15s
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
    character_name="Soda: Twinkling Bunny",
    skill1=(
        SkillEffect(
            description="At battle start: self Golden Chip stacks +50",
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.32 * 50,  # 50 stacks pre-loaded at start
                    duration_seconds=999.0,
                    stacks_max=50,
                    notes="Golden Chip pre-loaded; permanent until consumed by burst",
                ),
            ),
        ),
        SkillEffect(
            description="Every 3 normal hits in FBT: Golden Chip +1.32% crit dmg",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=3,
                condition="during Full Burst Time",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.32,
                    duration_seconds=999.0,
                    stacks_max=50,
                ),
            ),
        ),
        SkillEffect(
            description="Every 3 normal hits in FBT: self + top-ATK ally +10.51% attack dmg 2s",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=3,
                condition="during Full Burst Time",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=10.51,
                    duration_seconds=2.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=10.51,
                    duration_seconds=2.0,
                    notes="excludes self — DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Burst Stage 3 entry: Time Extension I (chips ≥10) +2s FBT",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Golden Chip stacks ≥ 10",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=2.0,
                    notes="actually FBT extension +2s; DSL gap (FB_TIME_EXT)",
                ),
            ),
        ),
        SkillEffect(
            description="Burst Stage 3 entry: Time Extension II (chips ≥20) +3s FBT",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Golden Chip stacks ≥ 20",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=3.0,
                    notes="actually FBT extension +3s; supersedes Stage 1",
                ),
            ),
        ),
        SkillEffect(
            description="Normal attack in FBT (Time Ext I): nearest enemy 52.04% damage",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="during FBT, Time Extension I active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.5204,
                ),
            ),
        ),
        SkillEffect(
            description="Normal attack in FBT (Time Ext II): nearest enemy 85.02% damage",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="during FBT, Time Extension II active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.8502,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst Stage 1: all enemies 628.7% damage",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=6.287,
                ),
            ),
        ),
        SkillEffect(
            description="Burst Stage 2 (chips ≥20): self Hit Rate +38.91% 15s",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Golden Chip stacks ≥ 20",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=38.91,
                    duration_seconds=15.0,
                ),
            ),
        ),
        SkillEffect(
            description="Burst Stage 3 (chips ≥30): self ATK +65.25% 15s",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Golden Chip stacks ≥ 30",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=65.25,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SG B3 stack-attacker. Self-loops crit damage stacks during "
        "FBT and extends FBT itself by 2-3s once she hits 10/20 chips. "
        "Strongest in long-burst comps where her FBT extension can chain."
    ),
)
register_character(_SKILL)
