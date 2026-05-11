"""Zwei (base) — Electric SG B1, Pierce-team support with cover heals.

Encoded from the live ``Character`` skill descriptions in the DB.
Zwei is a niche B1 — modest Pierce Damage buffs, Cover HP recovery
every 5 hits, and a single-shot weapon-change burst with the Pierce
effect. Outclassed by Liter / Tia / Volume for general B1 duty but
useful in dedicated Pierce-team comps with SR / RL carries.

**Source description (S1)**:

    ■ Activates when entering Full Burst. Affects all allies. Pierce
    Damage ▲ 20.13% for 1 shot(s). Pierce Damage ▲ 10.06% for 10 sec.

**Source description (S2)**:

    ■ Activates after landing 5 normal attack(s). Affects all allies.
    Recovers 7.52% of Cover's HP.
    ■ Activates when entering Full Burst. Effects all allies. Critical
    Rate ▲ 18.63% for 5 sec.

**Source description (Burst)**:

    ■ Affects self. Change the Weapon in use: Charge Time 1.5 sec,
    Damage 50.69% of final ATK, Full Charge Damage 300%, Max Ammo 1,
    Additional Effect: Pierce.
    ■ Affects all allies. Pierce Damage ▲ 15.48% for 10 sec.
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
    character_name="Zwei",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Pierce Damage +20.13% "
                "for 1 shot, plus Pierce Damage +10.06% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.13,
                    duration_seconds=1.0,
                    notes=(
                        "actually '1 shot' duration, not 1 second; DSL "
                        "gap — consumed by the next pierce attack"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.06,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 5 normal-attack hits: all allies recover 7.52% "
                "of their Cover's HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.52,
                    notes="recovers Cover HP (not Nikke HP)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Crit Rate +18.63% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=18.63,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon change — Charge 1.5s, Damage "
                "50.69%, Full Charge 300%, Pierce. All allies Pierce "
                "Damage +15.48% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.5069,
                    notes=(
                        "weapon-change shot: 50.69% per shot, Full "
                        "Charge applies 300% multiplier (= 152.07%)"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.48,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric SG B1 — Pierce-team buffer. Outshone by Liter for "
        "general burst-gen but unique in Pierce-comp builds with SR / "
        "RL carries (Snow White, Vesti, Modernia). Cover-HP heal is a "
        "small bonus stall-support feature."
    ),
)
register_character(_SKILL)
