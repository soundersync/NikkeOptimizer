"""Privaty: Unkind Maid — B3 Electric SG Elysion. Pellet-stacking carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Unkind Maid is the alt Privaty form built around shotgun pellet hits
during Full Burst — high-pellet attacks build ATK stacks and drive
the 1066.66% AOE burst.

**Source description (S1)**:

    Activates when landing attacks 30 time(s) using pellets.
    Affects 2 enemy units nearest to the crosshair.
    Deals 202.84% of final ATK as additional damage.

**Source description (S2)**:

    Activates when more than 5 pellet(s) hit with a single normal attack.
    Affects self. Reloading Speed ▲ 20.88% for 2 sec.

    Activates when hitting 30 time(s) using pellets during Full Burst Time.
    Affects self. Reload 1 round(s).
    ATK ▲ 11.22%, stacks up to 5 time(s) and lasts for 2 sec.

**Source description (Burst)**:

    Affects self. Attack Damage ▲ 10.56% for 10 sec.
    Critical Damage ▲ 88.17% for 10 sec.

    Affects all enemies. Deals 1066.66% of final ATK as damage.
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
    character_name="Privaty: Unkind Maid",
    skill1=(
        SkillEffect(
            description=(
                "Every 30 pellet hits: 2 nearest enemies take 202.84% "
                "of ATK additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=30,
                condition="pellet hits",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=2),
                    magnitude=2.0284,
                    notes="'nearest to crosshair' — DSL has no spatial target",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "When >5 pellets hit a single attack: self Reload "
                "Speed +20.88% for 2 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition=">5 pellets hit single normal attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.88,
                    duration_seconds=2.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 30 pellet hits during Full Burst: self instant "
                "reload 1 round + ATK +11.22% (stacks 5x, 2 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=30,
                condition="pellet hits during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=0.1,
                    notes=(
                        "actually 'Reload 1 round' — DSL has no "
                        "instant-reload kind. Captured as 100% reload buff."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=11.22,
                    duration_seconds=2.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Attack Damage +10.56% and Crit Damage "
                "+88.17% for 10 sec; all enemies take 1066.66% of ATK."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=10.56,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=88.17,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=10.6666,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Privaty: Unkind Maid is the SG alt form, built around pellet "
        "hits during Full Burst — high-pellet shots build ATK stacks "
        "and reload, driving repeated 1066% AOE bursts. Pairs with "
        "Leona (pellet count + crit), Drake (SG synergy), Liter "
        "(burst gen)."
    ),
)
register_character(_SKILL)
