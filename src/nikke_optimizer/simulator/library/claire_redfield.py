"""Claire Redfield — B1 Electric RL Abnormal (Resident Evil collab).

Encoded from the live ``Character`` skill descriptions in the DB. Claire
is a B1 Healer-Adventure pivot — Green Herb single-target heal, Blue
Herb on-burst team shield, on-burst team heal + cleanse.

**Source description (S1)**:

    Activates when landing 3 Full Charge attacks. Affects 2 ally units
    with the highest final ATK. Green Herb: Recovers 2.88% of caster's
    final max HP as HP.

**Source description (S2)**:

    Activates when using Burst Skill. Affects all allies.
    Blue Herb: Generates a shield with 10.13% of caster's final Max HP
    for 10 sec.

**Source description (Burst)**:

    Affects all allies. Recovers 34.35% of caster's final max HP as HP.
    Dispels 1 debuff.
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
    character_name="Claire Redfield",
    skill1=(
        SkillEffect(
            description=(
                "Every 3 full charge attacks: 2 highest-ATK allies "
                "Green Herb heal 2.88% of caster Max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=3,
                condition="full charge attacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=2.88,
                    notes="actually '2 highest-ATK allies' — DSL single-target proxy",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On burst use: all allies Blue Herb shield = 10.13% "
                "of caster Max HP for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
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
                "Burst: all allies heal 34.35% of caster Max HP and "
                "dispel 1 debuff."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=34.35,
                ),
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.0,
                    notes="dispel 1 debuff",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Claire is the RE collab B1 healer — Green Herb single-target "
        "heal, Blue Herb on-burst team shield, on-burst team heal + "
        "1-debuff cleanse. Niche pick for cleansing-required content "
        "or as a tertiary healer alongside Helm or Marciana."
    ),
)
register_character(_SKILL)
