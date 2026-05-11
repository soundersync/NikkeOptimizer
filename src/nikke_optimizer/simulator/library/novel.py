"""Novel — B2 Iron SMG Tetra Protocol. DEF-shred single-target nuker.

Encoded from the live ``Character`` skill descriptions in the DB.
Novel's identity is anti-tank: S1 shreds the 3 highest-DEF enemies,
S2 stacks self DEF via Cornucopia, and her burst nukes the highest-
ATK enemy with a 67.5% Damage Taken amplifier when fully stacked.

**Source description (S1)**:

    Top 3 highest-DEF enemies: 52.36% ATK damage + DEF -7.05% 5 sec.

**Source description (S2)**:

    Every 100 normal attacks: self Cornucopia — DEF +13.5%, ×5, 15 sec.

**Source description (Burst)**:

    Highest-ATK enemy: 330.61% ATK damage.
    If Cornucopia fully stacked: 1 enemy Damage Taken +67.5% 5 sec.
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
    character_name="Novel",
    skill1=(
        SkillEffect(
            description=(
                "Top-3 highest-DEF enemies take 52.36% ATK damage + "
                "DEF -7.05% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="fires on S1 internal cooldown",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=3),
                    magnitude=0.5236,
                    notes="actually top-3 highest-DEF (DSL gap)",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=3),
                    magnitude=7.05,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 100 normal attacks: self Cornucopia — DEF "
                "+13.5%, ×5 stacks, 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=100),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.5,
                    duration_seconds=15.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: highest-ATK enemy takes 330.61% ATK; if "
                "Cornucopia 5/5, 1 enemy Damage Taken +67.5% 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=3.3061,
                    notes="actually highest-ATK enemy (DSL gap)",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=67.5,
                    duration_seconds=5.0,
                    notes="conditional on Cornucopia 5/5",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SMG B2 — anti-tank single-target nuker. S1 passive DEF-"
        "shred on top-3 high-DEF enemies softens defensive comps; "
        "burst is a focused nuke + huge DT amp at max stacks. Pairs "
        "well behind a sustain B1/B3 since she has no team support."
    ),
)
register_character(_SKILL)
