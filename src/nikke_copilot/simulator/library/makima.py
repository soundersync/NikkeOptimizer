"""Makima — B2 Water SMG Abnormal (Chainsaw Man collab).

Encoded from the live ``Character`` skill descriptions in the DB.
Makima is the indomitability-tank B2 — taunts, lethal-damage immunity,
self-Pierce on burst, and strong DEF/Reload team support.

**Source description (S1)**:

    Activates when attacked 20 time(s). Affects all allies.
    Reloading Speed ▲ 36.96% for 10 sec. DEF ▲ 14.78% for 10 sec.

**Source description (S2)**:

    Activates after landing 120 normal attack(s). Affects self.
    Attract: Taunt all enemies for 3 sec.

    Activates when taking lethal damage. Affects self.
    Gains indomitability for 7 sec. Activates 1 time(s) per battle.
    Cooldown of Burst Skill ▼ 11.58 sec.

**Source description (Burst)**:

    Affects self. Gain Pierce for 10 sec.
    Recover 34.02% of attack damage as HP over 10 sec.

    Activates during indomitability. Affects self.
    HP Potency ▲ 41.02% for 10 sec.
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
    character_name="Makima",
    skill1=(
        SkillEffect(
            description=(
                "Every 20 hits taken: all allies Reload +36.96% and "
                "DEF +14.78% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                every_n_hits=20,
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=36.96,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.78,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 120 normal attacks: self Attract — taunts all "
                "enemies 3 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=3.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On lethal damage: self indomitability 7 sec; burst "
                "CD -11.58 sec. 1x/battle."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="lethal damage; 1x per battle",
                notes="DSL gap — no per-battle cap",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=7.0,
                    notes=(
                        "actually 'indomitability for 7 sec' — DSL "
                        "has no INDOMITABILITY effect kind. 0-mag "
                        "BUFF_DEFENSE with note flag."
                    ),
                ),
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=11.58,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Pierce 10 sec; lifesteal 34.02% of damage "
                "as HP. During indomitability: HP Potency +41.02% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.402,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'recover 34.02% of attack damage as "
                        "HP' — lifesteal. DSL has no LIFESTEAL kind. "
                        "HEAL_PER_SECOND proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=41.02,
                    duration_seconds=10.0,
                    notes=(
                        "'HP Potency +41.02%' — heal-amplifier; "
                        "indomitability conditional. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Makima is a self-sustaining tanky B2 — indomitability + "
        "lifesteal + Pierce burst makes her a reliable defense pivot "
        "that converts damage taken into pressure on the opposing "
        "team."
    ),
)
register_character(_SKILL)
