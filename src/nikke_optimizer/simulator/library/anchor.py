"""Anchor — B1 Wind RL Elysion defender/taunter.

Encoded from the live ``Character`` skill descriptions in the DB. A
compact kit centered on her S1 last-bullet taunt + DEF self-buff and a
straightforward AOE burst. Often the B1 in stall comps when Liter / Tia
aren't available.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects the target.
    Taunt for 5 sec.

    Activates when the last bullet hits the target. Affects self.
    DEF ▲ 23.82% for 5 sec.

**Source description (S2)**:

    Activates when entering battle. Affects self. When attacking an
    enemy projectile, damage dealt to that projectile ▲ 25.6% continuously.

**Source description (Burst)**:

    Affects all enemies. Deal 304.45% of final ATK as damage.

**DSL gaps**:

  * "Damage dealt to projectiles" — PvE-only stat. Encoded as a note.
  * Single-target taunt on a non-self target — same gap as Noah S2.
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
    character_name="Anchor",
    skill1=(
        SkillEffect(
            description=(
                "On firing the magazine's last bullet: target taunted "
                "for 5 sec; self DEF +23.82% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.0,
                    duration_seconds=5.0,
                    notes="single-target taunt on the enemy hit",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=23.82,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On battle start: self 'damage to enemy projectiles' "
                "+25.6% continuously (PvE-only stat — irrelevant in PvP)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes=(
                        "actually 'damage to enemy projectiles +25.6%' — "
                        "PvE-only mechanic, no effect in PvP"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: deals 304.45% of ATK to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.0445,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Anchor is a budget B1 defender — single-target taunt + self "
        "DEF buff on last bullet, plus a simple AOE burst. Useful as "
        "the B1 slot in stall comps that don't have access to Liter "
        "or Tia."
    ),
)
register_character(_SKILL)
