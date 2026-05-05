"""Aria — B2 Water MG. Crit-rate / Crit-damage team supporter with
Full Burst entry shield.

Encoded from the live ``Character`` skill descriptions in the DB.
Aria's identity is the team-wide crit-stat buff at the start of each
Full Burst window, paired with a max-HP-scaled shield on burst.
Underrated B2 alt for crit-leaning attacker comps.

**Source description (S1)**:

    On entering Full Burst: all allies Critical Damage +26.99% for 10s

**Source description (S2)**:

    On last bullet hits target: all allies Critical Rate +7.03% for 5s

**Source description (Burst)**:

    All allies: shield 37.86% of caster's max HP for 10s
    Self: Hit Rate +30.37% for 15s
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
    character_name="Aria",
    skill1=(
        SkillEffect(
            description="On FB entry: all allies Critical Damage +26.99% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=26.99,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Last bullet hits target: all allies Crit Rate +7.03% 5s",
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.03,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies shield 37.86% caster max HP + self Hit Rate +30.37%",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=37.86,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.37,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water MG B2 crit supporter. Crit Damage +27% on FB entry "
        "stacks with crit-rate buffs from Liter / Dolla / Volume — "
        "underrated alt B2 for crit-scaling attacker comps."
    ),
)
register_character(_SKILL)
