"""Snow White: Heavy Arms — B3 Water SR sniper, Pilgrim.

Encoded from the live ``Character`` skill descriptions in the DB. Like
Red Hood, this character has multi-stage state mechanics (Lock-On
targets, Auto Fire ammo, Seven Dwarves Fully Active mode) that the
current DSL captures only at headline level.

**Source description (S1)** — six conditional sub-effects gated on
charge state and Full Burst:

    Activates every 0.2 sec while charging. Affects nearest non-locked
    enemy. Lock-On Function: designate as Seven Dwarves target.
        Max Lock-On targets: 5
        Removed by: normal attack or taking cover.

    Activates every 0.2 sec while charging. Affects self. Auto Fire
    Ready Function: load Seven Dwarves with ammo.
        Effect: DEF ▲ 42.24% continuously.
        Max ammo: 5. Removed by: normal attack.

    Activates every 0.2 sec while charging. Affects all locked enemies.
        Damage Taken ▲ 4.2% for 4 sec.

    Activates on Full Charge. Auto Fire Function: attack lock-on targets.
        Effect 1 (all enemies): 41.9% of final ATK as damage.
        Effect 2 (lock-on targets): 105.59% of final ATK as damage,
        sequential, based on ammo loaded.

    Activates on Full Charge while in Seven Dwarves Fully Active.
        Number of uses of Seven Dwarves Fully Active ▼ 1.

    Activates on normal attack while NOT in Full Burst. Affects self.
        Removes Seven Dwarves Fully Active.

**Source description (S2)**:

    On battle start: fix charge time at 1.2 sec continuously.
    On Full Charge: self gains Pierce 5 sec, ATK ▲ 46.84% 5 sec,
        Damage to Parts ▲ 62.64% 5 sec.
    On entering Burst Stage 3: ATK ▲ 73.92% for 10 sec.
    On Full Charge during Seven Dwarves Fully Active:
        Charge damage ▲ 528% for 1 round.
        Sequential attack damage ▲ 158.4% for 1 round.

**Source description (Burst)**:

    Self: Attack damage ▲ 84.48% for 10 sec.
    Seven Dwarves Fully Active: 2 uses.
        Effect 1: Fixed charge time at 3.2 sec continuously.
        Effect 2: Max Lock-On targets ▲ 10 continuously.
        Effect 3: Max ammo loaded by Auto Fire Ready ▲ 10 continuously.
        Removed when: number of uses reaches 0.
    All destructible projectiles: deals 41.9% of final ATK as damage.

**DSL gaps**:

  * **Lock-On / Auto Fire Ready / Seven Dwarves Fully Active** are
    runtime states with stack counts and decrement triggers — encoded
    as headline DEAL_DAMAGE / BUFF_DEFENSE effects with stack-machine
    behavior described in notes. The simulator will need a state
    machine for these mechanics.
  * **"Damage to Parts"** is a niche stat (boss-fight relevant); the
    DSL doesn't have BUFF_DAMAGE_TO_PARTS — encoded as a note on the
    BUFF_ATK that fires alongside it.
  * **"Charge time fixed"** is an override, not a buff — modeled as a
    placeholder note.
  * **"For 1 round(s)"** vs second-based durations — currently encoded
    as 1.0 second duration with a note; simulator must distinguish
    rounds (one full charge cycle) from seconds.
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
    character_name="Snow White: Heavy Arms",
    skill1=(
        SkillEffect(
            description=(
                "While charging (every 0.2 sec): lock on the nearest "
                "non-locked enemy as a Seven Dwarves target (max 5)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=0.2,
                condition="while charging",
            ),
            effects=(
                # No direct damage / buff — this is a state-machine effect.
                # Encoded as a no-op DEAL_TRUE_DAMAGE with magnitude 0 and
                # a descriptive note so the simulator can model lock-on
                # state without polluting other effect kinds.
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_FRONT),
                    magnitude=0.0,
                    notes=(
                        "lock-on tag (max 5 simultaneous); cleared by "
                        "normal attack or taking cover. Simulator state."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While charging (every 0.2 sec): Auto Fire Ready loads "
                "ammo (max 5). DEF +42.24% continuously while loaded."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=0.2,
                condition="while charging",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=42.24,
                    duration_seconds=86400.0,  # continuous
                    stacks_max=5,
                    notes=(
                        "scales with Auto Fire Ready ammo count; cleared "
                        "by normal attack"
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While charging (every 0.2 sec): all locked enemies take "
                "+4.2% damage taken for 4 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=0.2,
                condition="while charging; targets must be in Lock-On",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=4.2,
                    duration_seconds=4.0,
                    notes="actually 'damage taken +4.2%' on locked enemies only",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge: Auto Fire deals 41.9% to all enemies + "
                "105.59% to each lock-on target sequentially based on "
                "loaded ammo."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge release",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.419,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=5),
                    magnitude=1.0559,
                    notes=(
                        "sequential per loaded ammo; targets are the "
                        "Lock-On set, NOT random — DSL gap"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On battle start: fixed 1.2 sec charge time continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                # No matching "set charge time" effect kind — encoded as a
                # high-magnitude charge-speed buff with a note. Simulator
                # should override the value rather than add to it.
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes="fixed charge time = 1.2 sec; DSL needs SET_CHARGE_TIME",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge: self gains Pierce + ATK +46.84% + "
                "Damage-to-Parts +62.64% for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge release",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=46.84,
                    duration_seconds=5.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=62.64,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On entering Burst Stage 3: self ATK +73.92% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="entering Burst Stage 3 (B3 cast)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=73.92,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge during Seven Dwarves Fully Active: charge "
                "damage +528% and sequential attack damage +158.4% for 1 round."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge release while Seven Dwarves Fully Active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=528.0,
                    duration_seconds=1.0,
                    notes="duration is '1 round', not '1 second' — simulator gap",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=158.4,
                    duration_seconds=1.0,
                    notes="actually 'sequential attack damage +158.4% for 1 round'",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Self: Attack damage +84.48% for 10 sec. Activates Seven "
                "Dwarves Fully Active (2 uses): fixed charge 3.2 sec, "
                "max lock-on +10, max ammo +10. All destructible "
                "projectiles take 41.9% of ATK as damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=84.48,
                    duration_seconds=10.0,
                    notes="actually 'Attack damage +84.48%'; ATK proxy",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.419,
                    notes=(
                        "destructible projectiles only; PvP rarely has "
                        "these so this is mostly a PvE clause"
                    ),
                ),
                # Seven Dwarves Fully Active mode toggling — captured in
                # notes since the DSL doesn't yet model named modes.
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes=(
                        "Seven Dwarves Fully Active mode: 2 uses; gives "
                        "fixed charge 3.2 sec, max lock-on +10, max ammo "
                        "+10; consumed by S1 'Number of uses ▼ 1'"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "SW:HA's mechanics revolve around the Lock-On / Auto Fire Ready / "
        "Seven Dwarves Fully Active triple state. The DSL captures the "
        "headline damage and self-buffs, but the state machine "
        "(charge → lock-on accumulation → full charge release → SDFA "
        "consumption) is left for the simulator to model from the notes."
    ),
)
register_character(_SKILL)
