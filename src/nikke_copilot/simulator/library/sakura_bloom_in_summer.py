"""Sakura: Bloom in Summer — B3 Wind AR. Sustained-damage attacker
keyed on parts destruction.

Encoded from the live ``Character`` skill descriptions in the DB.
S:BiS leans on parts destruction to extend her two named buffs:
``Dancing Flower`` (self attack-damage amp) and ``Sakura Petals``
(target sustained DOT). Her S1 force-casts S2 at battle start so the
buffs apply immediately. Burst is a 10-hit AOE plus a stacking DOT
on the same targets.

**Source description (S1)**:

    On battle start: forcefully cast Skill 2

    On ally/self destroying enemy part:
      self Sustained Damage +5.1% for 30s
      self Dancing Flower duration +10.02s
      enemies in Sakura Petals: Sakura Petals duration +10.02s

**Source description (S2)**:

    self Dancing Flower: Attack Damage +15.64% for 15s
    enemy with highest ATK: Sakura Petals — 256% / 1s sustained for 15s

**Source description (Burst)**:

    Random enemies — 457.14% × 10 sequential
    Same target — 35.16% / 1s sustained, max 10 stacks, 10s
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
    character_name="Sakura: Bloom in Summer",
    skill1=(
        SkillEffect(
            description="At battle start: force-cast Skill 2 (apply Dancing Flower + Sakura Petals)",
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.64,
                    duration_seconds=15.0,
                    notes="Dancing Flower (forced from S2 at start)",
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=2.56,
                    duration_seconds=15.0,
                    notes=(
                        "Sakura Petals: 256% / 1s sustained, target highest-ATK "
                        "enemy. ENEMY_HIGHEST_HP used as proxy — DSL has no "
                        "ENEMY_HIGHEST_ATK kind."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description="Part destroyed: self Sustained Damage +5.1% 30s",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ally or self destroys an enemy's part",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=5.1,
                    duration_seconds=30.0,
                ),
            ),
        ),
        SkillEffect(
            description="Part destroyed: self Dancing Flower duration +10.02s",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ally or self destroys an enemy's part; Dancing Flower active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.64,
                    duration_seconds=10.02,
                    notes="Dancing Flower duration extension; refreshed on parts kill",
                ),
            ),
        ),
        SkillEffect(
            description="Part destroyed: Sakura Petals duration +10.02s",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ally or self destroys an enemy's part; Sakura Petals active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.56,
                    duration_seconds=10.02,
                    notes="Sakura Petals duration extension; refreshed on parts kill",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="self Dancing Flower: Attack Damage +15.64% 15s",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="S2's own cooldown timer; force-cast at battle start",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.64,
                    duration_seconds=15.0,
                ),
            ),
        ),
        SkillEffect(
            description="Highest-ATK enemy: Sakura Petals 256% / 1s sustained 15s",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="S2 ticks; targets highest-ATK enemy",
            ),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=2.56,
                    duration_seconds=15.0,
                    notes="ENEMY_HIGHEST_HP as proxy for highest-ATK (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: random enemies 457.14% × 10 sequential",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=4.5714,
                    notes="10 sequential hits at 457.14% each",
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=0.3516,
                    duration_seconds=10.0,
                    stacks_max=10,
                    notes="35.16% / 1s sustained, max 10 stacks, 10s",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind AR B3 sustained-damage attacker. Best in PvE / boss fights "
        "with destructible parts; PvP value gated by part-destruction "
        "trigger frequency. Force-cast S2 at battle start gives instant "
        "Dancing Flower up-time."
    ),
)
register_character(_SKILL)
