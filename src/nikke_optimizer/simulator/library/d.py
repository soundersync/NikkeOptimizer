"""D — B3 Wind SMG. Strong-element attacker with one-time team
burst-gauge fill on enemy appearance.

Encoded from the live ``Character`` skill descriptions in the DB.
D's identity is the on-target-appear payload: she immediately fills
team burst gauge by 98.56% (effectively launching a burst chain
within seconds) and grants herself 91.09% Damage as Strong Element.
Her burst grants Attacker allies +42.38% Parts Damage and extends
Full Burst Time by 5.04s if she has Stun immunity.

**Source description (S1)**:

    On entering Full Burst: self Damage as Strong Element +46.93% for 15s
    On entering Full Burst: self recovers 3.52% of ATK damage as HP for 15s
    On first activation: self recovers 16.5% of ATK damage as HP for 15s

**Source description (S2)**:

    On target appears (1×/battle): all allies fill Burst Gauge by 98.56%
    On target appears: self Stun Immunity for 36.95 sec
    On target appears: self Damage as Strong Element +91.09% for 15s

**Source description (Burst)**:

    All enemies: 426.24% of final ATK damage
    Attacker allies: Parts Damage +42.38% for 15s
    All allies (if caster has Stun Immunity): Full Burst Time +5.04s
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Role,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="D",
    skill1=(
        SkillEffect(
            description="On FB entry: self Damage as Strong Element +46.93% 15s + lifesteal",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=46.93,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.52,
                    duration_seconds=15.0,
                    notes="3.52% of ATK damage as HP — lifesteal-style",
                ),
            ),
        ),
        SkillEffect(
            description="On 1st activation: self lifesteal 16.5% of ATK damage 15s",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="first activation only",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=16.5,
                    duration_seconds=15.0,
                    notes="one-shot lifesteal trigger",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On target appears (1×): all allies fill Burst Gauge 98.56%",
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                condition="1st target appearance, once per battle",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=98.56,
                ),
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.SELF),
                    duration_seconds=36.95,
                    notes="Stun Immunity for 36.95s — captured as CLEANSE proxy",
                ),
            ),
        ),
        SkillEffect(
            description="On target appears: self Damage as Strong Element +91.09% 15s",
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                condition="1st target appearance",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=91.09,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all enemies 426.24% damage",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.2624,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.ATTACKER,
                    ),
                    magnitude=42.38,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=5.04,
                    notes=(
                        "FBT extension +5.04s if caster has Stun Immunity. "
                        "DSL gap (FB_TIME_EXT) — duration captures the +5.04s."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SMG B3 attacker. Premier opener — instant team burst gauge "
        "fill via S2 effectively gives the team a free first burst chain. "
        "Burst grants Attacker allies +42.38% Parts Damage. Strong vs "
        "Iron-element defenders (Wind > Iron)."
    ),
)
register_character(_SKILL)
