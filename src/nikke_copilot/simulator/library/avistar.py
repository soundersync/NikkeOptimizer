"""Avistar — B1 Electric MG. Re-Enter Burst Stage 1 supporter with
single-ally Aftershow ATK buff.

Encoded from the live ``Character`` skill descriptions in the DB.
Avistar's identity is the Aftershow buff after FB ends — designates
a "favorite pop star" (highest-ATK ally) and gives them +80.26%
of caster's ATK. Stargazer state from burst grants self +26.4% of
caster's max HP, and burst grants Re-Enter Burst Stage 1 (back-to-back
B1 cast).

**Source description (S1)**:

    On FB ends: favorite pop star — Aftershow ATK +80.26% of caster's
    ATK; removes on entering FB
    On FB ends: self HP regen 3.52% of caster's max HP / 1s for 10s;
    removes Stargazer

**Source description (S2)**:

    On FB entry while in Stargazer >25% HP: self Current HP -20%
    On FB entry while in Stargazer: favorite pop star — Projectile
    Explosion Damage +40.13% (continuous), Attack Damage +40.13%
    (continuous)

**Source description (Burst)**:

    All allies: Re-Enter Burst Stage 1
    Self: Stargazer — Max HP +26.4% of caster's max HP (continuous)
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
    character_name="Avistar",
    skill1=(
        SkillEffect(
            description="On FB end: top-ATK ally Aftershow ATK +80.26% caster ATK",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=80.26,
                    duration_seconds=30.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="removes on next FB entry; ~30s effective duration",
                ),
            ),
        ),
        SkillEffect(
            description="On FB end: self HP regen 3.52% caster max HP / 1s for 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.52,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="FB entry (Stargazer): favorite pop star Projectile + Attack Dmg +40.13%",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="self in Stargazer status",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=40.13,
                    duration_seconds=999.0,
                    notes="Projectile Explosion Damage — captured as parts-dmg",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=40.13,
                    duration_seconds=999.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: Re-Enter Stage 1 + self Stargazer (Max HP +26.4% caster HP)",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=26.4,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="Stargazer — continuous self Max HP buff",
                ),
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=100.0,
                    notes=(
                        "Re-Enter Burst Stage 1 — refunds team gauge for "
                        "an immediate second chain. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric MG B1 supporter — Re-Enter Burst Stage 1 mechanic + "
        "Aftershow ATK boost on a designated carry. Niche pick for "
        "double-burst comps with a single hyper-carry."
    ),
)
register_character(_SKILL)
