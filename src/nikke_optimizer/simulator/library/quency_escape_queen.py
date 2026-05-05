"""Quency: Escape Queen — Water SMG B3, distributed-damage carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Quency:EQ has a multi-stage state machine ("Explore Route Stage 1/2/3")
that grants different self-buffs as her S2 stacks fill. We encode the
headline buffs at each stage; the staged progression is a DSL gap.

**Source description (S1)**:

    Activates only when Explore Route Stage 1 is fully stacked. Affects
    self. Distributed Damage ▲ 49.58% continuously.
    Activates only when Explore Route Stage 2 is fully stacked. Affects
    self. Damage dealt when attacking core ▲ 25.25% continuously.
    Activates only when Explore Route Stage 3 is fully stacked. Affects
    self. Critical Rate ▲ 16.73% continuously.

**Source description (S2)**:

    Activates after landing 2 normal attack(s). Effects self. Effects
    in each phase vary. Previous effects trigger repeatedly.
      Stage 1: Hit Rate ▲ 1.36%, ATK ▲ 2.45%, max 10 stacks, 2 sec.
      Stage 2 (after Stage 1 fully stacked): Hit Rate ▲ 2.71%, ATK ▲
      4.9%, max 10 stacks, 1 sec.
      Stage 3 (after Stage 2 fully stacked): Hit Rate ▲ 4.08%, ATK ▲
      8.16%, max 5 stacks.

**Source description (Burst)**:

    Affects self. Attack Damage ▲ 57.08% for 10 sec. Reloading Speed
    ▲ 25.87% for 10 sec.
    Affects all enemies. Deals 1736.31% of final ATK as Distributed
    Damage.
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
    character_name="Quency: Escape Queen",
    skill1=(
        SkillEffect(
            description=(
                "Stage 1 fully stacked: self Distributed Damage +49.58% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Explore Route Stage 1 fully stacked",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=49.58,
                    duration_seconds=86400.0,
                    notes=(
                        "actually 'Distributed Damage' (multi-target "
                        "explosion); encoded as pierce-damage proxy"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Stage 2 fully stacked: self core damage +25.25% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Explore Route Stage 2 fully stacked",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CORE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.25,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Stage 3 fully stacked: self Crit Rate +16.73% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Explore Route Stage 3 fully stacked",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=16.73,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 2 normal attacks: self gains a stage-specific "
                "ATK + Hit Rate stack. Stage 1: +2.45% ATK, max 10. "
                "Stage 2: +4.9% ATK, max 10. Stage 3: +8.16% ATK, max 5."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=2),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.45,
                    duration_seconds=2.0,
                    stacks_max=10,
                    notes=(
                        "Stage 1 magnitudes; stage-2/3 transitions are "
                        "a DSL gap. Encoded with stage-1 values."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.36,
                    duration_seconds=2.0,
                    stacks_max=10,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Attack Damage +57.08% and Reload Speed "
                "+25.87% for 10 sec; deals 1736.31% of ATK as Distributed "
                "Damage to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=57.08,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.87,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=17.3631,
                    notes=(
                        "actually 'Distributed Damage' (multi-target "
                        "explosion); encoded as ATK-channel for now"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SMG B3 — distributed-damage / multi-target carry. The "
        "stage progression is a DSL gap; stage-1 magnitudes are used "
        "as the encoded baseline. The simulator under-credits her "
        "endgame damage because stages 2-3 are not modeled."
    ),
)
register_character(_SKILL)
