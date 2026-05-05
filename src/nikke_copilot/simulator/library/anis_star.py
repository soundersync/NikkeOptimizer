"""Anis: Star — B1 Electric RL buffer/healer, Tetra. Squad-conditional B1 alt.

Encoded from the live ``Character`` skill descriptions in the DB. Anis:
Star has the most complex squad-conditional logic in our library: her
state ("My Own Star" or "Everyone's Star") flips based on whether
another B1 ally is on the team, and her S2 + Burst gate effects on
that state. We encode both branches with explicit conditions.

**Source description (S1)** — three sub-clauses, the second of which
has a conditional fork:

    Activates at the start of battle only if self is alive. Affects
    all allies. Burst Gauge filling speed 6% ▲ continuously.

    Activates at the start of battle and when Full Burst ends. Effect
    differs according to squad formation. Only the corresponding effect
    is applied.

      If there are no other Burst 1 allies:
        Effect 1: Cancels Everyone's Star.
        Effect 2: Self ATK ▲ 40.01% continuously (My Own Star state).
        Effect 3: All allies burst CD ▼ 7.48 sec.

      If there are any other Burst 1 allies:
        Effect 1: Cancels My Own Star.
        Effect 2: Re-enters Burst and changes to Stage 1 (Everyone's Star).

    Activates when hitting a target with Full Charge. Affects the
    target. Deals 120.13% of final ATK as additional damage.

**Source description (S2)** — four conditional clauses:

    Activates when entering Full Burst while in My Own Star status.
    Affects all allies. ATK ▲ 35.01% of caster's ATK for 10 sec.

    Activates when performing a Full Charge attack while in Everyone's
    Star status. Affects all allies. Restores 1.26% of caster's max HP.

    Activates when entering Full Burst. Affects self and all allies
    with lower final DEF than self. Projectile Explosion Damage ▲
    92.03% for 10 sec.

    Activates when entering Full Burst. Affects all allies.
    Attack Damage ▲ 34% for 10 sec.

**Source description (Burst)**:

    Affects self. Shooting Stars Function: Generates stars around Anis
    that attack random targets automatically.
        Damage: 40.01% of final ATK
        Attack Interval: 0.25 sec
        Duration: 10 sec
    Additional Effects:
        Charge time is fixed at 0.7 sec for 10 sec.
        Explosion Radius ▲ 100% for 10 sec.
        DEF ▲ 55.01% for 10 sec.

    Activates while in My Own Star status. Affects self.
    Attack Damage ▲ 35.2% for 10 sec.

    Activates while in Everyone's Star status. Affects all allies.
    Max HP ▲ 15.02% of caster's max HP for 10 sec.

**DSL gaps**:

  * "My Own Star" / "Everyone's Star" are named states that flip on
    squad composition — encoded as CONDITIONAL with state name in
    ``condition``. Simulator must track state.
  * "Re-enters Burst and changes to Stage 1" — same gap as Tia's burst.
  * "Projectile Explosion Damage" / "Explosion Radius" — niche stats
    (matters for Anis's RL); encoded as ATK proxy with notes.
  * "Shooting Stars" auto-attacks every 0.25 sec — encoded as a
    persistent DEAL_DAMAGE during burst with a per-tick note.
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
    character_name="Anis: Star",
    skill1=(
        SkillEffect(
            description=(
                "On battle start (passive while alive): all allies "
                "Burst Gauge filling speed +6% continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=6.0,
                    notes=(
                        "actually 'Burst Gauge filling speed +6% "
                        "continuously' — multiplicative on gauge gain, "
                        "not a one-shot. Encoded as note."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On battle start / Full Burst end with NO other B1 ally: "
                "self ATK +40.01% (My Own Star, continuous); all allies "
                "burst CD -7.48 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="solo B1 (no other Burst-1 ally on team)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.01,
                    duration_seconds=86400.0,
                    notes="continuous while in My Own Star state",
                ),
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.48,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On battle start / Full Burst end WITH another B1 ally: "
                "Anis enters 'Everyone's Star' state and re-enters Burst "
                "Stage 1 for the team."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="another Burst-1 ally on team (Everyone's Star)",
            ),
            effects=(
                # Re-enter burst — same gap as Tia's burst. Encoded as
                # GAIN_BURST_GAUGE placeholder + note.
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    notes=(
                        "actually 'Re-enters Burst and changes to Stage 1' "
                        "— team can burst again. DSL gap (RE_ENTER_BURST)."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge hit: deals 120.13% of ATK as additional "
                "damage to the target."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge attack lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.2013,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst entry while in My Own Star: all allies "
                "ATK +35.01% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="My Own Star state active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=35.01,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge while in Everyone's Star: all allies "
                "recover 1.26% of caster's max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Everyone's Star + Full Charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.26,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: self + lower-DEF allies get "
                "Projectile Explosion Damage +92.03% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=92.03,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Projectile Explosion Damage' (RL/SG "
                        "specific) and target subset is allies with "
                        "lower DEF than caster. Encoded as broad proxy."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: all allies Attack Damage +34% "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=34.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: Shooting Stars (auto-attacks every 0.25 sec for "
                "10 sec, 40.01% ATK each), self charge time fixed at "
                "0.7 sec, Explosion Radius +100%, DEF +55.01% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=1),
                    magnitude=0.4001,
                    notes=(
                        "Shooting Stars: 40.01% per hit × ~40 hits over "
                        "10 sec (every 0.25 sec). Encoded as per-shot."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=55.01,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "charge time fixed at 0.7 sec; DSL gap "
                        "(SET_CHARGE_TIME)"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Burst, while in My Own Star: self Attack Damage "
                "+35.2% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="My Own Star state active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=35.2,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Burst, while in Everyone's Star: all allies Max HP "
                "+15.02% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Everyone's Star state active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.02,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Anis: Star is the canonical 'flexible B1 slot' — solo-B1 teams "
        "get a beefy ATK self-buff and team burst-CD reduction; "
        "double-B1 teams get a re-enter-burst rotation. Pairs naturally "
        "with Liter for Everyone's Star comps that double-burst per "
        "rotation."
    ),
)
register_character(_SKILL)
