"""Eve — B3 Iron AR Abnormal (NIKKE × NIKKE Eve collab).

Encoded from the live ``Character`` skill descriptions in the DB. Eve's
identity is the dual Exospine system: Impact-Type (crit + Unstable
Energy sequential nuke) and Eagle Eye-Type (continuous ATK + Ammo).
Burst Mk2 doubles both Exospine multipliers.

**Source description (S1)**:

    Activates when entering battle. Affects self.
    Impact-Type Exospine: Critical rate ▲ 60% continuously.

    Activates when landing 44 critical hits. Affects random enemy.
    Unstable Energy: Deals 240% of final ATK as damage.
    Attacks sequentially for 3 times.

    Activates when Unstable Energy hits the target.
    Affects the target if they belong to Electric Code.
    Damage taken ▲ 10% for 10 sec.

**Source description (S2)**:

    Activates when entering battle. Affects self.
    Eagle Eye-Type Exospine: ATK ▲ 50% of caster's ATK continuously.
    Max Ammunition Capacity ▲ 25% continuously.

    Activates when landing 10 normal attacks. Affects self if target
    belongs to Electric Code. Reloads 3 rounds.

**Source description (Burst)**:

    Affects random enemy. Deals 457.14% of final ATK as damage.
    Attacks sequentially for 6 times.

    Affects self. Exospine Mk2.
    Function: Enhance Exospine. Lasts for: 10 sec.
    Triggers Impact-Type Exospine Mk2.
        Effect: Damage multiplier of Unstable Energy sequential
        attacks is scaled by 100%.
    Triggers Eagle Eye-Type Exospine Mk2.
        Effect: Damage multiplier of Eagle Eye-Type Exospine is
        scaled by 100%.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Eve",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: self Impact-Type Exospine — Crit Rate "
                "+60% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.0,
                    duration_seconds=999.0,
                    notes="'Impact-Type Exospine' state — undispellable",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 44 crit hits: random enemy takes 240% sequential "
                "damage 3 times (Unstable Energy)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=44,
                condition="critical hits",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=3),
                    magnitude=2.4,
                    notes=(
                        "'Attacks sequentially for 3 times' — encoded as "
                        "3-target proxy; simulator may need to resolve "
                        "as 3 sequential single-target hits on same enemy."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Unstable Energy hit (Electric-code target): target "
                "Damage Taken +10% 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Unstable Energy hits Electric-code enemy",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=10.0,
                    duration_seconds=10.0,
                    notes="Electric-code only — DSL gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: self Eagle Eye-Type Exospine — ATK "
                "+50% of caster's ATK and Max Ammo +25% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=50.0,
                    duration_seconds=999.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="'Eagle Eye-Type Exospine' state — undispellable",
                ),
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=25.0,
                    duration_seconds=999.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 10 normal attacks (Electric-code target): self "
                "reload 3 rounds."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=10,
                condition="target is Electric-code",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=0.1,
                    notes=(
                        "actually 'Reload 3 rounds' — DSL has no flat-"
                        "rounds reload kind. Captured as 100% reload buff."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: random enemy takes 457.14% × 6 sequential; "
                "self Exospine Mk2 — both Exospine multipliers ×2 "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=6),
                    magnitude=4.5714,
                    notes=(
                        "'Attacks sequentially for 6 times' — encoded as "
                        "6-target proxy."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes=(
                        "Impact-Type Exospine Mk2: Unstable Energy "
                        "sequential damage ×2 (encoded as +100% ATK proxy). "
                        "DSL has no skill-multiplier scaling."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes=(
                        "Eagle Eye-Type Exospine Mk2: Eagle Eye damage "
                        "×2 (encoded as +100% ATK proxy)."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Eve is the dual-Exospine NIKKE × NIKKE collab carry — Impact-"
        "Type drives 60% Crit + Unstable Energy AOE-style sequential "
        "nukes; Eagle Eye-Type drives flat ATK/Ammo. Burst doubles "
        "both for 10 sec. Pairs natively with Electric-code teams "
        "(Helm: Aquamarine, Snow White: Heavy Arms, Anis: Star)."
    ),
)
register_character(_SKILL)
