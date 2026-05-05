"""Ludmilla: Winter Owner — Water MG B3, MG sustained-damage carry.

Encoded from the live ``Character`` skill descriptions.

**Source description (S1)**:

    Activates when landing 60 normal attacks. Affects the target.
    Damage Taken ▲ 12.56% for 3 sec. Deal 158.43% of final ATK as
    additional damage.
    Activates when landing 60 normal attacks. Affects self. Reloads
    20 rounds of ammunition.

**Source description (S2)**:

    Activates when hitting the Core for 60 times. Affects the target.
    Deal 109.64% of final ATK as additional damage.
    Activates at the beginning of Full Burst. Affects self. Critical
    Rate ▲ 14.6% for 10 sec.

**Source description (Burst)**:

    Affects self. ATK ▲ 62.54% for 10 sec. Reloading Speed ▲ 67.2%
    for 20 sec.
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
    character_name="Ludmilla: Winter Owner",
    skill1=(
        SkillEffect(
            description=(
                "Every 60 normal attacks: target takes 158.43% of ATK "
                "as additional damage and Damage Taken +12.56% for 3 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.5843,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=12.56,
                    duration_seconds=3.0,
                    notes="actually 'damage taken' debuff (DSL gap)",
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.0,
                    duration_seconds=86400.0,
                    notes="reload 20 rounds (one-shot, not capacity buff)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 60 core hits: target takes 109.64% of ATK as "
                "additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT, every_n_hits=60,
                condition="core hits only",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.0964,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst entry: self Crit Rate +14.6% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=14.6,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self ATK +62.54% for 10 sec; Reload Speed "
                "+67.2% for 20 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=62.54,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=67.2,
                    duration_seconds=20.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water MG B3 — sustained-damage carry. Self-buff focused (no "
        "team support); benefits from B1+B2 supporters that boost "
        "her ATK and ammo. 60-attack cadence is fast on MG (high fire "
        "rate), so the per-60 triggers fire reliably mid-match."
    ),
)
register_character(_SKILL)
