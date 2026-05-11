"""Viper (Treasure) — Water SG B2, upgraded Vamp DPS support.

Encoded from the live ``Character`` skill descriptions in the DB. The
Treasure form upgrades base Viper substantially: same on-spawn team
buff, but adds Vamp-state Sustained Damage stacking, a beefier burst
(1029.6% vs 462.85%), a re-enter Burst Stage 2 effect, and a 10-sec
sustained-damage DOT post-burst.

**Source description (S1)**:

    ■ Activates when the target appears. Affects all allies. ATK ▲
    25.98% for 10 sec. Hit Rate ▲ 11.13% for 10 sec.
    ■ Only activates when attacking in Vamp status. Affects self.
    Sustained Damage ▲ 4.4%, stacks up to 10 time(s) and lasts for
    10 sec. Hit Rate ▲ 1.84%, stacks up to 10 time(s) and lasts for
    10 sec.

**Source description (S2)**:

    ■ Affects self. Hit Rate ▲ 21.96% continuously.
    ■ Activates when entering Full Burst. Affects self. Vamp: Prevents
    self from being the target of single-target attacks continuously.
    Loses effect when the caster takes damage. Invulnerable for 1 sec.
    ■ Activates when using Burst Skill. Affects all allies. Re-enter
    Burst Skill Stage 2.

**Source description (Burst)**:

    ■ Affects 1 designated enemy unit(s). Deals 1029.6% of final ATK
    as damage.
    ■ Activates when the designated enemy unit(s) include the stage
    target. Affects the same enemy unit(s). DEF ▼ 19.83% for 10 sec.
    Deals 105.3% of final ATK as sustained damage every 1 sec for
    10 sec.
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
    character_name="Viper (Treasure)",
    skill1=(
        SkillEffect(
            description=(
                "On enemy spawn: all allies ATK +25.98% and Hit Rate "
                "+11.13% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="enemy spawns",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=25.98,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.13,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While in Vamp status (on attack): self Sustained "
                "Damage +4.4% and Hit Rate +1.84%, both stack 10x for "
                "10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="attacking in Vamp status",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=4.4,
                    duration_seconds=10.0,
                    stacks_max=10,
                ),
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.84,
                    duration_seconds=10.0,
                    stacks_max=10,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Passive: self Hit Rate +21.96% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=21.96,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: self enters Vamp (untargetable "
                "by single-target attacks continuously; consumed on "
                "damage taken) and gains 1 sec invulnerability."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=1.0,
                    notes=(
                        "actually 'Vamp + Invulnerable 1 sec' — Vamp "
                        "is a single-target-untargetable state that "
                        "ends on damage taken; DSL has no Vamp kind"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use: all allies re-enter Burst Stage 2."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=999.0,
                    notes=(
                        "actually 'Re-enter Burst Stage 2' — resets "
                        "all allies' burst gauge to B2 state; encoded "
                        "as massive CD-reduction proxy"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 1029.6% ATK to designated enemy; if stage "
                "target, DEF -19.83% and 105.3% ATK sustained damage "
                "every sec for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=10.296,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=19.83,
                    duration_seconds=10.0,
                    notes="conditional on stage target match",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.053,
                    notes=(
                        "actually 'sustained damage 105.3% every 1 sec "
                        "for 10 sec' = 10 ticks; encoded as single "
                        "instance"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water SG B2 — Treasure form of Viper. Re-enter B2 makes her "
        "a chainable B2 in 3-1-1 or 2-1-2 lineups; the 1029.6% burst "
        "+ DEF shred + DOT make her stronger than base Viper as a "
        "single-target nuke / debuffer."
    ),
)
register_character(_SKILL)
