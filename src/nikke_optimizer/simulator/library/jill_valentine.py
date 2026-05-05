"""Jill Valentine — B3 Electric AR Abnormal (Resident Evil collab).

Encoded from the live ``Character`` skill descriptions in the DB. Jill's
identity is the dual ammo system — Magnum Ammo (+30% damage 9 rounds
post-reload) and Acid Ammo (192% sustained damage DOT for 30 sec on
first round of reload). Burst caps with a forced reload + true-damage
sustained barrage.

**Source description (S1)**:

    Activates at the start of battle and upon reloading to Max
    Ammunition. Affects self.
    Magnum Ammo: Normal Attack Damage Multiplier ▲ 30% for 9 rounds.

    Activates when using Burst Skill. Affects self.
    True Damage ▲ 34.99% for 10 sec.

**Source description (S2)**:

    Activates at the start of battle and upon reloading to Max
    Ammunition. Affects self.
    Acid Ammo Function: Upon reloading to Max Ammunition, only the
    first round deals sustained damage to the target.
    Effect: Deals 192% of final ATK as sustained damage every 1 sec
    for 30 sec.

    Activates when entering Full Burst. Affects self.
    ATK ▲ 40.03% for 10 sec.

**Source description (Burst)**:

    Affects self. Fixes reloading speed at 99.96% increase for 10 sec.
    Removes 100% of bullets. Forced Reload.
    Hit Rate +80.78% for 10 sec.
    Attack Damage +75% for 10 sec.
    Normal attacks deal True Damage for 10 sec.
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
    character_name="Jill Valentine",
    skill1=(
        SkillEffect(
            description=(
                "Battle start + on max-ammo reload: self Magnum Ammo "
                "— Normal Attack Damage +30% for 9 rounds."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=30.0,
                    duration_seconds=9.0,
                    notes=(
                        "'Normal Attack Damage Multiplier +30% for 9 "
                        "rounds' — round-bound, encoded as 9-sec proxy"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use: self True Damage +34.99% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=34.99,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start + on max-ammo reload: self Acid Ammo "
                "— next shot inflicts 192% DOT/sec for 30 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.92,
                    duration_seconds=30.0,
                    notes=(
                        "Acid Ammo DOT — 192% per sec for 30 sec on "
                        "first-round-after-reload target."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: self ATK +40.03% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.03,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self forced reload, Reload Speed +99.96%, "
                "Hit Rate +80.78%, Attack Damage +75%, normals deal "
                "true damage — all for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=99.96,
                    duration_seconds=10.0,
                    notes="forced reload empties + refills magazine instantly",
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=80.78,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=75.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes=(
                        "'normal attacks deal True Damage for 10 sec' "
                        "— full true-damage conversion (+100%) for "
                        "burst window"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Jill is the RE collab true-damage AR carry — burst forces a "
        "reload (refreshing both Magnum Ammo's +30% and Acid Ammo's "
        "DOT), then converts normals to true damage for 10 sec. The "
        "DOT alone caps at 192% × 30 = 5760% over 30 sec from a "
        "single first-round-of-reload shot."
    ),
)
register_character(_SKILL)
