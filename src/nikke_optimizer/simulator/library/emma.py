"""Emma — B1 Fire MG Elysion Absolute. Pure healer / HP-potency.

Encoded from the live ``Character`` skill descriptions in the DB. Base
Emma is a low-frill defensive B1: chance-on-hit team heal, passive HP-
recovery-potency buff while above 90% HP, and a burst combining a flat
team heal with attack-damage lifesteal. Distinct from Emma: Tactical
Upgrade (B1 Fire MG, the meta supporter form).

**Source description (S1)**:

    5% chance when attacked. Affects all allies.
    Restore HP equal to 10.77% of caster's final Max HP.

**Source description (S2)**:

    Active when HP > 90%. Affects all allies.
    HP Recovery ▲ 13.33% permanently.

**Source description (Burst)**:

    All allies recover 39.6% of caster's Max HP. Also recovers 39.6%
    of attack damage as HP over 5 sec.
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
    character_name="Emma",
    skill1=(
        SkillEffect(
            description=(
                "5% chance on damage taken: all allies recover 10.77% "
                "of Emma's max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="5% chance",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.77,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "While Emma HP > 90%: all allies HP Recovery +13.33% "
                "permanently."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="self HP > 90%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=999.0,
                    notes=(
                        "HP Recovery +13.33% — modifier on incoming "
                        "heal potency, not a heal-per-second. DSL gap "
                        "(no HEAL_POTENCY modifier kind); 0-mag flag."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies recover 39.6% of caster's max HP + "
                "39.6% of attack damage as HP over 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=39.6,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=39.6,
                    duration_seconds=5.0,
                    notes=(
                        "actually '39.6% of attack damage as HP over "
                        "5 sec' — lifesteal-style. DSL has no LIFESTEAL "
                        "kind; encoded as proxy regen."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Base Emma is a low-investment Fire MG B1 healer — chance "
        "proc team heal + passive HP-recovery-potency buff + 39.6% "
        "burst heal. Severely outshone by Emma: Tactical Upgrade for "
        "PvP, but viable in low-stage PvE."
    ),
)
register_character(_SKILL)
