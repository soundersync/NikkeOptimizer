"""Anis — B2 Iron RL Tetra defender. Counters squad's main story Anis.

Encoded from the live ``Character`` skill descriptions in the DB.
The base story Anis has a damage-share + DEF stack mechanic similar to
Bay (her squadmate), focused on absorbing damage off the team's
high-ATK members.

**Source description (S1)**:

    Activates when attacked 40 time(s). Affects self.
    DEF ▲ 120% for 10 sec.

**Source description (S2)**:

    Affects self and 2 allies with the highest ATK (except caster).
    DEF ▲ 80% for 5 sec. Shares damage taken for 10 sec.

**Source description (Burst)**:

    Affects all enemies within attack range.
    Deals 156.73% of final ATK as damage. DEF ▼ 32% for 5 sec.

**DSL gaps**:

  * Damage-share (same as Bay) — distinct mechanic, encoded as note.
  * "self and 2 allies (except caster)" target spec — DSL gap; encoded
    via composite of SELF + ALLY_HIGHEST_ATK with count=2.
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
    character_name="Anis",
    skill1=(
        SkillEffect(
            description=(
                "After being attacked 40 times: self DEF +120% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                cooldown_seconds=0.0,
                condition="40 hits taken (counter-based, not periodic)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=120.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Self + 2 highest-ATK allies (except self): DEF +80% "
                "for 5 sec, share damage taken for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=80.0,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=80.0,
                    duration_seconds=5.0,
                    notes=(
                        "ALSO 'shares damage taken' — DSL gap "
                        "(DAMAGE_SHARE), same as Bay."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: enemies in range take 156.73% of ATK + DEF -32% "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.5673,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=32.0,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Story-Anis (the base form) is a budget Bay-equivalent: damage "
        "share + DEF buffs to top-2 ATK allies. Useful when Bay isn't "
        "available."
    ),
)
register_character(_SKILL)
