"""Asuka Shikinami Langley — B3 Fire AR Abnormal hyper-DPS / shield-breaker.

Encoded from the live ``Character`` skill descriptions in the DB.
Asuka's signature is the 601% shield damage multiplier (PvP shield
breaker) plus a long 25-sec self-Pierce window on burst. She's a
flexible top-tier B3 attacker that slots into both Crown comps and
SBS comps depending on match-up.

**Source description (S1)**:

    Activates at the start of the battle. Affects self.
    Damage dealt to Shield ▲ 601.01% continuously.
    (It only affects the damage dealt to the shield, not to the Rapture itself)

    Activates when recovery takes effect. Affects self.
    ATK ▲ 96.98% for 25 sec.

**Source description (S2)**:

    Activates when entering Full Burst. Affects self when in Shield
    status. Damage as strong element ▲ 30.02% for 10 sec.

    Activates when entering Full Burst. Affects all Fire Code allies.
    Damage dealt when attacking core ▲ 60.07% for 10 sec.

**Source description (Burst)**:

    Affects self. Gain Pierce for 25 sec.
    Attack damage ▲ 150.04% for 10 sec.
    Recovers 3.16% of attack damage as HP over 10 sec.
    Hit Rate ▲ 101.37% for 10 sec.

**DSL gaps**:

  * "Damage dealt to Shield +601.01%" — anti-shield-only multiplier;
    DSL has no SHIELD_DAMAGE_MULTIPLIER. Encoded as a note. Critical
    for shield-break matchups.
  * "Damage as strong element" — element-advantage damage bonus,
    distinct from BUFF_ELEMENT_DAMAGE which is unconditional.
  * "Fire Code allies" — manufacturer/code filter on target — DSL has
    no manufacturer-class filter (similar gap to D:KW's SR-only).
  * "When recovery takes effect" — triggers on any healing applied to
    Asuka (e.g. by Tia, Naga, Helm). Encoded as CONDITIONAL.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Asuka Shikinami Langley",
    skill1=(
        SkillEffect(
            description=(
                "On battle start: self anti-shield damage +601.01% "
                "continuously (shield damage only, NOT damage to the "
                "underlying enemy)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SHIELD_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=601.01,
                    duration_seconds=86400.0,
                    notes=(
                        "'Damage dealt to Shield +601.01%' — anti-Helm "
                        "/ anti-Centi shield-break mechanic"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When healing is applied to Asuka: self ATK +96.98% "
                "for 25 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any healing effect applied to Asuka",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=96.98,
                    duration_seconds=25.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry while Asuka has a shield: self "
                "strong-element damage +30.02% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="Asuka has an active shield",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.02,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Damage as strong element' — only "
                        "applies vs element-weak enemies. Conditional "
                        "on shield (often Crown burst provides it)."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: all Fire-code allies 'damage to "
                "core' +60.07% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CORE_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.FIRE,
                    ),
                    magnitude=60.07,
                    duration_seconds=10.0,
                    notes="'damage to core' — boss-leaning stat",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Pierce 25s, attack damage +150.04% 10s, "
                "lifesteal 3.16% of attack damage, Hit Rate +101.37% 10s."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=25.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=150.04,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.316,  # 3.16% / 10s proxy
                    duration_seconds=10.0,
                    notes=(
                        "lifesteal: 3.16% of attack damage as HP. The "
                        "Pierce + lifesteal combo is what lets her "
                        "self-sustain through burst windows."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=101.37,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Asuka is the canonical anti-shield meta attacker — her S1 "
        "601% shield-damage multiplier breaks Helm/Centi/Blanc walls "
        "more efficiently than D:KW does. Her S1 second clause "
        "(ATK +96.98% on healing) makes her synergize with any healer "
        "on the team (Tia, Naga, Helm burst, Blanc burst, etc.)."
    ),
)
register_character(_SKILL)
