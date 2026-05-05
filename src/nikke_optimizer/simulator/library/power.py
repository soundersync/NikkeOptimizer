"""Power — B3 Fire RL Abnormal (Chainsaw Man collab).

Encoded from the live ``Character`` skill descriptions in the DB.
Power's identity is the Blood Fiend stacking (5 stacks → max payout
on burst). Her burst nukes 1 highest-ATK enemy for 1584%, doubled
on max stacks.

**Source description (S1)**:

    Activates when attacking with Full Charge. Affects self.
    Blood Fiend: ATK ▲ 6.4%, stacks up to 5 time(s) and lasts for 3 sec.

**Source description (S2)**:

    Activates when at Max Stacks of Blood Fiend after landing 18
    normal attack(s). Affects self.
    Explosion Radius ▲ 38.61% for 10 sec. Reload ▲ 100%.
    Activates 1 time(s) per battle.

**Source description (Burst)**:

    Affects 1 enemy unit with the highest ATK. Deals 1584% of final
    ATK as damage.

    Affects the same target(s) when Blood Fiend is fully stacked.
    Deals 1584% of final ATK as additional damage.
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
    character_name="Power",
    skill1=(
        SkillEffect(
            description=(
                "On full charge attack: self Blood Fiend ATK +6.4% "
                "(stacks 5x, 3 sec)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.4,
                    duration_seconds=3.0,
                    stacks_max=5,
                    notes="'Blood Fiend' stacks — gates burst doubling",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "At max Blood Fiend after 18 normal attacks: self "
                "Explosion Radius +38.61% 10 sec, Reload 100%. "
                "1x/battle."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=18,
                condition="Blood Fiend at max stacks",
                notes="1x per battle — DSL gap",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=38.61,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Explosion Radius +38.61%' — DSL has "
                        "no AOE_RADIUS effect kind. BUFF_ATK proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes="instant full reload — captured as 100% reload buff",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 1 highest-ATK enemy takes 1584%; if Blood "
                "Fiend max, +1584% additional."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=15.84,
                    notes=(
                        "actually 'highest ATK enemy' — DSL has no "
                        "ENEMY_HIGHEST_ATK target kind. Proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=15.84,
                    notes=(
                        "Blood Fiend max-stacks conditional bonus. "
                        "DSL has no stack-state trigger; encoded as "
                        "second damage instance with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Power is a single-target burst nuker — full-charge into 5 "
        "Blood Fiend stacks, then S2 reload for an extra full-charge "
        "salvo, then burst doubles to 3168%. Pairs with Jackal "
        "(single-target burst amp) and any reload-speed support."
    ),
)
register_character(_SKILL)
