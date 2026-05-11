"""Signal — Fire SMG B2, niche debuffer with self-sustain.

Encoded from the live ``Character`` skill descriptions in the DB.
Signal lays a small ATK/DEF debuff every 60 normal-attack hits and
contributes a burst-skill DEF shred plus a flat-damage payload. Modest
PvP relevance — more of a meme/PvE pick than a meta B2 — but encoded
for roster completeness.

**Source description (S1)**:

    ■ Affects enemy hit by 60 normal attack(s). DEF ▼ 5.94% for 5 sec.
    ATK ▼ 5.94% for 5 sec.

**Source description (S2)**:

    ■ Affects self. Cast when entering Full Burst. Recovers 44.08%
    of attack damage as HP over 10 sec.

**Source description (Burst)**:

    ■ Affects enemies within attack range. Deals 229.22% of final ATK
    as damage. DEF ▼ 12.34% for 10 sec.
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
    character_name="Signal",
    skill1=(
        SkillEffect(
            description=(
                "Every 60 normal-attack hits: target DEF -5.94% and "
                "ATK -5.94% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=5.94,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=5.94,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry: self recovers 44.08% of attack "
                "damage as HP over 10 sec (lifesteal)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=44.08,
                    duration_seconds=10.0,
                    notes=(
                        "actually % of attack damage dealt — lifesteal-"
                        "style; encoded as HEAL_PER_SECOND proxy"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: enemies in range take 229.22% of ATK and DEF "
                "-12.34% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.2922,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=12.34,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire SMG B2 — debuff-focused but with low magnitudes. Outshone "
        "by Crown / Blanc for B2 slot in PvP. Niche pick on Fire-element "
        "teams when no better B2 is available."
    ),
)
register_character(_SKILL)
