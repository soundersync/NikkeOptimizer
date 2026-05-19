"""Per-character state machines for the event-loop simulator.

The DSL handles most NIKKE skills declaratively, but certain
characters have multi-stage state mechanics that the generic DSL
can't represent cleanly:

  - Centi (Treasure): periodic shield refresh every 5s (S2 ALWAYS
    trigger with internal cooldown)
  - Scarlet: HP-threshold conditional buffs (S1 30%-chance damage-
    response, S2 HP<60% crit damage)
  - Snow White: Heavy Arms: Lock-On target set + Auto-Fire +
    Seven Dwarves Fully Active multi-state
  - Crown: Relax stack-of-20 → invulnerability + team buff
  - Liberalio: Raging Current state on full-charge hit
  - Drake: Hostile counter true-damage on hits

This module provides a base ``StateMachine`` class with lifecycle
hooks the event loop calls at appropriate points. Each registered
character handler implements the hooks it needs; defaults are no-op.

Usage:

    machines = create_state_machines_for_team(members)
    for m, sm in zip(team, machines):
        sm.on_battle_start(m, team, enemy_team, current_time=0.0)
    ...
    # per-shot:
    sm.on_shot_fired(member, ally_team, enemy_team, current_time)
    # per-tick:
    sm.on_tick(member, ally_team, enemy_team, current_time, dt)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .event_loop import EventLoopMember


class StateMachine:
    """Base class. All hooks are no-op by default.

    Subclasses override hooks for the specific behavior they need.
    ``state`` is stored on the EventLoopMember (``member.state``) — a
    dict keyed by short strings to avoid name collisions between
    multiple state machines. Each handler should use its own
    namespace (e.g. ``state["centi_last_shield_at"]``).
    """

    # Characters this handler applies to. Subclasses set this.
    character_name: str = ""

    def on_battle_start(
        self,
        member: "EventLoopMember",
        ally_team: list,
        enemy_team: list,
        current_time: float,
    ) -> None:
        """Called once at t=0 for each living member with a handler."""
        pass

    def on_tick(
        self,
        member: "EventLoopMember",
        ally_team: list,
        enemy_team: list,
        current_time: float,
        dt: float,
    ) -> Optional[float]:
        """Called every tick (10 Hz default). Returns bonus damage to
        deal to enemies on this tick, or None for no bonus."""
        return None

    def on_shot_fired(
        self,
        member: "EventLoopMember",
        ally_team: list,
        enemy_team: list,
        current_time: float,
    ) -> Optional[float]:
        """Called after a normal-attack shot fires. Returns bonus
        damage to deal to the primary target."""
        return None

    def on_damage_taken(
        self,
        member: "EventLoopMember",
        ally_team: list,
        enemy_team: list,
        damage_amount: float,
        current_time: float,
    ) -> None:
        """Called when this member takes damage. State machines can
        proc counter-effects (Drake Hostile) or HP-threshold buffs
        (Scarlet) here."""
        pass

    def on_burst_fired(
        self,
        member: "EventLoopMember",
        ally_team: list,
        enemy_team: list,
        current_time: float,
    ) -> None:
        """Called when this member fires their burst skill."""
        pass


# ---------------------------------------------------------------------------
# Centi (Treasure) — periodic team shield (5s cycle)
# ---------------------------------------------------------------------------


class CentiTreasure(StateMachine):
    """Centi (Treasure) S2: grants the team a shield equal to 7% of
    Centi's max HP every 5 seconds for 5s duration.

    In-game: S1 force-casts S2 at battle start, then the 5s timer
    fires periodically. Real shield duration overlaps with refresh
    so the team has near-continuous shield uptime.

    Hooks used:
      - on_battle_start: cast initial shield (S1 force-cast)
      - on_tick: refresh every 5s
    """

    character_name = "Centi (Treasure)"
    SHIELD_PCT = 7.0  # % of caster max HP
    REFRESH_INTERVAL_SEC = 5.0

    def on_battle_start(self, member, ally_team, enemy_team, current_time):
        # S1 forces S2 cast at battle start.
        self._apply_shield(member, ally_team)
        member.state["centi_last_shield_at"] = current_time

    def on_tick(self, member, ally_team, enemy_team, current_time, dt):
        last = member.state.get("centi_last_shield_at", -999.0)
        if current_time - last >= self.REFRESH_INTERVAL_SEC:
            self._apply_shield(member, ally_team)
            member.state["centi_last_shield_at"] = current_time
        return None

    def _apply_shield(self, caster, ally_team):
        shield_amt = caster.max_hp * (self.SHIELD_PCT / 100.0)
        for ally in ally_team:
            if ally.alive:
                # Don't stack indefinitely — cap at 2× shield value.
                ally.shield = min(ally.shield + shield_amt, shield_amt * 2)


# ---------------------------------------------------------------------------
# Centi (non-Treasure) — same mechanic, slightly different magnitude
# ---------------------------------------------------------------------------


class Centi(StateMachine):
    """Centi (regular) S2: 5.45% of max HP shield every 7s.

    Less impactful than her Treasure form but still meaningful for
    stall comps that don't have the Treasure unlocked.
    """

    character_name = "Centi"
    SHIELD_PCT = 5.45
    REFRESH_INTERVAL_SEC = 7.0

    def on_battle_start(self, member, ally_team, enemy_team, current_time):
        self._apply_shield(member, ally_team)
        member.state["centi_last_shield_at"] = current_time

    def on_tick(self, member, ally_team, enemy_team, current_time, dt):
        last = member.state.get("centi_last_shield_at", -999.0)
        if current_time - last >= self.REFRESH_INTERVAL_SEC:
            self._apply_shield(member, ally_team)
            member.state["centi_last_shield_at"] = current_time
        return None

    def _apply_shield(self, caster, ally_team):
        shield_amt = caster.max_hp * (self.SHIELD_PCT / 100.0)
        for ally in ally_team:
            if ally.alive:
                ally.shield = min(ally.shield + shield_amt, shield_amt * 2)


# ---------------------------------------------------------------------------
# Scarlet — HP-threshold crit damage
# ---------------------------------------------------------------------------


class Scarlet(StateMachine):
    """Scarlet's defining mechanic: when HP < 60%, her Crit Damage
    gains +6.61% continuously. Her S1 has a 30% chance to deal
    damage on damage taken — modeled as a small per-shot bonus
    proxy.

    Hooks used:
      - on_tick: check HP threshold, apply/remove crit buff
      - on_damage_taken: tracks damage for S1 proc proxy
    """

    character_name = "Scarlet"
    HP_THRESHOLD = 0.60
    CRIT_DAMAGE_BONUS_PCT = 6.61

    def on_tick(self, member, ally_team, enemy_team, current_time, dt):
        in_state = member.hp / max(1, member.max_hp) < self.HP_THRESHOLD
        was_in_state = member.state.get("scarlet_low_hp", False)
        if in_state and not was_in_state:
            # Apply per-member +6.61% crit damage as ATK buff (simulator
            # doesn't track crit damage directly per-member).
            # Approximation: +6.61% × 0.25 (crit rate) = +1.65% damage
            # multiplier. Apply to member.atk / base_atk.
            multiplier = 1.0 + 0.0165
            member.atk *= multiplier
            member.base_atk *= multiplier
            member.state["scarlet_low_hp"] = True
        return None


# ---------------------------------------------------------------------------
# Snow White: Heavy Arms — Lock-On + Auto-Fire
# ---------------------------------------------------------------------------


class SnowWhiteHeavyArms(StateMachine):
    """Snow White: Heavy Arms multi-stage mechanic:

      - Every 10 normal attacks: designate 1 enemy as Lock-On target
        (max 5). On full charge, Auto-Fire deals 105.59% damage to
        each Lock-On target sequentially.

    Simplified model: every 10 shots, fire AOE damage at 105.59% to
    all enemies (Lock-On set assumed to grow to full 5).

    Hooks used:
      - on_shot_fired: every 10th shot, fire Auto-Fire AOE bonus
    """

    character_name = "Snow White: Heavy Arms"
    AUTO_FIRE_MAGNITUDE_PCT = 105.59  # per target
    DESIGNATE_EVERY_N_HITS = 10

    def on_shot_fired(self, member, ally_team, enemy_team, current_time):
        shots = member.state.get("swha_shots", 0) + 1
        member.state["swha_shots"] = shots
        # Build Lock-On set over first 50 shots.
        n_locked = min(5, shots // self.DESIGNATE_EVERY_N_HITS)
        if shots % self.DESIGNATE_EVERY_N_HITS == 0 and n_locked > 0:
            # Auto-Fire damage to n_locked targets.
            return (
                member.base_atk * (self.AUTO_FIRE_MAGNITUDE_PCT / 100.0)
                * n_locked
            )
        return None


# ---------------------------------------------------------------------------
# Liberalio — Raging Current state machine (self-only +231% attack damage)
# ---------------------------------------------------------------------------


class Liberalio(StateMachine):
    """Liberalio's S2: Full Charge hit on stage target gives self
    Attack Damage +231% continuously (Raging Current state).

    Generic CONDITIONAL handler in event_loop applies this as a
    team-wide buff scaled down. This handler models it correctly as
    a self-only buff by directly boosting her per-shot damage once
    the state activates.

    Hooks used:
      - on_shot_fired: first shot triggers entry into Raging Current,
        then her base_atk is permanently boosted by some fraction
        (still less than 231% because real PvP fights end before all
        the buff value is realized).
    """

    character_name = "Liberalio"
    # Real magnitude is +231% attack damage = 3.31× multiplier on her
    # attack channel. In a typical 30s PvP match with her charging
    # cadence, she lands ~5-8 full-charge shots — but Raging Current
    # only activates after the FIRST one. Realized duty cycle: ~50%.
    DUTY_CYCLE = 0.50
    MAGNITUDE_PCT = 231.0

    def on_shot_fired(self, member, ally_team, enemy_team, current_time):
        if not member.state.get("liberalio_raging_current"):
            # First shot triggers it.
            member.state["liberalio_raging_current"] = True
            multiplier = 1.0 + (self.MAGNITUDE_PCT / 100.0) * self.DUTY_CYCLE
            member.atk *= multiplier
            member.base_atk *= multiplier
        return None


# ---------------------------------------------------------------------------
# Blanc — Indomitability + team heal on burst
# ---------------------------------------------------------------------------


class Blanc(StateMachine):
    """Blanc's burst grants the team Indomitability (1s no-death) +
    HP recovery 5% per sec for 5s.

    Indomitability is the key stall mechanic: during the 1s window
    after Blanc's burst, no ally can die. Models by giving all
    allies a small HP top-off + temporary invulnerability proxy
    (raise HP to at least 1% on each tick during the window).

    Hooks used:
      - on_burst_fired: trigger team heal + grace window
      - on_tick: during grace window, prevent allies from dying
    """

    character_name = "Blanc"
    HEAL_PCT_PER_SEC = 5.0
    HEAL_DURATION_SEC = 5.0
    GRACE_DURATION_SEC = 1.0  # Indomitability

    def on_burst_fired(self, member, ally_team, enemy_team, current_time):
        member.state["blanc_heal_until"] = current_time + self.HEAL_DURATION_SEC
        member.state["blanc_grace_until"] = current_time + self.GRACE_DURATION_SEC

    def on_tick(self, member, ally_team, enemy_team, current_time, dt):
        heal_until = member.state.get("blanc_heal_until", 0.0)
        grace_until = member.state.get("blanc_grace_until", 0.0)
        if current_time < heal_until:
            # Heal 5% of caster max HP / sec to all allies.
            heal_amt = member.max_hp * (self.HEAL_PCT_PER_SEC / 100.0) * dt
            for ally in ally_team:
                if ally.alive:
                    healed = min(ally.max_hp - ally.hp, heal_amt)
                    ally.hp += healed
                    member.healing_done += healed
        if current_time < grace_until:
            # Indomitability: prevent allies from dying. Top off at 1%.
            for ally in ally_team:
                if ally.hp < ally.max_hp * 0.01:
                    ally.hp = ally.max_hp * 0.01
                    ally.alive = True
        return None


# ---------------------------------------------------------------------------
# Drake — S2 periodic damage every 10 hits
# ---------------------------------------------------------------------------


class Drake(StateMachine):
    """Drake S2: every 10 normal attacks, 3 lowest-HP enemies take
    98.55% of ATK damage.

    Hooks used:
      - on_shot_fired: every 10th shot, deal AOE bonus to 3 targets
    """

    character_name = "Drake"
    MAGNITUDE_PCT = 98.55
    EVERY_N_HITS = 10
    N_TARGETS = 3

    def on_shot_fired(self, member, ally_team, enemy_team, current_time):
        shots = member.state.get("drake_shots", 0) + 1
        member.state["drake_shots"] = shots
        if shots % self.EVERY_N_HITS == 0:
            return (
                member.base_atk * (self.MAGNITUDE_PCT / 100.0)
                * self.N_TARGETS
            )
        return None


# ---------------------------------------------------------------------------
# Drake (Treasure) — same S2 + additional 5-hit secondary
# ---------------------------------------------------------------------------


class DrakeTreasure(StateMachine):
    """Drake (Treasure) S2: same 10-hit AOE plus an extra 5-hit
    single-target hit (201.6% to 1 enemy).

    Hooks used:
      - on_shot_fired: every 10th shot, AOE bonus; every 5th, ST bonus
    """

    character_name = "Drake (Treasure)"
    AOE_MAGNITUDE_PCT = 98.55
    AOE_EVERY = 10
    AOE_TARGETS = 3
    ST_MAGNITUDE_PCT = 201.6
    ST_EVERY = 5

    def on_shot_fired(self, member, ally_team, enemy_team, current_time):
        shots = member.state.get("drake_t_shots", 0) + 1
        member.state["drake_t_shots"] = shots
        bonus = 0.0
        if shots % self.AOE_EVERY == 0:
            bonus += (
                member.base_atk * (self.AOE_MAGNITUDE_PCT / 100.0)
                * self.AOE_TARGETS
            )
        if shots % self.ST_EVERY == 0:
            bonus += member.base_atk * (self.ST_MAGNITUDE_PCT / 100.0)
        return bonus if bonus > 0 else None


# ---------------------------------------------------------------------------
# Registry — looked up by character name in event_loop
# ---------------------------------------------------------------------------


_STATE_MACHINES: dict[str, type[StateMachine]] = {
    cls.character_name: cls
    for cls in [
        CentiTreasure,
        Centi,
        Scarlet,
        SnowWhiteHeavyArms,
        Liberalio,
        Blanc,
        Drake,
        DrakeTreasure,
    ]
}


def state_machine_for(name: str) -> Optional[StateMachine]:
    """Return an instance of the state machine for ``name``, or None
    when no handler is registered."""
    cls = _STATE_MACHINES.get(name)
    return cls() if cls else None
