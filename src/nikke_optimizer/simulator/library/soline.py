"""Soline (base) — Iron SMG B3, Max-HP crit DPS.

Encoded from the live ``Character`` skill descriptions in the DB. Base
Soline is a deceptively simple kit: a tiny attack-speed proc, a giant
permanent crit buff that requires staying at Max HP, and a burst that
doubles damage when at Max HP. Heavily synergizes with shield/heal
supports that prevent any HP loss.

**Source description (S1)**:

    ■ Activates after 40 normal attack(s). Affects Self. Attack speed
    ▲ 7.26% for 3 sec.

**Source description (S2)**:

    ■ Only affects self at Max HP. Critical Rate ▲ 21.62% permanently
    Critical Damage ▲ 62.27% permanently.

**Source description (Burst)**:

    ■ Affects enemies within attack range. Deals damage equal to 396%
    of final ATK.
    ■ Cast on the same enemies when at Max HP. Deals 924% of final ATK
    as additional damage.
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
    character_name="Soline",
    skill1=(
        SkillEffect(
            description=(
                "Every 40 normal-attack hits: self Attack Speed +7.26% "
                "for 3 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=40),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=7.26,
                    duration_seconds=3.0,
                    notes=(
                        "actually 'Attack Speed +7.26%'; DSL has no "
                        "BUFF_ATTACK_SPEED — encoded as BUFF_HIT_RATE proxy"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "While at Max HP: self Crit Rate +21.62% and Crit "
                "Damage +62.27% permanently."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self at Max HP",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.62,
                    duration_seconds=86400.0,
                    notes="conditional on caster at Max HP",
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=62.27,
                    duration_seconds=86400.0,
                    notes="conditional on caster at Max HP",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: enemies in range take 396% of ATK; if self at "
                "Max HP, +924% additional damage on same targets."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.96,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=9.24,
                    notes="conditional on caster at Max HP",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SMG B3 attacker — Max-HP gated crit nuke. Strong when "
        "paired with shield-providing supports (Helm, Centi, Noah) "
        "that prevent any HP loss to keep crit + bonus burst active."
    ),
)
register_character(_SKILL)
