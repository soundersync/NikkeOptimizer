"""Rupee: Winter Shopper — B1 Electric AR Tetra Talentum. Burst-cycle reset DEF buffer.

Encoded from the live ``Character`` skill descriptions in the DB. R:WS
is a B1 with a unique re-burst mechanic: her burst grants Reload Speed
+63.17% + re-enters Burst Skill Stage 1 (allowing back-to-back B1
rotations) and self-Taunts with lifesteal. S2 stacks DEF on burst use
across the team.

**Source description (S1)**:

    On last bullet hit: all allies DEF +19.02% for 5 sec.

**Source description (S2)**:

    On any ally Burst Skill use: all allies Shopping — DEF +1.33%,
        ×4, 20 sec.
    When self reaches max Shopping stacks at end of Full Burst: all
        allies Burst gauge loading speed +7.9% for 5 sec.

**Source description (Burst)**:

    Self: Attract 5 sec. Recover 50.47% of attack damage as HP over
        10 sec.
    All allies: Reload Speed +63.17% for 10 sec. Re-enter Burst Skill
        Stage 1.
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
    character_name="Rupee: Winter Shopper",
    skill1=(
        SkillEffect(
            description=(
                "On last-bullet hit: all allies DEF +19.02% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=19.02,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On any ally Burst use: all allies Shopping DEF +1.33% "
                "×4 stacks, 20 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_ALLY_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.33,
                    duration_seconds=20.0,
                    stacks_max=4,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "At Full Burst end with max Shopping stacks: all "
                "allies Burst gauge speed +7.9% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_END,
                condition="self at Shopping 4/4 stacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.9,
                    notes=(
                        "Burst gauge loading speed +7.9% over 5 sec. "
                        "DSL has no BURST_GAUGE_SPEED kind; proxied "
                        "via GAIN_BURST_GAUGE."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Taunt 5s + 50.47% lifesteal 10s; all "
                "allies Reload Speed +63.17% 10s; re-enter Burst Stage 1."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=50.47,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'recover 50.47% of attack damage as "
                        "HP over 10 sec' — lifesteal proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=63.17,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    notes=(
                        "Re-enter Burst Skill Stage 1 — refreshes the "
                        "burst chain back to B1. DSL gap (BURST_CHAIN_"
                        "RESET); critical mechanic. 0-mag flag."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric AR B1 — unique burst-cycle reset mechanic (re-enter "
        "B1 stage) enables back-to-back rotations. DEF-stacking team "
        "supporter via Shopping (S2) + last-bullet DEF buff (S1). "
        "Self-sustain via lifesteal during her own Taunt window."
    ),
)
register_character(_SKILL)
