"""Drake (Treasure) — B3 Fire SG. Treasure-form SG-comp anchor.

Encoded from the live ``Character`` skill descriptions in the DB.
Drake's Treasure form is a true SG-comp linchpin: her S1 grants ATK
+63.88% AND Ammo +50.14% to all SG allies during Full Burst, her S2
hits low-HP enemies on a periodic ticker, and her burst is a 3009.6%
range attack with self ammo + attack-damage scaling.

**Source description (S1)**:

    On entering Full Burst: all allies — Hit Rate +20.09%, ATK +11.85% for 10s
    On entering Full Burst: all SG allies — ATK +63.88%, Max Ammo +50.14% for 10s

**Source description (S2)**:

    Every 10 normal attacks: 3 lowest-HP enemies — 98.55% damage
    Every 5 normal attacks: 1 lowest-HP enemy — 201.6% damage

**Source description (Burst)**:

    Enemies in attack range: 3009.6% of final ATK damage
    Self: Max Ammo +72.18%, Attack Damage +31.68% for 10s
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
    WeaponClass,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Drake (Treasure)",
    skill1=(
        SkillEffect(
            description="FB entry: all allies Hit Rate +20.09%, ATK +11.85% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.09,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.85,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description="FB entry: SG allies ATK +63.88%, Ammo +50.14% 10s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=63.88,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SG,
                    ),
                    magnitude=50.14,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Every 10 hits: 3 low-HP enemies 98.55% damage",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP, count=3),
                    magnitude=0.9855,
                ),
            ),
        ),
        SkillEffect(
            description="Every 5 hits: 1 low-HP enemy 201.6% damage",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP),
                    magnitude=2.016,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: enemies in range 3009.6% damage; self Ammo + Atk Dmg",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=30.096,
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=72.18,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=31.68,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Treasure-form Drake — SG comp anchor. SG-allies ATK +63.88% on "
        "FB entry is the headline buff; pairs with Leona, SBS (SG), "
        "Anis: SS, Privaty for SG-only comps. Burst is a 30x range payload."
    ),
)
register_character(_SKILL)
