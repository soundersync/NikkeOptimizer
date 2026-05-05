"""Kilo — B3 Fire MG Missilis. Nano Coating shield carry.

Encoded from the live ``Character`` skill descriptions in the DB. Kilo's
identity is the Nano Coating shield state — battle start grants a 21.12%
Max HP shield, burst either nukes (in coating) or refreshes Max HP +48%
(out of coating). Her S2 cumulative ramps the next shield's HP up to +35%.

**Source description (S1)**:

    Activates when entering battle. Affects self.
    Nano Coating: Creates a Shield equal to 21.12% of caster's final
    Max HP continuously.

    Activates when using Burst Skill. Affects self if not in Nano
    Coating status. Nano Coating: Creates a Shield equal to 21.12%
    of caster's final Max HP continuously.

**Source description (S2)**:

    Activates when performing Normal Attack for 200 time(s) in Nano
    Coating status. Affects self.
    Recovery Shield HP equal to 2.85% caster's final Max HP.

    Activates when using Burst Skill. Affects self if not in Nano
    Coating status. Effect changes according to the caster's status.
    Previous effects trigger repeatedly:
        Once:        Next Shield's HP ▲ 17.75% continuously.
        Twice:       Next Shield's HP ▲ 26.66% continuously.
        Three times: Next Shield's HP ▲ 35.53% continuously.

**Source description (Burst)**:

    Activates when in Nano Coating status. Affects all enemies.
    Deals damage equal to 1150.84% of the ATK, which is calculated
    from 5% of final Max HP.

    Activates when not in Nano Coating status. Affects self.
    Max HP ▲ 48% for 20 sec.
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
    character_name="Kilo",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: self Nano Coating shield = 21.12% of "
                "Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.12,
                    duration_seconds=999.0,
                    notes="'Nano Coating' state — gates burst nuke vs HP buff",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use without Nano Coating: self refreshes "
                "shield = 21.12% of Max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="not in Nano Coating",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.12,
                    duration_seconds=999.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 200 normal attacks in Nano Coating: self "
                "shield HP +2.85% of Max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=200,
                condition="in Nano Coating",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.85,
                    duration_seconds=999.0,
                    notes="actually 'recovery shield HP' — adds to existing shield",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Cumulative on burst use without Nano Coating "
                "(3rd-tier): next shield HP +35.53%; tiers 1+2 also "
                "active."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="not in Nano Coating",
                notes="cumulative — encodes 3rd-tier value",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=35.53,
                    duration_seconds=999.0,
                    notes=(
                        "'next shield HP +35.53%' — cumulative tier "
                        "(1st: 17.75%, 2nd: 26.66%, 3rd: 35.53%). "
                        "Compounds with S1's 21.12% base."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst (in Nano Coating): all enemies take 1150.84% "
                "of ATK scaled by 5% Max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="in Nano Coating",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=11.5084,
                    notes=(
                        "actually '1150.84% of ATK calculated from 5% "
                        "of Max HP' — cross-stat damage (HP→damage). "
                        "DSL gap."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Burst (without Nano Coating): self Max HP +48% for "
                "20 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="not in Nano Coating",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=48.0,
                    duration_seconds=20.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Kilo is the Nano Coating state-machine carry — battle start "
        "shields her, and her burst either nukes (when shielded) or "
        "rebuilds HP (when broken). Pairs with HP-scaling supports "
        "(Centi shields, Maiden: Ice Rose's HP-driven burst) since her "
        "damage scales off Max HP."
    ),
)
register_character(_SKILL)
