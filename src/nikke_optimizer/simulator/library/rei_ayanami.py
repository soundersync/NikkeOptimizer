"""Rei Ayanami — B3 Fire MG Abnormal NERV (Evangelion collab, base form).

Encoded from the live ``Character`` skill descriptions in the DB.
Base Rei Ayanami is the Fire MG Eva collab carry — passive 700.5%
Shield damage scaling makes her a dedicated shield-shredder, and her
burst combines a Fire-allies Shield + Attack Damage buff with a
990.2% AOE nuke. Distinct from Rei Ayanami (Tentative Name), the
Wind AR Annihilation State variant.

**Source description (S1)**:

    Every 100 normal attacks: self damage as strong element +30.23%
        for 3 sec.
    Every 100 normal attacks: nearest enemy in attack range, 112.37%
        ATK as additional damage.

**Source description (S2)**:

    Battle start: self damage dealt to Shield 700.5% continuously
        (shield only, not Rapture).
    On entering Burst stage 3: all Fire Code allies, ATK +25.03% of
        caster's ATK for 10 sec.

**Source description (Burst)**:

    All Fire Code allies: shield 13.44% of caster max HP for 10 sec.
        Attack damage +48.02% for 10 sec.
    All enemies: 990.2% ATK as damage.
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
    character_name="Rei Ayanami",
    skill1=(
        SkillEffect(
            description=(
                "Every 100 normal attacks: self Elemental Advantage "
                "damage +30.23% for 3 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=100),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.23,
                    duration_seconds=3.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 100 normal attacks: nearest enemy in attack "
                "range takes 112.37% ATK as additional damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=100),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_FRONT),
                    magnitude=1.1237,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self Damage to Shield +700.5% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SHIELD_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=700.5,
                    duration_seconds=999.0,
                    notes="shield-only damage amp (not vs Rapture core)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On entering Burst stage 3: Fire allies ATK +25.03% of "
                "caster's ATK for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="team enters Burst stage 3 (B3 fired)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.FIRE,
                    ),
                    magnitude=25.03,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: Fire allies shield 13.44% caster max HP + "
                "Attack Damage +48.02% 10 sec; all enemies take 990.2% ATK."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.FIRE,
                    ),
                    magnitude=13.44,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.FIRE,
                    ),
                    magnitude=48.02,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=9.902,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire MG B3 Eva-collab carry — base form. Massive 700.5% "
        "shield-damage passive makes her the premier shield-shredder; "
        "burst contributes a Fire-only team Attack Damage buff + "
        "shield + 990.2% AOE nuke. Distinct from Rei Ayanami "
        "(Tentative Name) which is Wind AR + Annihilation State."
    ),
)
register_character(_SKILL)
