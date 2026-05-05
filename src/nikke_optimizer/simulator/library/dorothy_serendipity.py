"""Dorothy: Serendipity — B3 Water SG. Pierce-attacker variant.

Encoded from the live ``Character`` skill descriptions in the DB.
D:S is a SG-form Pierce attacker — every 80 pellets she gains Pierce,
+98.18% Hit Rate, and +72% Attack Damage for 3 rounds (with pellet
count fixed to 1, turning her single-shot Pierce-style). Burst
self-empowers ATK + attack speed + +5 pellet count.

**Source description (S1)**:

    Every 80 pellets hit: self gains Pierce 3 rounds, Hit Rate +98.18%
    3 rounds, Attack Damage +72% 3 rounds, Pellet count fixed at 1
    Every 160 pellets hit: self Pierce range +200% for 3 rounds

**Source description (S2)**:

    On battle start: self Pierce damage +55.08% (continuous)
    During Full Burst only: self ATK +75.24%, Hit Rate +40.68% (continuous)

**Source description (Burst)**:

    Self: Attack Speed +65% for 15s
    Self: ATK +88.12% for 15s
    Self: Pellet count +5 for 15s
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
    character_name="Dorothy: Serendipity",
    skill1=(
        SkillEffect(
            description="Every 80 pellets: self Pierce + Hit Rate + Attack Damage 3 rounds",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=80,
                notes="pellet count, not normal-attack count",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=15.0,
                    notes="3 rounds — duration approximated as 15s",
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=98.18,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=72.0,
                    duration_seconds=15.0,
                ),
            ),
        ),
        SkillEffect(
            description="Every 160 pellets: self Pierce range +200% 3 rounds",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=160,
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=200.0,
                    duration_seconds=15.0,
                    notes="Pierce range expansion — captured as pierce-dmg amp",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="At battle start: self Pierce damage +55.08% (continuous)",
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=55.08,
                    duration_seconds=999.0,
                ),
            ),
        ),
        SkillEffect(
            description="During FB only: self ATK +75.24%, Hit Rate +40.68%",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                notes="active during FB window only",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=75.24,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.68,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: self Attack Speed +65%, ATK +88.12%, Pellet +5 (15s)",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=88.12,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=65.0,
                    duration_seconds=15.0,
                    notes="actually Attack Speed +65% — DSL gap (ATK_SPEED)",
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=500.0,
                    duration_seconds=15.0,
                    notes="Pellet count +5 — captured as ammo-capacity boost",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SG B3 self-carry. Pierce-stack mechanic at 80 pellets "
        "transforms her into a single-shot Pierce attacker. Strong vs "
        "shielded / cover-heavy comps; pairs naturally with Anchor S2 "
        "and SG-comp anchors (Drake (Treasure))."
    ),
)
register_character(_SKILL)
