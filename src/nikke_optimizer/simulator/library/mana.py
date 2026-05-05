"""Mana — Wind AR B3, dual-state (Metal y / Metal o) carry.

Encoded from the live ``Character`` skill descriptions. Mana toggles
between Metal y (offensive ATK + heal-on-attack) and Metal o (burst-
gauge fill + ATK on burst). State machine is a DSL gap noted inline.

**Source description (S1)**:

    Activates at the start of the battle. Affects self. Metal y:
    ATK ▲ 58.08% continuously. Activates once per battle.
    Activates in Metal y status after 10 normal attacks. Affects all
    allies. Recovers 2.04% of caster's final Max HP.
    Activates if caster in Metal y when ally is out of action.
    Affects 1 incapacitated ally with highest ATK. Resurrect with 96% HP.
    Activates when ally is out of action. Affects self. Removes Metal y.

**Source description (S2)**:

    Battle start. Affects self. Metal o: Burst Gauge filling speed
    ▲ 70.4% continuously.
    On Full Burst entry while in Metal o: self Attack Damage ▲ 21.12%
    + ATK ▲ 63.36% for 10 sec. Removes Metal o.
    On Full Burst entry: ally with longest Charge Time gets Charge
    Time -0.18 sec for 10 sec.

**Source description (Burst)**:

    Affects self. Sustained Damage ▲ 52.8% for 10 sec.
    Affects nearest enemy. 396% of ATK as sustained damage / sec for 10 sec.
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
    character_name="Mana",
    skill1=(
        SkillEffect(
            description=(
                "Battle start (Metal y, once per battle): self ATK +58.08% "
                "continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=58.08,
                    duration_seconds=86400.0,
                    notes="Metal y state — removed when ally goes down (DSL gap)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 10 normal attacks while in Metal y: all allies "
                "recover 2.04% of caster's Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=2.04,
                    notes="Metal y state required (DSL gap)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start (Metal o): self Burst Gauge fill speed "
                "+70.4% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=70.4,
                    notes="actually 'gauge fill speed +70.4%' (Metal o continuous)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst entry while in Metal o: self Attack Damage "
                "+21.12% and ATK +63.36% for 10 sec. Removes Metal o."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="Metal o status active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.12,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=63.36,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Sustained Damage +52.8% for 10 sec; nearest "
                "enemy takes 396% ATK as sustained damage every 1 sec for "
                "10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=52.8,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=3.96,
                    duration_seconds=10.0,
                    notes="DoT 396% ATK / sec for 10 sec",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind AR B3 — dual-state (Metal y / Metal o) carry with self-"
        "buff + niche resurrection. State-machine gap means simulator "
        "treats both buffs as always-on; real PvP usage requires "
        "carefully managing which state to be in."
    ),
)
register_character(_SKILL)
