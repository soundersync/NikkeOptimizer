"""Anis: Sparkling Summer — B3 Electric SG Tetra. Tetra-code attack buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Anis: Sparkling Summer's value comes from her S1 ATK + Reload buff to
Electric-code allies (gates her into a code-locked team), plus a
last-bullet 2-target nuke from S2.

**Source description (S1)**:

    Activates when entering Full Burst. Affects all Electric Code allies.
    ATK ▲ 55.31% of caster's ATK, lasts for 10 sec.
    Reloading Speed ▲ 49.28% for 10 sec.

**Source description (S2)**:

    Activates when firing the last bullet. Affects 2 enemy units(s)
    with the highest ATK.
    Deals 382.42% of final ATK as damage.

    Activates when firing the last bullet. Affects self.
    Damage to Interruption Parts ▲ 6.91% for 10 seconds.

**Source description (Burst)**:

    Affects self.
    Max Ammunition Capacity ▼ 73.92% for 10 sec.
    Reloading Speed ▲ 27.72% for 10 sec.
    Damage as strong element ▲ 42.24% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Anis: Sparkling Summer",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all Electric-code allies ATK "
                "+55.31% and Reload +49.28% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=55.31,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=49.28,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On last bullet: deals 382.42% of ATK to the 2 highest-ATK "
                "enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP, count=2),
                    magnitude=3.8242,
                    notes="actually 'highest ATK'; ENEMY_HIGHEST_HP proxy in PvP",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On last bullet: self 'Damage to Interruption Parts' "
                "+6.91% for 10 sec (PvE-only)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.91,
                    duration_seconds=10.0,
                    notes="'Damage to Interruption Parts' — PvE-only",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Max Ammo -73.92%, Reload +27.72%, "
                "strong-element damage +42.24% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=27.72,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=42.24,
                    duration_seconds=10.0,
                    notes="actually 'Damage as strong element'; only vs weak elements",
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Max Ammo -73.92%' — debuff, but the "
                        "reduced ammo + reload speed lets her fire faster"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Anis: Sparkling Summer slots into Electric-code attack comps "
        "where her S1 ATK buff applies. Outside of code-matched teams "
        "she's a tier-2 alt B3."
    ),
)
register_character(_SKILL)
