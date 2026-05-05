"""Naga — B2 Electric SG buffer/healer, Missilis. Tia's burst-gen partner.

Encoded from the live ``Character`` skill descriptions in the DB.
Naga's cover heal is what enables the Tia/Naga burst-gen loop, and
her on-shield-apply triggers stack with Crown's burst-shield to
amplify damage.

**Source description (S1)**:

    Activates after 12 normal attack(s). Affects all allies.
    Recovery of Cover's HP ▲ 14.57%.

    Activates when applying Shield. Affects all allies.
    Damage dealt when attacking core ▲ 85.17% for 10 sec.

**Source description (S2)**:

    Activates after 5 normal attack(s). Affects 2 ally unit(s) with
    the highest ATK. Damage dealt when attacking core ▲ 40.07% for 5 sec.

    Activates after 5 normal attack(s). Affects 2 ally unit(s) with
    the lowest HP percentage. Recovers 9.58% of the caster's final
    Max HP as HP.

**Source description (Burst)**:

    Affects self. Gain Pierce for 10 sec.

    Affects all allies. ATK ▲ 16.18% of caster's ATK for 10 sec.

    Activates when applying Shield. Affects all allies.
    ATK ▲ 31.02% of caster's ATK for 10 sec.

**DSL gaps**:

  * "Damage dealt when attacking core" is a niche stat (boss core
    damage); encoded as BUFF_ATK with a note.
  * "Cover's HP recovery" is the trigger that drives Tia's S1 — the
    simulator must connect Naga's S1 to Tia's S1 across characters.
  * On-shield-apply triggers (S1 second clause + Burst third clause)
    fire when ANY ally applies a shield to the team (e.g. Crown's
    burst, Centi's S2). Encoded as CONDITIONAL.
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
    character_name="Naga",
    skill1=(
        SkillEffect(
            description=(
                "Every 12 normal attacks: all allies Cover-HP recovery "
                "+14.57%. Drives the Tia/Naga burst-gen loop."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=12),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.57,
                    duration_seconds=1.0,
                    notes=(
                        "actually 'Recovery of Cover's HP +14.57%' — "
                        "instant cover heal, encoded as 1-sec pulse"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On any shield application (e.g. Crown burst, Centi S2): "
                "all allies 'damage dealt to core' +85.17% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any ally has shield applied",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CORE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=85.17,
                    duration_seconds=10.0,
                    notes="PvE-leaning stat; also relevant on PvP boss-style enemies",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 5 normal attacks: top-2 ATK allies get core damage "
                "+40.07% for 5 sec; bottom-2 HP allies recover 9.58% max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CORE_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=40.07,
                    duration_seconds=5.0,
                    notes=(
                        "actually 2 highest-ATK allies (ALLY_HIGHEST_ATK "
                        "doesn't honor count yet)"
                    ),
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=2),
                    magnitude=9.58,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Pierce 10s, all allies ATK +16.18% for 10s. "
                "Plus on-shield-apply: all allies ATK +31.02% for 10s "
                "(stacks with the base 16.18%)."
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
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=16.18,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=31.02,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "conditional on a shield being applied; pairs with "
                        "Crown burst (universal shield) for total +47.20% ATK"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Naga is the burst-gen partner to Tia AND the canonical "
        "shield-amplifier — her S1 second clause + Burst third clause "
        "both proc on shield application, so pairing her with Crown "
        "(universal shield burst) doubles down on team ATK."
    ),
)
register_character(_SKILL)
