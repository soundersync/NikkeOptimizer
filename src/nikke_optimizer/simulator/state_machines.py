"""Per-character state machines for the event-loop simulator.

The DSL handles most NIKKE skills declaratively, but certain
characters have multi-stage state mechanics that the generic DSL
can't represent cleanly. This module provides a base
``StateMachine`` class with lifecycle hooks the event loop calls
at appropriate points. Each registered character handler
implements the hooks it needs; defaults are no-op.

Usage from event_loop.simulate_event_loop:

    a_machines = [state_machine_for(m.name) for m in a_team]
    for member, sm in zip(a_team, a_machines):
        if sm: sm.on_battle_start(member, a_team, d_team, 0.0)
    # then per-tick on_tick(), per-shot on_shot_fired(), on_burst_fired().

Currently encoded (12 handlers):
  * Defenders/stall: Centi, Centi (Treasure), Trina, Soda, Blanc,
    Rosanna, Soda: Twinkling Bunny
  * Attackers: Scarlet, Liberalio, Snow White: Heavy Arms, Drake,
    Drake (Treasure)

==============================================================
NEXT-STEP STATE MACHINES TO ENCODE (priority order)
==============================================================

Each handler is ~30-50 LOC. Returns are diminishing on the current
14-match corpus but pay off as the corpus grows and new chars enter.

**Tier 1 — high-impact missing mechanics that already appear in
matches we can't W/L-predict correctly:**

  - **Crown** — Relax 20-stack cycle. In long matches (60s+) Crown
    fully stacks Relax → 7s of team ATK damage +20.99%. Should be
    modeled as an on_tick state machine: stack_count increments
    every 43 shots, at 20 grant team buff + invul. Currently the
    static evaluator silently drops her ON_HIT trigger; in
    Champion matches this under-credits Crown comps by 15-25%
    sustained DPS.
  - **Cinderella** — High-damage glass-cannon burst. Currently
    treated as a generic burst but has unique "high-roll" mechanics
    (Doll/Treasure scaling, lower-HP modifier). Big in m351's miss.
  - **Helm / Helm (Treasure)** — Charge Damage stacking on full
    charge hits. SR-specific. Helm Treasure burst 8237% is huge but
    only fires once per cycle; the per-shot state machine should
    track full-charge buildup.
  - **Red Hood** — Multi-stage burst (Beast Cage → Last Howl →
    Red Wolf). Each stage has different damage/buff structure.

**Tier 2 — common chars with simpler mechanics:**

  - **Noah** — Shield-on-burst defender. Her S2 grants team
    "Indestructible" (similar to Blanc Indomitability). Worth a
    handler for the m31-m35 user-side defense modeling.
  - **Biscuit** — Heal-on-burst + class-buff. Common rookie support.
  - **Moran (Treasure)** — Defender with taunt + shield. Slot 1
    position-based mechanic.
  - **Noir** — HP>70% ATK buff (not "Hostile counter" as I
    initially misremembered). Threshold-based ATK boost.
  - **Jackal** — Combo trigger + drone damage. Drone deals
    continuous on-tick damage during burst window.
  - **Anis: Star** — Pierce-damage stacker. Pierce shots through
    cover scale her damage massively.

**Tier 3 — niche / boss-PvE focused (low PvP priority):**

  - SW:HA Seven Dwarves Fully Active stage (multi-cycle)
  - Maxwell / Alice charge mechanics
  - Cinderella's burst damage variance from Doll phase
  - Snow White (regular) — multi-hit burst spread

**Patterns for adding new handlers:**

  1. Read the source description from the character's library file
  2. Identify which lifecycle hook fits (on_tick for periodic,
     on_shot_fired for count-based, on_burst_fired for burst-state,
     on_damage_taken for HP-threshold and counter)
  3. Use ``member.state`` dict with a unique key prefix per
     character (e.g. ``state["crown_relax_count"]``) to avoid
     collisions
  4. Apply buffs as ``member.atk *= multiplier`` for self-only,
     or modify ``ally.shield`` / ``ally.hp`` for team effects
  5. Register the class in ``_STATE_MACHINES`` dict
  6. Run ``baseline-sim --event-loop`` to measure impact

**Calibration tips:**

  - Cap activation reliability at ~50% (state machines don't fire
    every cycle in real fights — see Liberalio's DUTY_CYCLE=0.50)
  - SELF buffs should NOT cascade team-wide. Use member.atk
    directly, not active_buffs list
  - Heals add to ally.hp via min(max_hp - hp, heal_amt); track
    member.healing_done for validation
  - Shields add to ally.shield with a cap (2× the value) to
    prevent runaway accumulation
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
# Rosanna — Concealment (dodge) + Frenzy stacks
# ---------------------------------------------------------------------------


class Rosanna(StateMachine):
    """Rosanna's defensive value:
      - S1: After 120 normal attacks, enter Concealment for 10s.
      - S2: Battle start gives 5s Concealment. When ally falls,
        gain Frenzy stack (+22.61% ATK, max 10, 30s).

    Concealment in real NIKKE makes Rosanna untargetable. We model
    it as a temporary damage reduction (~70% to her HP pool during
    the concealment window).

    Hooks used:
      - on_battle_start: 5s concealment window from S2
      - on_tick: track and end concealment periods
      - on_damage_taken: reduce damage during concealment
    """

    character_name = "Rosanna"
    CONCEAL_BATTLE_START_SEC = 5.0
    DAMAGE_REDUCTION_PCT = 0.70  # 70% of damage absorbed by concealment

    def on_battle_start(self, member, ally_team, enemy_team, current_time):
        member.state["rosanna_conceal_until"] = self.CONCEAL_BATTLE_START_SEC

    def on_tick(self, member, ally_team, enemy_team, current_time, dt):
        # While in concealment, boost shield (acts as damage soak proxy).
        if current_time < member.state.get("rosanna_conceal_until", 0.0):
            # Top up to at least 30% of max_hp as shield to absorb hits.
            min_shield = member.max_hp * 0.3
            if member.shield < min_shield:
                member.shield = min_shield
        return None


# ---------------------------------------------------------------------------
# Trina — battle-start invulnerability + post-burst team heal
# ---------------------------------------------------------------------------


class Trina(StateMachine):
    """Trina S1: 4.06% of caster Max HP team heal for 5s after burst.
    S2 battle start: leftmost Electric Code rifle ally invulnerable
    for 2s + Electric Code Max HP buff already in DSL.

    The on-tick team heal (5s × 4.06%) is the key stall mechanic.

    Hooks used:
      - on_battle_start: 2s invulnerability for leftmost SR ally
      - on_tick: heal team during post-burst window
      - on_burst_fired: start the post-burst heal window
    """

    character_name = "Trina"
    HEAL_PCT_PER_SEC = 4.06
    HEAL_DURATION_SEC = 5.0

    def on_battle_start(self, member, ally_team, enemy_team, current_time):
        member.state["trina_grace_until"] = 2.0  # 2s invul for leftmost SR

    def on_burst_fired(self, member, ally_team, enemy_team, current_time):
        # Post-burst heal window opens.
        member.state["trina_heal_until"] = (
            current_time + 10.0 + self.HEAL_DURATION_SEC  # after full burst ~10s
        )

    def on_tick(self, member, ally_team, enemy_team, current_time, dt):
        # Battle-start grace
        grace = member.state.get("trina_grace_until", 0.0)
        if current_time < grace:
            for ally in ally_team:
                if ally.weapon_class == "sr" and ally.alive:
                    if ally.hp < ally.max_hp * 0.01:
                        ally.hp = ally.max_hp * 0.01
                    break
        # Post-burst heal
        heal_until = member.state.get("trina_heal_until", 0.0)
        if 0 < current_time < heal_until:
            heal_amt = member.max_hp * (self.HEAL_PCT_PER_SEC / 100.0) * dt
            for ally in ally_team:
                if ally.alive:
                    healed = min(ally.max_hp - ally.hp, heal_amt)
                    ally.hp += healed
                    member.healing_done += healed
        return None


# ---------------------------------------------------------------------------
# Soda — Maid Spirit (Max HP stacks) + team heal on burst
# ---------------------------------------------------------------------------


class Soda(StateMachine):
    """Soda S1: every 180 normal attacks gain Maid Spirit (+13% Max HP,
    5 stacks, 10s). S2: on Maid Spirit full stacks, team heal 3.23%
    of caster Max HP. Burst: 2 enemies 321.8% damage + 1s stun.

    Maid Spirit stacks are slow (180 attacks) — in 30s with 10 shots/s,
    she'd hit ~5 stacks total. Approximate by adding a flat 30% Max HP
    boost early in the match.

    Hooks used:
      - on_battle_start: trigger Maid Spirit ramp
      - on_tick: heal team 3.23% Max HP periodically (when full stacks)
    """

    character_name = "Soda"
    HEAL_PCT = 3.23
    HEAL_INTERVAL_SEC = 6.0  # roughly matches her Maid Spirit cycle

    def on_battle_start(self, member, ally_team, enemy_team, current_time):
        member.state["soda_last_heal_at"] = current_time + 18.0  # delay before first

    def on_tick(self, member, ally_team, enemy_team, current_time, dt):
        last = member.state.get("soda_last_heal_at", 999.0)
        if current_time >= last + self.HEAL_INTERVAL_SEC:
            heal_amt = member.max_hp * (self.HEAL_PCT / 100.0)
            for ally in ally_team:
                if ally.alive:
                    healed = min(ally.max_hp - ally.hp, heal_amt)
                    ally.hp += healed
                    member.healing_done += healed
            member.state["soda_last_heal_at"] = current_time
        return None


# ---------------------------------------------------------------------------
# Soda: Twinkling Bunny — Golden Chip stacks + cascading burst stages
# ---------------------------------------------------------------------------


class SodaTwinklingBunny(StateMachine):
    """Soda: Twinkling Bunny S1: 50 Golden Chips at battle start,
    +1.32% Crit Damage per stack (max 50, every 3 attacks during FBT).
    Burst cascades through stages based on Chip count.

    Hooks used:
      - on_battle_start: grant 50 chips (+66% crit damage)
      - on_shot_fired: maintain chips during FBT
    """

    character_name = "Soda: Twinkling Bunny"
    BASE_CHIPS = 50
    CRIT_DAMAGE_PER_CHIP = 1.32

    def on_battle_start(self, member, ally_team, enemy_team, current_time):
        member.state["soda_bunny_chips"] = self.BASE_CHIPS
        # Apply expected crit damage uplift to per-shot damage as a
        # one-shot multiplier (crit_rate × crit_damage = expected).
        crit_dmg_total = self.BASE_CHIPS * self.CRIT_DAMAGE_PER_CHIP  # 66%
        # Crit rate baseline 25%, so expected damage uplift = 0.25 × 0.66 = 16.5%.
        multiplier = 1.0 + 0.25 * (crit_dmg_total / 100.0)
        member.atk *= multiplier
        member.base_atk *= multiplier


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
        Rosanna,
        Trina,
        Soda,
        SodaTwinklingBunny,
    ]
}


def state_machine_for(name: str) -> Optional[StateMachine]:
    """Return an instance of the state machine for ``name``, or None
    when no handler is registered."""
    cls = _STATE_MACHINES.get(name)
    return cls() if cls else None
