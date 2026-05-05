"""Sin — B2 Electric AR Missilis. Cumulative-tier self-buff defender.

Encoded from the live ``Character`` skill descriptions in the DB. Sin's
identity is the cumulative burst-use tier (1st: lifesteal, 2nd: HP
Potency, 3rd: DEF) — she gets sturdier as the rotation progresses.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects self.
    Duplicate 15.03% HP of ally with the highest HP, lasts for 5 sec.
    Attract: Taunt all enemies for 5 sec.

**Source description (S2)**:

    Activates after the Full Burst ends. Affects self.
    Burst gauge loading speed ▲ 16.17% for 5 sec.

    Activates when using Burst Skill. Affects self.
    Effect changes according to the number of activation time(s).
    Previous effects trigger repeatedly:
        Once:    Recovers 15.3% of ATK damage as HP, lasts for 5 sec.
        Twice:   HP Potency ▲ 51% for 5 sec.
        Thrice:  DEF ▲ 43.2% for 5 sec.

**Source description (Burst)**:

    Activates when enemy unit(s) (excluding Nikkes) are more than 4.
    Affects all enemies. Damage Taken ▲ 12.23% for 5 sec.

    Affects enemies within attack range. Deals 176.32% of final ATK
    as damage.
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
    character_name="Sin",
    skill1=(
        SkillEffect(
            description=(
                "On last bullet: self Max HP +15.03% (mirror of "
                "highest-HP ally) for 5 sec; Attract — taunts all "
                "enemies 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.03,
                    duration_seconds=5.0,
                    notes=(
                        "actually '15.03% HP of highest-HP ally' — "
                        "cross-stat scaling. DSL gap; encoded as flat "
                        "BUFF_HP."
                    ),
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst end: self Burst gauge gain +16.17% "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=16.17,
                    notes=(
                        "actually 'Burst gauge loading speed +16.17% "
                        "for 5 sec' — DSL has no BURST_GEN_RATE; "
                        "GAIN_BURST_GAUGE proxy."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Cumulative on burst use (3rd-tier): self DEF +43.2% "
                "for 5 sec; tiers 1+2 also active."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                notes="cumulative activation — encodes 3rd-tier value",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.53,
                    duration_seconds=5.0,
                    notes=(
                        "tier 1: 'Recovers 15.3% of attack damage as "
                        "HP' — lifesteal. DSL gap; HEAL_PER_SECOND proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=51.0,
                    duration_seconds=5.0,
                    notes="tier 2: 'HP Potency +51%' — heal-amplifier",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=43.2,
                    duration_seconds=5.0,
                    notes="tier 3 (cumulative): DEF +43.2%",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: enemies in range take 176.32%; if >4 non-Nikke "
                "enemies, all enemies take +12.23% Damage Taken 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.7632,
                    notes="actually 'enemies within attack range' — proxy",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=12.23,
                    duration_seconds=5.0,
                    notes=(
                        "'>4 non-Nikke enemies' conditional — almost "
                        "always inactive in 1v1 PvP (5v5), captured "
                        "as note flag for the simulator to filter."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Sin is a cumulative-tier defender — gets sturdier each burst "
        "rotation (1st: lifesteal, 2nd: HP Potency, 3rd: DEF). Her "
        "burst's >4-enemies conditional is a PvE optimization — almost "
        "always inactive in 5v5 PvP."
    ),
)
register_character(_SKILL)
