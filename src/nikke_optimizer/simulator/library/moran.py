"""Moran — Electric AR B1, taunter / defender.

Encoded from the live ``Character`` skill descriptions in the DB. Moran
is a defensive B1 with a "Perseverance" state machine that activates
when HP falls below 20% — the cap on activations (once / twice / three
times per battle, with declining magnitudes) is a DSL gap noted in S2.

**Source description (S1)**:

    Activates at the start of the battle. Affects self. DEF ▲ 3.51%
    with every 1% of HP loss.
    Activates when landing 5 normal attacks when changing the weapon
    in use. Affects the target. Deals 47.18% of final ATK as additional
    damage.

**Source description (S2)**:

    Activates when firing the final bullet. Affects 3 enemy unit(s)
    with the highest ATK. Taunt for 4 sec.
    Activates when HP falls below 20%. Affects self. Effect changes
    according to the number of activation time(s). Perseverance:
    Effect of each phase does not stack.
      Once: Max HP ▲ 91% for 3 sec. Once per battle.
      Twice: Max HP ▲ 69.84% for 3 sec. Once per battle.
      Three: Max HP ▲ 51.09% for 3 sec. Once per battle.

**Source description (Burst)**:

    Affects self. Change the Weapon in use:
      Damage: 14.7% of final ATK
      Lasts for: 10 sec
      Recovers 36.14% of attack damage as HP for 10 sec.
      Attract: Taunt all enemies for 10 sec.
    Affects all allies. Damage Taken ▼ 35.14% for 10 sec. DEF ▲ 14.85%
    of caster's DEF for 10 sec.
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
    character_name="Moran",
    skill1=(
        SkillEffect(
            description=(
                "Battle start (continuous): self DEF +3.51% per 1% HP "
                "lost — scales with damage taken."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.51,
                    duration_seconds=86400.0,
                    notes="actually scales per 1% HP lost — DSL gap",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On landing 5 normal attacks after weapon change: target "
                "takes 47.18% ATK additional damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="5 normal attacks after weapon change",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.4718,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On firing final bullet: 3 highest-ATK enemies taunted "
                "for 4 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=3),
                    magnitude=0.0,
                    duration_seconds=4.0,
                    notes="actually 3 highest-ATK enemies (target filter)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Perseverance — when HP < 20%, self gains Max HP buff. "
                "Once: +91% for 3 sec. Twice: +69.84% for 3 sec. "
                "Three times: +51.09% for 3 sec. Each phase fires once "
                "per battle."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="HP < 20% (1st / 2nd / 3rd activation)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=91.0,
                    duration_seconds=3.0,
                    notes=(
                        "phased: 91% (once) / 69.84% (twice) / 51.09% "
                        "(three times). Each cap is once-per-battle. "
                        "Encoded with first-tier magnitude. (DSL gap)"
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: weapon switch (14.7% ATK per shot, 10 sec, "
                "36.14% lifesteal); Attract taunt for 10 sec; all allies "
                "damage taken -35.14% for 10 sec; DEF +14.85% of caster's "
                "DEF for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=35.14,
                    duration_seconds=10.0,
                    notes="actually 'damage taken' debuff — encoded as DEF",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.85,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Electric AR B1 — taunter / lifesteal tank. Niche on offense "
        "(weapon switch is the only damage path) but solid on stall "
        "defense comps where the team-wide damage reduction matters."
    ),
)
register_character(_SKILL)
