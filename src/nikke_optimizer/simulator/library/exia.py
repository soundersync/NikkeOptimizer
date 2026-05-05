"""Exia — B1 Electric SR. ATK/DEF debuffer with self-stacking ATK.

Encoded from the live ``Character`` skill descriptions in the DB.
Exia stacks her own ATK +16.8% per last-bullet hit (max 5), and once
fully stacked her last-bullet hits also debuff the target's ATK and
DEF by 13.77% each. Burst is a 10-target high-DEF nuke.

**Source description (S1)**:

    Last bullet hits target while in Collect Hacking Code: target —
    ATK -13.77% for 5s, DEF -13.77% for 5s

**Source description (S2)**:

    Last bullet hits target: self Collect Hacking Code — ATK +16.8%
    per stack (max 5, 15s)

**Source description (Burst)**:

    10 highest-DEF enemies: 122.32% damage; DEF -2.71% for 5s
    On Collect Hacking Code fully stacked: same targets — 122.32%
    additional damage
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
    character_name="Exia",
    skill1=(
        SkillEffect(
            description="Last bullet (Collect Hacking Code): target ATK -13.77% / DEF -13.77% 5s",
            trigger=Trigger(
                kind=TriggerKind.ON_LAST_AMMO,
                condition="Collect Hacking Code active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=13.77,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=13.77,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Last bullet: self Collect Hacking Code — ATK +16.8% (max 5, 15s)",
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=16.8,
                    duration_seconds=15.0,
                    stacks_max=5,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: 10 high-DEF enemies 122.32% + DEF -2.71% 5s + bonus if maxed",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=1.2232,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=2.71,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=1.2232,
                    notes="conditional bonus when Collect Hacking Code fully stacked",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SR B1 debuff support. Self-stacking ATK + on-target "
        "ATK/DEF debuff once stacked. Niche — mostly out-tier'd by "
        "Liter / Tia in PvP."
    ),
)
register_character(_SKILL)
