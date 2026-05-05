"""Little Mermaid (Siren) — Wind SMG B1, burst-gen / debuffer.

Encoded from the live ``Character`` skill descriptions in the DB. LM:S
is a B1 SMG support that applies a "Bubble" debuff (damage-taken ▲ on
enemies) and feeds team burst gauge through ammo-counted triggers.

**Source description (S1)**:

    Activates only when in Focusing status. Affects all allies. Focuses
    fire continuously.
    Activates when Full Burst ends. Affects all allies. Cooldown of
    Burst Skill ▼ 7.48 sec.
    Activates when entering Full Burst. Affects all allies. Attack
    Damage ▲ 4% for 10 sec.
    Activates each time total ammo consumed by allies reaches 400.
    Affects all allies. Fills Burst Gauge by ▲ 37%.

**Source description (S2)**:

    Activates when the enemy appears. Affects the target. Bubble:
    Damage Taken ▲ 5.05% continuously.
    Activates after landing 50 normal attack(s). Affects the target if
    in Bubble status. Explosive Bubble: Damage Taken ▲ 5.05%
    continuously. Stuns for 3 sec. Removes Bubble.
    Activates every 1 sec only during Full Burst. Affects random enemy
    unit(s). Deals 63.36% of final ATK as damage. Attacks sequentially
    for 4 time(s).
    Activates each time total ammo consumed by allies reaches 500.
    Affects random enemy unit(s). Bubble Barrage: Deals 85% of final
    ATK as damage.

**Source description (Burst)**:

    Affects all allies. Attack Damage ▲ 10.13% for 10 sec. Reloads
    33.26% magazine(s).
    Affects self. ATK ▲ 17.28% of caster's ATK for 10 sec.
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
    character_name="Little Mermaid (Siren)",
    skill1=(
        SkillEffect(
            description=(
                "Full Burst end: all allies' burst skill cooldown -7.48 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.48,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Full Burst start: all allies Attack Damage +4% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=4.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 400 team-ammo: all allies +37% burst gauge."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=400),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=37.0,
                    notes="counter is total team ammo consumed, not per-Nikke",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On enemy spawn: target gains Bubble (Damage Taken +5.05% "
                "continuously)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="enemy spawns",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=5.05,
                    duration_seconds=86400.0,
                    notes="actually 'Damage Taken' debuff (DSL gap)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "After 50 normal attacks on a Bubbled target: Explosive "
                "Bubble (+5.05% damage taken stacks, stun 3 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=50),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=5.05,
                    duration_seconds=86400.0,
                    notes="actually Damage Taken; +3 sec stun, removes Bubble",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 1 sec during Full Burst: 63.36% ATK damage to "
                "random enemy, 4 sequential hits."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER, cooldown_seconds=1.0,
                condition="during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=4),
                    magnitude=0.6336,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Attack Damage +10.13% for 10 sec, "
                "reloads 33.26% magazine; self ATK +17.28% of caster ATK "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.13,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=17.28,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SMG B1 — burst-gen support via 400-ammo trigger plus a "
        "team-Attack-Damage buff and Bubble debuff that softens "
        "single-target damage. Pairs naturally with sustained-DPS comps "
        "that consume ammo quickly to trigger the gauge gains."
    ),
)
register_character(_SKILL)
