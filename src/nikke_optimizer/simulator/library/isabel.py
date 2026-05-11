"""Isabel — B3 Electric SG Pilgrim Inherit. Burst-cycling self-stacker.

Encoded from the live ``Character`` skill descriptions in the DB.
Isabel's identity is the Marked Target state machine: each Burst use
advances her through three phases that progressively unlock Crit
Rate → Crit Damage → ATK self-buffs, and the additional burst-damage
output scales with the same phase progression. Her S2 fires a passive
high-DEF nuke per attack rotation. The burst itself shortens Full
Burst by 5 sec — a unique trade-off.

**Source description (S1)**:

    On Burst use: self Marked Target 1, Crit Rate ▲ 6.26% for 45 sec.
    On Burst use during Marked Target 1: self Marked Target 2, Crit
        Damage ▲ 18.03% for 45 sec. Previous effects trigger repeatedly.
    On Burst use during Marked Target 2: self Marked Target 3, ATK
        ▲ 17.28% for 45 sec. Previous effects trigger repeatedly.

**Source description (S2)**:

    Affects 5 highest-DEF enemies. Deals 170.58% of final ATK as damage.

**Source description (Burst)**:

    All enemies: 149.85% of final ATK as damage.
    Marked Target 1: Damage Taken +39.96% 5 sec.
    Marked Target 2: +299.7% additional damage.
    Marked Target 3: +349.65% additional damage.
    Previous effects trigger repeatedly.
    All allies: Full Burst Time -5 sec.
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
    character_name="Isabel",
    skill1=(
        SkillEffect(
            description=(
                "On Burst use: self Crit Rate +6.26% for 45 sec "
                "(Marked Target 1)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.26,
                    duration_seconds=45.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Burst use during Marked Target 1: advance to MT2 "
                "+ self Crit Damage +18.03% for 45 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="self in Marked Target 1",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=18.03,
                    duration_seconds=45.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Burst use during Marked Target 2: advance to MT3 "
                "+ self ATK +17.28% for 45 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="self in Marked Target 2",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=17.28,
                    duration_seconds=45.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Passive: top-5 highest-DEF enemies take 170.58% ATK "
                "as damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="fires on S2 internal cooldown",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=5),
                    magnitude=1.7058,
                    notes="actually top-5 highest-DEF enemies (DSL gap)",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 149.85% AOE damage to all enemies; phase-gated "
                "bonuses (MT1: +39.96% DT 5s; MT2: +299.7% damage; "
                "MT3: +349.65% damage); team FB time -5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.4985,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=39.96,
                    duration_seconds=5.0,
                    notes="conditional on self in Marked Target 1",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.997,
                    notes="conditional on self in Marked Target 2",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=3.4965,
                    notes="conditional on self in Marked Target 3",
                ),
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    notes=(
                        "Full Burst Time -5 sec — trade-off. DSL gap "
                        "(TUNE_FB_DURATION)."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SG B3 Pilgrim — state-machine self-buff carry. "
        "Cycles through 3 Marked Target phases on repeated bursts, "
        "ramping Crit Rate → Crit Damage → ATK while burst damage "
        "phase-scales upward. Shortens team FB by 5 sec (unique cost). "
        "Niche but powerful in Isabel-centric Electric burst rotations."
    ),
)
register_character(_SKILL)
