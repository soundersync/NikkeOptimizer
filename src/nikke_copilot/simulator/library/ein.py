"""Ein — B3 Electric SR Missilis. Near Feathers true-damage carry.

Encoded from the live ``Character`` skill descriptions in the DB. Ein
summons Near Feathers — autonomous projectiles that deal true damage —
plus a Charge-Damage-on-Full-Charge self buff. Burst summons more
feathers and deals true damage to the 10 highest-DEF enemies.

**Source description (S1)**:

    Activates when entering battle. Effects self.
    Summons 4 Near Feathers.

    Activates when entering Burst Skill Stage 3. Affects self.
    ATK ▲ 70.12% for 10 sec.

**Source description (S2)**:

    Activates when Near Feather is summoned. Effects 1 random enemy unit(s).
    Near Feather Attack: Deals 90.81% of final ATK as true damage.

    Activates when attacking with Full Charge. Affects self.
    Charge Damage ▲ 80% for 1 shot(s).

**Source description (Burst)**:

    Affects self. Summons 6 Near Feathers.
    True Damage ▲ 55.3% for 10 sec.
    Charge Damage ▲ 140.68% for 10 sec.

    Affects 10 enemy unit(s) with the highest DEF.
    Deals 300.02% of final ATK as true damage.
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
    character_name="Ein",
    skill1=(
        SkillEffect(
            description=(
                "On battle start: summons 4 Near Feathers (auto-attacking "
                "projectiles)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=4),
                    magnitude=0.9081,
                    notes=(
                        "4 Near Feathers — each deals 90.81% true damage "
                        "to a random enemy on summon (S2 trigger)"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On B3 cast: self ATK +70.12% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=70.12,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge: self Charge Damage +80% for 1 shot."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge release",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=80.0,
                    duration_seconds=1.0,
                    notes="actually 'for 1 shot', not 1 sec",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: summons 6 Near Feathers, self True Damage +55.3% "
                "+ Charge Damage +140.68% for 10 sec; 10 highest-DEF "
                "enemies take 300.02% true damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=140.68,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=55.3,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.0002,
                    notes="actually highest-DEF (10 enemies); PvP fallback",
                ),
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=6),
                    magnitude=0.9081,
                    notes="6 additional Near Feathers summoned",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Ein's true damage bypasses DEF — strong vs heavy-defense comps "
        "(Helm/Centi/Blanc walls). Pairs with Crown for ATK stacking."
    ),
)
register_character(_SKILL)
