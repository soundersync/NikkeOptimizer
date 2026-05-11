"""Sakura Suzuhara — B1 Water SMG Abnormal. Healer-support B1.

Encoded from the live ``Character`` skill descriptions in the DB.
Sakura's kit is healing-amp + damage-taken-debuff on lowest-HP allies,
plus a sustained heal-per-second burst. A budget Helm/Tia adjacent.

**Source description (S1)**:

    Activates after landing 120 normal attacks. Affects the target(s).
    Damage Taken ▲ 17.18% for 5 sec.

**Source description (S2)**:

    Activates after landing 60 normal attack(s). Effects 2 ally unit(s)
    with the lowest HP percentage. Potency of HP restored ▲ 15.18% for
    10 sec.
    Activates after landing 120 normal attack(s). Effects 2 ally unit(s)
    with the lowest HP percentage. Damage Taken ▼ 14.97% for 10 sec.

**Source description (Burst)**:

    Affects 2 ally unit(s) with the lowest HP percentage. Recovers
    10.03% of caster's final Max HP every Sec for 10 sec.
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
    character_name="Sakura Suzuhara",
    skill1=(
        SkillEffect(
            description=(
                "Every 120 normal attacks: target takes +17.18% damage "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=17.18,
                    duration_seconds=5.0,
                    notes="'Damage Taken ▲' approximated as DEF debuff",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 60 normal attacks: 2 lowest-HP allies get "
                "Potency of HP restored +15.18% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=60),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=2),
                    magnitude=15.18,
                    duration_seconds=10.0,
                    notes=(
                        "'Potency of HP restored' — healing amplifier; "
                        "DSL has no BUFF_HEAL_AMP kind; encoded as BUFF_HP."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 120 normal attacks: 2 lowest-HP allies take "
                "-14.97% damage for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=2),
                    magnitude=14.97,
                    duration_seconds=10.0,
                    notes="'Damage Taken ▼' approximated as DEF buff",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 2 lowest-HP allies recover 10.03% of Sakura's "
                "Max HP every sec for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=2),
                    magnitude=10.03,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Sakura is a B1 SMG support — periodic heal + damage-taken "
        "debuff on the lowest-HP allies. Strong in Anomaly-heavy comps."
    ),
)
register_character(_SKILL)
