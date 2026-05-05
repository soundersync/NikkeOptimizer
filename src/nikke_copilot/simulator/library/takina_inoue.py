"""Takina Inoue — B2 Iron SR Abnormal (Lycoris Recoil collab).

Encoded from the live ``Character`` skill descriptions in the DB. Takina
pairs with Chisato — her burst weapon-changes to a true-damage rifle,
and her S2 stuns + amplifies team true damage. Strong in true-damage-
leaning team comps.

**Source description (S1)**:

    Activates at the start of battle and when Full Burst ends.
    Affects self. ATK ▲ 80.04% for 5 sec.

    Activates when entering Full Burst. Affects self.
    True Damage ▲ 35.05% for 15 sec.

**Source description (S2)**:

    Affects all enemies. Damage Taken ▲ 10.09% for 5 sec.
    Stuns for 2 sec.

    Affects all allies. True Damage ▲ 140.49% for 10 sec.

**Source description (Burst)**:

    Affects self. Changes the weapon in use.
        Damage: 200.64% of final ATK.
        Duration: 10 sec.

    Additional Effects:
        Affects self: Normal attacks deal true damage for 10 sec.
        Affects targets hit: Damage Taken ▲ 6.04% for 5 sec.
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
    character_name="Takina Inoue",
    skill1=(
        SkillEffect(
            description=(
                "Battle start + on Full Burst end: self ATK +80.04% "
                "for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=80.04,
                    duration_seconds=5.0,
                    notes="also fires on Full Burst end — DSL multi-trigger gap",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: self True Damage +35.05% 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=35.05,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: all enemies Damage Taken +10.09% 5 sec, "
                "stun 2 sec; all allies True Damage +140.49% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=10.09,
                    duration_seconds=5.0,
                    notes="'Damage Taken +10.09%' — DEBUFF_DEFENSE proxy",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=2.0,
                    notes="actually 'Stuns for 2 sec' — DSL no STUN kind",
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=140.49,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon change for 10 sec (200.64% per "
                "shot, normals are true damage); targets hit take "
                "+6.04% Damage Taken 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=2.0064,
                    notes=(
                        "weapon-change per-shot damage. DSL has no "
                        "WEAPON_CHANGE kind; encoded as single damage "
                        "instance — simulator must amortize over 10 sec."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes=(
                        "'normal attacks deal true damage for 10 sec' — "
                        "encoded as full true-damage conversion (+100%) "
                        "for the burst window."
                    ),
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=6.04,
                    duration_seconds=5.0,
                    notes="'Damage Taken +6.04%' on targets hit — DEBUFF_DEFENSE proxy",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Takina is the Lycoris true-damage carry — pairs natively "
        "with Chisato (collab partner). Burst weapon-change converts "
        "her normals to true damage for 10 sec, while S2 stuns + amps "
        "team true damage. Hard counter to high-DEF defenders."
    ),
)
register_character(_SKILL)
