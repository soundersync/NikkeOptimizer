"""Nihilister — B2 Fire SR Pilgrim. Pierce + AOE Burn carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Nihilister is the dragon-comp B2 Pierce SR — full charge grants
Pierce, multi-hit normals deal AOE bonus, and her burst stacks AOE
damage with a Burn DOT.

**Source description (S1)**:

    Activates when attacking with Full Charge. Affects self.
    Gain Pierce for 1 round(s). Piercing Radius ▲ 50% for 1 round(s).

    Activates when a normal attack hits 2 or more enemies concurrently.
    Affects all enemies hit. Deals 50.33% of final ATK as additional damage.

**Source description (S2)**:

    Affects enemy unit(s) within attack range. Deals 112.64% of final
    ATK as damage.

**Source description (Burst)**:

    Affects enemies within the attack range. Deals 158.59% of final
    ATK as damage. Burn: Deals 13.19% of final ATK as sustained damage
    every 1 sec for 10 sec.

    Affects self. Max Ammunition Capacity ▲ 6 round(s) for 15 sec.
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
    character_name="Nihilister",
    skill1=(
        SkillEffect(
            description=(
                "On full charge: self gains Pierce + Piercing Radius "
                "+50% for 1 round."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=50.0,
                    duration_seconds=2.0,
                    notes=(
                        "actually '1 round' — DSL gap (rounds vs "
                        "seconds). Captured as 2-sec proxy."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When normal attack hits 2+ enemies: all hit enemies "
                "take 50.33% of ATK additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="normal attack hits 2+ enemies",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.5033,
                    notes="actually 'all enemies hit' — proxy via ALL_ENEMIES",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: enemies within attack range take 112.64% "
                "of ATK damage."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.1264,
                    notes="actually 'enemies within attack range' — proxy",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: enemies in range take 158.59% damage + Burn "
                "(13.19% per sec for 10 sec); self Max Ammo +6 for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.5859,
                    notes="actually 'enemies within attack range' — proxy",
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.1319,
                    duration_seconds=10.0,
                    notes="Burn DOT: 13.19% of ATK every 1 sec for 10 sec",
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.0,
                    duration_seconds=15.0,
                    notes="actually '+6 rounds' — flat ammo bonus",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Nihilister is the rare B2 SR with built-in Pierce + AOE Burn "
        "DOT. Pairs with Full-Charge teams (Cinderella / SBS / "
        "Maxwell) and Pierce supports (Asuka, Crown). Burn DOT "
        "compounds her sustained damage profile."
    ),
)
register_character(_SKILL)
