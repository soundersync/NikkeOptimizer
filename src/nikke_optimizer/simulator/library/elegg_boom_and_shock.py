"""Elegg: Boom and Shock — B3 Water MG. Ghost-stack attacker with
team ATK buff for Water allies.

Encoded from the live ``Character`` skill descriptions in the DB.
Elegg's identity is the Ghost capture mechanic: every 100 cumulative
ally hits captures one ghost (max 13). Ghosts buff Water-code allies'
ATK (cross-stat from Elegg's ATK) and unlock a strong-element damage
amp at >4 stacks. Her burst spends ghosts for sequential hits, with
a max-ghost variant that deals +13 hits instead of +6.

**Source description (S1)**:

    On battle start: 1 random enemy possessed for 6s.
    Capture: required 100 cumulative ally hits → +1 ghost (max 13).
    Recurring 6s.

    Water-code allies:
      ≥1 ghost: ATK +16.2% of caster's ATK (continuous)
      >4 ghosts: Damage as strong element +35% (continuous)

**Source description (S2)**:

    On using Burst: self ATK +40% for 10s
    On ghost captured at max ghost capacity: all enemies — 1100% damage

**Source description (Burst)**:

    If ghosts ≠ 13: random enemies — 800% × 6 sequential. Ghosts -6 (min 1)
    If ghosts = 13: random enemies — 800% × 13 sequential. Ghosts -9
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Elegg: Boom and Shock",
    skill1=(
        SkillEffect(
            description="Possess random enemy 6s, capture ghost every 100 hits (max 13)",
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                notes="possession recurs every 6s",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=6.0,
                    stacks_max=13,
                    notes=(
                        "Ghost-capture mechanic: 100 cumulative ally hits → "
                        "+1 ghost. DSL gap (POSSESS / GHOST_STACK)."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description="≥1 ghost: Water allies ATK +16.2% of caster's ATK",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ghosts ≥ 1",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=16.2,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
        SkillEffect(
            description=">4 ghosts: Water allies Damage as Strong Element +35%",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ghosts > 4",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.WATER,
                    ),
                    magnitude=35.0,
                    duration_seconds=999.0,
                    notes="amp applies on damage-as-strong-element instances",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On Burst use: self ATK +40% for 10s",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description="On ghost captured at max capacity: all enemies 1100% dmg",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ghost captured while at max capacity (13)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=11.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: 800% × 6 random hits if ghosts < 13 (Ghosts -6, min 1)",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="ghosts < 13",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=6),
                    magnitude=8.0,
                    notes="6 sequential hits at 800% each",
                ),
            ),
        ),
        SkillEffect(
            description="Burst: 800% × 13 random hits if ghosts = 13 (Ghosts -9)",
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="ghosts == 13",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=13),
                    magnitude=8.0,
                    notes="13 sequential hits at 800% each",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water MG B3. Ghost-stack engine that supports Water-code allies "
        "with cross-stat ATK + strong-element amp at >4 ghosts. Best "
        "paired with hit-rate Water teams that can capture ghosts fast."
    ),
)
register_character(_SKILL)
