"""Chime — B2 Iron SMG. "King" cross-stat single-target buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Chime's identity is the King mechanic — she designates one ally
(usually the team carry / B3) and pumps cross-stat ATK + Normal
Attack Damage + Attack Damage onto that single target. Her own burst
re-enters Stage 2 (a unique back-to-back B2 cast) and ammo-buffs
all allies. Niche but powerful in single-carry comps.

**Source description (S1)**:

    On battle start: King — ATK +46.46% of caster's ATK (continuous)

**Source description (S2)**:

    On entering Full Burst: King — Normal Attack Damage Multiplier
    +46.22% for 10s

**Source description (Burst)**:

    All allies: Re-Enter Burst Stage 2; Max Ammo +20% for 10s
    King: Loyalty — Attack Damage +92.44% for 10s
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
    character_name="Chime",
    skill1=(
        SkillEffect(
            description="At battle start: King ATK +46.46% of caster's ATK",
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=46.46,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "King is designated by the player; we approximate "
                        "via ALLY_HIGHEST_ATK since that's typically the "
                        "team's primary carry."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On FB entry: King Normal Attack Damage Multiplier +46.22% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=46.22,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: Re-Enter Stage 2 + all Max Ammo +20% + King Loyalty",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=92.44,
                    duration_seconds=10.0,
                    notes="Loyalty — Attack Damage +92.44% to King for 10s",
                ),
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=100.0,
                    notes=(
                        "Re-Enter Burst Stage 2 — refunds gauge, allows "
                        "back-to-back B2 cast. DSL gap (RE_ENTER_STAGE)."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Iron SMG B2 single-target buffer. King mechanic targets the "
        "team carry — cross-stat ATK + Normal Attack Damage + Attack "
        "Damage all funnel into one B3. Re-Enter Stage 2 enables exotic "
        "double-B2 rotations."
    ),
)
register_character(_SKILL)
