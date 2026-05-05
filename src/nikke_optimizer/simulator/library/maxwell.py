"""Maxwell — B3 Iron SR Missilis. Charge-Speed support carry.

Encoded from the live ``Character`` skill descriptions in the DB.
Maxwell's burst transforms her weapon into a Pierce sniper rifle with
massive Full Charge multiplier — pairs naturally with attackers that
benefit from Charge Speed support (her S1 buffs the team's two
highest-ATK allies).

**Source description (S1)**:

    Activates when entering Full Burst. Affects 2 ally units with
    the highest ATK.
    Charge Speed ▲ 4.48% for 10 sec. ATK ▲ 43.1% for 10 sec.

**Source description (S2)**:

    Activates when there are above 5 enemy unit(s), excluding NIKKEs.
    Affects self. Critical Rate ▲ 4.83% Critical Damage ▲ 13.91%

**Source description (Burst)**:

    Affects self. Change the Weapon in use.
        Charge Time: 2 sec
        Damage: 813.42% of final ATK
        Full Charge Damage: 300% damage
        Max Ammunition Capacity: 1 round
        Additional Effect: Pierce
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
    character_name="Maxwell",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: top-2 ATK allies get Charge Speed "
                "+4.48% and ATK +43.1% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=4.48,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=43.1,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Activates above 5 enemies (PvE-only since PvP has 5): "
                "self Crit Rate +4.83%, Crit Damage +13.91%."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition=">5 enemies (effectively PvE-only)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=4.83,
                    duration_seconds=86400.0,
                    notes="conditional on >5 enemies; PvE has bosses with parts",
                ),
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.91,
                    duration_seconds=86400.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self weapon change for the burst window — fixed "
                "2-sec charge, 813.42% Damage, 300% Full Charge multiplier, "
                "Max Ammo 1, Pierce."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                ),
                # Weapon-change damage profile — encoded as a per-shot
                # DEAL_DAMAGE for the burst window. The simulator must
                # apply the 300% Full Charge multiplier separately.
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=8.1342,
                    notes=(
                        "weapon change: per-shot 813.42% of ATK, charge "
                        "2 sec, Full Charge applies 300% multiplier, "
                        "Max Ammo 1. Same DSL gap as Red Hood Step 3."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Maxwell's value is the team Charge Speed + ATK buff to top-2 "
        "ATK allies (S1) plus her own pierce + 813% per-shot weapon. "
        "Anti-shield through Pierce; pairs with Crown for +ATK stacking."
    ),
)
register_character(_SKILL)
