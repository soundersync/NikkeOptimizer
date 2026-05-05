"""Arcana: Fortune Mate — Fire SG B2, SG-comp burst-window enhancer.

Encoded from the live ``Character`` skill descriptions. Arcana:FM has
a multi-phase normal-attack stack ladder (2/4/6 hits) feeding into
"Precious Moments" stacks that drive her S1 SG-team ATK buff.

**Source description (S1)**:

    Activates when Full Burst ends. Affects all SG allies. ATK ▲ 13%
    of caster's ATK × Precious Moments stacks for 15 sec.
    Activates when Happy Memories takes effect. Affects self.
    Snapshots of Youth: Normal Attack Damage Multiplier ▲ 10%
    continuously, max 3 stacks.
    Activates when Full Burst ends. Removes Making Memories. Removes
    Snapshots of Youth.

**Source description (S2)**:

    Activates on normal attacks while in Making Memories. Phase varies
    by attack count.
      Two times: Reload 6 rounds.
      Four times: Happy Memories (+1 pellet, max 3 stacks).
      Six times: Precious Moments (+2.49% ATK, max 3 stacks).

**Source description (Burst)**:

    Affects self. Making Memories: Crit Rate ▲ 20.09% continuously,
    Reload 2 rounds, Attack Damage ▲ 29.99% continuously.
    Affects all enemies. 554.4% of ATK as Burst Skill damage.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
    WeaponClass,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Arcana: Fortune Mate",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst end: all SG allies ATK +13% of caster's ATK "
                "× Precious Moments stacks (max 3) for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=13.0,
                    duration_seconds=15.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    stacks_max=3,
                    notes="mirrors Precious Moments stacks (1-3)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 6 normal attacks (Phase 6 of Making Memories): "
                "self Precious Moments — ATK +2.49% continuously, max "
                "3 stacks."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=6),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.49,
                    duration_seconds=86400.0,
                    stacks_max=3,
                    notes=(
                        "phased: only after Making Memories triggers, "
                        "and reset on full reload (DSL gap)"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst — Making Memories: self Crit Rate +20.09% and "
                "Attack Damage +29.99% continuously; deals 554.4% of "
                "ATK as Burst-Skill damage to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.09,
                    duration_seconds=86400.0,
                    notes="Making Memories state — removed on FB end",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=29.99,
                    duration_seconds=86400.0,
                    notes="Making Memories state — removed on FB end",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=5.544,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire SG B2 — SG-team ATK enhancer. Pairs with Tove + Noir + "
        "SG B3 carries. Multi-phase Making Memories state machine is "
        "a DSL gap; per-phase stacks (2/4/6 hits) collapse into a "
        "single 'every 6 hits → +ATK stack' approximation."
    ),
)
register_character(_SKILL)
