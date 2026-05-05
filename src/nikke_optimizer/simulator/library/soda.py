"""Soda — B1 Fire MG Tetra. Healer + buff-stack extender.

Encoded from the live ``Character`` skill descriptions in the DB.
Soda's S1 Maid Spirit stacks self Max-HP, her S2 heals all allies and
super-heals at max stacks, and her burst damages 2 random enemies +
extends Fire-element ally buffs by 1 stack count (a unique mechanic
that pairs with stack-based attackers like Mast: Romantic Maid or
Modernia).

**Source description (S1)**:

    Activates after 180 normal attack(s). Affects self.
    Maid Spirit: Increase Max HP by 13%, stacks up to 5 time(s) and lasts for 10 sec.

**Source description (S2)**:

    Affects all allies. Restore HP equal to 3.23% of caster's final Max HP.

    Activates when Maid Spirit is fully stacked. Affects all allies.
    Restore HP equal to 12.71% of caster's final Max HP.

**Source description (Burst)**:

    Affects 2 enemy units randomly. Deals 321.8% of final ATK as damage.
    Stun for 1 sec.

    Affects all allies with Fire element. Stack count of buffs ▲ 1.
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
    character_name="Soda",
    skill1=(
        SkillEffect(
            description=(
                "Every 180 normal attacks: self Maid Spirit (+13% Max HP, "
                "max 5 stacks, 10 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=180),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.0,
                    duration_seconds=10.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic team heal: all allies recover 3.23% of Soda's "
                "max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="fires on S2's own cooldown timer",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.23,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Maid Spirit fully stacked (5x): all allies recover "
                "12.71% of Soda's max HP (super-heal)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Maid Spirit at 5 stacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=12.71,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 2 random enemies → 321.8% damage + Stun 1 sec. "
                "All Fire-element allies → +1 stack count of all buffs "
                "(unique mechanic)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=3.218,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=0.0,
                    duration_seconds=1.0,
                    notes=(
                        "Stun 1 sec; DSL has no STUN kind. Captured as "
                        "0-mag DEBUFF_DEFENSE with the duration set."
                    ),
                ),
                # Stack-count extension — unique buff manipulator.
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Fire-element allies: Stack count of "
                        "buffs +1' — a meta-buff that adds an extra "
                        "stack to existing buff effects. DSL gap "
                        "(STACK_COUNT_BUFF). Pairs with Mast:RM."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Soda is a B1 alt healer with a unique 'stack count +1' burst "
        "effect that boosts Fire-element teammates' stack-based buffs "
        "(e.g. Mast: Romantic Maid's Drunken stacks). Niche but "
        "powerful in stack-leaning Fire comps."
    ),
)
register_character(_SKILL)
