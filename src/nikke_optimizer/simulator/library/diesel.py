"""Diesel — B2 Wind MG Elysion. Self-sustain defender + AOE taunt.

Encoded from the live ``Character`` skill descriptions in the DB.
Diesel's S1 self-sustain (DEF + heal-when-attacked during FB) makes
her durable in burst windows; her burst is a 5-target AOE damage +
taunt that locks the opponent's strongest attackers onto her.

**Source description (S1)**:

    Activates when entering Full Burst. Affects self.
    DEF ▲ 25.92% for 10 sec.

    Activates when attacked during Full Burst. Affects self.
    Recovers HP by 12.96% of caster's final Max HP.

**Source description (S2)**:

    Activates after landing 100 normal attack(s). Affects self.
    Strawberry Candy: Max Ammunition Capacity ▲ 56.7% for 10 time(s)
    and lasts for 10 sec.

    Affects all allies when the caster reaches max stacks of Strawberry
    Candy. Activates after clearing stacks effect. Reload 86.62% magazine(s).

**Source description (Burst)**:

    Affects 5 enemy unit(s) with the highest ATK.
    Deals 299.98% final ATK as damage. Taunt for 5.06 sec.
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
    character_name="Diesel",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: self DEF +25.92% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.92,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When attacked during Full Burst: self heals 12.96% of "
                "max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="Full Burst window active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.96,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 100 normal attacks: self Max Ammo +56.7% (max 10 "
                "stacks, 10 sec). Strawberry Candy stacks."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=100),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=56.7,
                    duration_seconds=10.0,
                    stacks_max=10,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Strawberry Candy reaches max stacks (after stacks "
                "clear): all allies reload 86.62% of magazine."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Strawberry Candy reaches max stacks (10)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=86.62,
                    duration_seconds=1.0,
                    notes="actually 'reload 86.62% magazine' — instant reload proxy",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 5 highest-ATK enemies → 299.98% damage + taunt "
                "for 5.06 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP, count=5),
                    magnitude=2.9998,
                    notes="actually 'highest ATK'; ENEMY_HIGHEST_HP proxy in PvP",
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=5.06,
                    notes=(
                        "burst-applied taunt; the 5 nuked enemies are "
                        "the ones that get taunted (target enemies, "
                        "not Diesel) — encoded as self-taunt proxy"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Diesel slots into defense or hybrid teams as a B2 alt — her "
        "5-target AOE damage + taunt is solid disruption. Self-sustain "
        "during Full Burst gives her staying power."
    ),
)
register_character(_SKILL)
