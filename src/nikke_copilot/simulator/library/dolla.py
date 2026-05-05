"""Dolla — B2 Wind SR Pilgrim. Burst-CD-reduction supporter with
escalating per-cast crit/atk buffs.

Encoded from the live ``Character`` skill descriptions in the DB.
Dolla's identity is the "Three-cast escalation": each successive
Full Burst entry deepens her cooldown reduction and her on-burst
team buff cycles through ATK → Crit Rate → Crit Damage. Pairs
strongly with B3 attackers that scale on those three stats (Red Hood,
SBS, etc.).

**Source description (S1)**:

    All allies: ATK +16.16% for 5 sec

**Source description (S2)**:

    On entering Full Burst, escalates per cast:
      1st: all allies Burst Skill Cooldown -1.82 sec
      2nd: all allies Burst Skill Cooldown -2.2 sec
      3rd: all allies Burst Skill Cooldown -2.6 sec

    On using Burst, escalates per cast:
      1st: all allies ATK +7.72% for 5 sec
      2nd: all allies Critical Rate +4.21% for 5 sec
      3rd: all allies Critical Damage +13.22% for 5 sec

**Source description (Burst)**:

    Highest-DEF enemy: 734.69% of final ATK damage
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
    character_name="Dolla",
    skill1=(
        SkillEffect(
            description="All allies: ATK +16.16% for 5s (passive ticker)",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="S1 ticks on its own cooldown",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=16.16,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="FB entry, 1st cast: allies Burst CD -1.82s",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="1st activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.82,
                ),
            ),
        ),
        SkillEffect(
            description="FB entry, 2nd cast: allies Burst CD -2.2s",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="2nd activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.2,
                ),
            ),
        ),
        SkillEffect(
            description="FB entry, 3rd cast: allies Burst CD -2.6s",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="3rd activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.6,
                ),
            ),
        ),
        SkillEffect(
            description="On burst, 1st: allies ATK +7.72% 5s",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="1st activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.72,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description="On burst, 2nd: allies Crit Rate +4.21% 5s",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="2nd activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=4.21,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description="On burst, 3rd: allies Crit Damage +13.22% 5s",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="3rd activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=13.22,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: highest-DEF enemy 734.69% damage",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=7.3469,
                    notes=(
                        "Targets highest-DEF — DSL has no ENEMY_HIGHEST_DEF, "
                        "ENEMY_HIGHEST_HP used as proxy for tank-finder."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SR B2 supporter. Each successive FB entry / burst use "
        "deepens team Burst CD reduction and rotates between ATK → "
        "Crit Rate → Crit Damage. Pairs with crit-scaling B3s — Red "
        "Hood, SBS, Maxwell — and B3s that benefit from CD compression."
    ),
)
register_character(_SKILL)
