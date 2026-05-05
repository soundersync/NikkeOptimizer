"""Anchor: Innocent Maid — B2 Water RL Elysion. Cumulative team buffer + Storage healer.

Encoded from the live ``Character`` skill descriptions in the DB.
Anchor: IM uses the cumulative-activation pattern with three buff
tiers per skill, plus Marciana-style Storage on burst.

**Source description (S1)** (cumulative; squad-conditional regen):

    On Full Burst entry: all allies — three-tier cumulative buffs.
        Once: HP Potency +30.96% for 5 sec.
        Twice: Distributed Damage +30.4% for 10 sec.
        Three times: Stack count of debuffs -1.

    On Full Burst entry with same-squad ally on field: all allies
    recover 3.04% max HP/sec for 8 sec.

**Source description (S2)** (cumulative):

    After Full Burst ends: all allies — three-tier cumulative buffs.
        Once: Hit Rate +10.13% for 10 sec.
        Twice: ATK +35.02% of caster's ATK for 10 sec.
        Three times: Reloading Speed +40.04% for 15 sec.

**Source description (Burst)**:

    Affects all allies. Storage: heal-overflow banked up to 60.19% of
    caster's max HP for 25 sec. Recovers 40.18% of caster's max HP.
    ATK +30.09% of caster's ATK for 10 sec.
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
    character_name="Anchor: Innocent Maid",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all allies — third-tier cumulative "
                "(Distributed Damage +30.4% 10s; debuff -1 stack count). "
                "Earlier tiers added HP Potency."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                notes="cumulative activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.4,
                    duration_seconds=10.0,
                    notes="Distributed Damage tier; ATK proxy",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry with same-squad ally on field: all "
                "allies regen 3.04% max HP/sec for 8 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="same-squad ally on field",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.04,
                    duration_seconds=8.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst end: cumulative third-tier buffs — Reload "
                "Speed +40.04% (15s) + earlier-tier ATK +35.02% (10s) + "
                "Hit Rate +10.13% (10s)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_END,
                notes="cumulative activation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.04,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=35.02,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.13,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Storage (heal overflow up to 60.19% "
                "for 25s) + 40.18% max-HP heal + ATK +30.09% (10s)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=60.19,
                    duration_seconds=25.0,
                    notes="Storage (heal overflow buffer); same as Marciana burst",
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.18,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=30.09,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Anchor: IM combines Marciana-style Storage healing with "
        "cumulative team buffs (Liter-style scaling). Excellent in "
        "PvP defense / hybrid comps."
    ),
)
register_character(_SKILL)
