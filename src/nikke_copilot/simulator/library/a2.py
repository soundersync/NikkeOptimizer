"""A2 — B3 Fire RL Abnormal NieR collab. Mode B HP-burn carry.

Encoded from the live ``Character`` skill descriptions in the DB.
A2's identity is Mode B — her burst trades HP for ATK and Charge
Speed, making her a high-risk high-reward attacker that pairs well
with healers (Tia, Naga, Helm burst, Blanc).

**Source description (S1)**:

    Activates when using Burst Skill. Affects self.
    Charge Damage ▲ 110.44% for 15 sec.
    Explosion Radius ▲ 100.74% for 15 sec.

**Source description (S2)**:

    Activates when hitting a target with Full Charge. Affects the target.
    Deals 30.1% of final ATK as additional damage.

    Activates when hitting a target with Full Charge. Affects self.
    Damage to Parts ▲ 40.88% for 3 sec.

**Source description (Burst)**:

    Affects self. Mode B: Own HP decreases every second while ATK and
    Charge Speed increase. If own HP dips below 40%, Mode B is deactivated.
        Effect 1: Current HP ▼ 3.99% every 1 sec.
        Effect 2: ATK ▲ 15.19%
        Effect 3: Charge Speed ▲ 35.88%
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
    character_name="A2",
    skill1=(
        SkillEffect(
            description=(
                "On burst: self Charge Damage +110.44%, Explosion Radius "
                "+100.74% for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=110.44,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.74,
                    duration_seconds=15.0,
                    notes="actually 'Explosion Radius' (RL-only stat); proxy",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge hit: target takes 30.1% additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge hit lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.301,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge hit: self Damage to Parts +40.88% for 3 sec "
                "(PvE-only stat)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge hit lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.88,
                    duration_seconds=3.0,
                    notes="PvE-only stat; near-zero PvP relevance",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: Mode B activates — self ATK +15.19%, Charge "
                "Speed +35.88%, but HP drains 3.99%/sec until below 40%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.19,
                    duration_seconds=86400.0,
                    notes=(
                        "Mode B continuous until HP < 40% — duration is "
                        "really 'until self-deactivation'"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=35.88,
                    duration_seconds=86400.0,
                    notes="active during Mode B",
                ),
                # Self HP drain — DSL has no SELF_DAMAGE kind. Captured
                # as a note on a placeholder.
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes=(
                        "Mode B HP drain: 3.99%/sec self-damage. DSL gap "
                        "(SELF_DAMAGE_OVER_TIME)."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "A2's Mode B is the canonical 'use a healer' enabler — her "
        "burst becomes self-sustaining if combined with a Tia/Naga/Helm "
        "type. Without one, the 3.99%/sec drain ends Mode B fast. "
        "Pairs with Asuka's S1 (ATK +96.98% on healing applied to self) "
        "for double-collab synergies."
    ),
)
register_character(_SKILL)
