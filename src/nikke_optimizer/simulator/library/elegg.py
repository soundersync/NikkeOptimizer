"""Elegg — Electric MG B2, anti-projectile / Distributed Damage support.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Battle start: all allies — when attacking enemy projectile, damage
    to that projectile ▲ 59.66% continuously.
    After 100 normal attacks on a BOOM Install target: 91.03% ATK
    Distributed Damage to target + 2 surrounding enemies.

**Source description (S2)**:

    After 60 normal attacks on a BOOM Install target: all allies ATK
    +13.09% of caster's ATK for 5 sec.
    Target appears: all allies +100% burst gauge (1 / battle).

**Source description (Burst)**:

    All allies: Distributed Damage ▲ 39.74% for 10 sec.
    Nearest enemy: 79.2% ATK damage. BOOM Install: DEF ▼ 35.64% for
    10 sec.
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
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Elegg",
    skill1=(
        SkillEffect(
            description=(
                "Every 100 normal attacks on BOOM Install target: target "
                "+ 2 surrounding enemies take 91.03% ATK Distributed "
                "Damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=100),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=3),
                    magnitude=0.9103,
                    notes="target + 2 surrounding (DSL gap on AOE)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 60 normal attacks on BOOM Install target: all "
                "allies ATK +13.09% of caster's ATK for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=13.09,
                    duration_seconds=5.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Enemy spawn: all allies +100% burst gauge (1 / battle)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="enemy spawns (1 per battle)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=100.0,
                    notes="once-per-battle (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Distributed Damage +39.74% for 10 sec; "
                "nearest enemy takes 79.2% ATK damage and DEF -35.64% "
                "for 10 sec (BOOM Install)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=39.74,
                    duration_seconds=10.0,
                    notes="actually 'Distributed Damage' (DSL gap, encoded as pierce)",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.792,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=35.64,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric MG B2 — distributed-damage / anti-projectile niche. "
        "Pairs with Distributed-Damage carries (Quency:EQ). Mostly "
        "boss-room utility; PvP value depends on the team's "
        "Distributed-Damage outputs."
    ),
)
register_character(_SKILL)
