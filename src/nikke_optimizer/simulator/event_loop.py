"""Event-driven NIKKE PvP match simulator.

Successor to ``match_sim.simulate_per_character`` that addresses the
limits identified during Phase 1-7 validation:
  - Tight Champions Arena matchups end in 5-15s, before our static
    snapshots can differentiate teams.
  - Buff durations (10-15s windows) are crucial in this regime —
    being treated as steady-state hides who has the edge.
  - Per-skill cooldowns within a chain (e.g. Liter S1 every 6s,
    Anchor MP gauge progression) decide first-burst-rotation winners.

Architecture (event-driven, 10 Hz):

  1. Each tick (dt=0.1s) advances simulated time.
  2. Per-Nikke shot timer fires SHOT events every ``1/shots_per_sec``
     seconds — each shot deals damage AND adds burst gauge.
  3. Burst gauge fills until 100; the team's leftmost B1/B2/B3 (off
     cooldown) chain in sequence, opening a 10s Full Burst window.
  4. Skills with timed effects (BUFF_ATK +X% for 10s, etc.) are
     scheduled as ``BuffExpiry`` events at apply_time + duration.
  5. Death events propagate: dead Nikkes stop firing AND being
     targeted; team DPS recomputes on the next tick.
  6. Match ends when one team is fully dead OR at 300s timeout.

Built as a SEPARATE module from ``match_sim.py`` so the existing
team-aggregate / per-char snapshot simulators remain available for
fast scoring use cases. Event-loop is the high-fidelity fallback
when peer-matched outcomes are needed.

Sources cross-referenced for calibration:
  - nikke.gg/damage-formula (formula structure)
  - nikke.gg/burst-gauge-generation (per-weapon gauge rates)
  - nikke.gg/arena-mechanics (PvP-specific rules: 100% hit rate,
    SG always lands all 10 pellets, defender wins on timeout)
  - bittopup.com NIKKE F2P Burst Guide (cooldown table)
  - prydwen.gg/nikke/guides/pvp-burst (skill bonuses)

Status: SCAFFOLDING. Core event-loop + shot/burst-gauge/death events
are wired. Per-skill effect application from the DSL is TODO — the
tick loop currently uses pre-evaluated NikkeSnapshot stats with a
DPS-decay approximation, which is where event-loop improves on the
prior simulator. Full skill-event integration is the next slice.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Optional

from .damage import (
    DEFAULT_FIRST_BURST_SEC,
    MATCH_LENGTH_SEC,
    MIN_DAMAGE_FRACTION_THROUGH_DEF,
    WEAPON_DAMAGE_PER_SECOND_FRACTION,
    _def_reduction_factor,
    _per_member_atk_damage_multiplier,
)
from .evaluator import TeamEvaluation
from .timeline import (
    BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC,
    BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC,
)


# Frame rate for the event loop. 10 Hz balances precision (matches
# resolve in 5-300s, so 0.1s ticks give 50-3000 samples per match)
# with compute cost. Higher rate (60 Hz like NIKKE Synergy) costs 6×
# more compute for diminishing returns at our prediction granularity.
DEFAULT_TICK_DT_SEC = 0.1
FULL_BURST_WINDOW_SEC = 10.0


# Approximate shots-per-second by weapon class. NIKKE doesn't publish
# canonical fire rates; community estimates from nikke.gg vary slightly.
# These are calibrated to make burst-gen rates round-trip through the
# WEAPON_DAMAGE_PER_SECOND_FRACTION table consistently.
SHOTS_PER_SEC_BY_WEAPON: dict[str, float] = {
    "smg": 30.0,   # ~30 rounds/sec spray
    "ar":  12.0,   # 12 rounds/sec sustained
    "mg":  40.0,   # MGs are faster after spin-up
    "sg":  0.6,    # ~1 shotgun blast per 1.6s but each = 10 pellets
    "sr":  0.5,    # ~1 charged shot per 2s
    "rl":  0.25,   # ~1 charged shot per 4s
}


@dataclass(order=True)
class _Event:
    """Heap-ordered event."""
    time: float
    seq: int = field(compare=True)  # tiebreak — younger seq fires first
    kind: str = field(compare=False)
    data: dict = field(default_factory=dict, compare=False)


@dataclass
class EventLoopMember:
    """Per-Nikke runtime state for the event-loop simulator."""

    name: str
    hp: float
    max_hp: float
    shield: float
    atk: float                # effective ATK after all snapshot buffs
    weapon_class: str
    burst_position: str       # "1" / "2" / "3" / "flex"
    burst_payload: float      # one-shot burst-skill damage
    burst_cooldown_sec: float
    burst_ready_at: float     # next sim-time the burst can fire
    shots_per_sec: float
    next_shot_at: float       # next sim-time this Nikke fires
    eff_def: float
    is_taunting: bool
    heal_per_second: float
    heal_window_until: float  # while sim_time < this, heals tick
    alive: bool = True
    damage_dealt: float = 0.0
    damage_taken: float = 0.0


@dataclass
class EventLoopResult:
    """Output of an event-loop match simulation."""

    attacker_wins: bool = False
    match_ended_at_sec: float = 0.0
    end_reason: str = "timeout"
    attacker_total_damage: float = 0.0
    defender_total_damage: float = 0.0
    attacker_living_at_end: int = 0
    defender_living_at_end: int = 0
    a_first_burst_at: float = 0.0
    d_first_burst_at: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "attacker_wins": self.attacker_wins,
            "match_ended_at_sec": self.match_ended_at_sec,
            "end_reason": self.end_reason,
            "attacker_total_damage": self.attacker_total_damage,
            "defender_total_damage": self.defender_total_damage,
            "attacker_living_at_end": self.attacker_living_at_end,
            "defender_living_at_end": self.defender_living_at_end,
            "a_first_burst_at": self.a_first_burst_at,
            "d_first_burst_at": self.d_first_burst_at,
            "notes": list(self.notes),
        }


def _build_member(
    snap, opponent_avg_def: float
) -> EventLoopMember:
    """Convert a NikkeSnapshot into runtime EventLoopMember state."""
    weapon = (snap.weapon_class or "").lower()
    sps = SHOTS_PER_SEC_BY_WEAPON.get(weapon, 5.0)
    eff_atk = snap.effective_atk
    # Per-shot damage fraction × weapon mult is precomputed below;
    # we still need a fallback "DPS-equivalent" for sustained channels.
    weapon_factor = WEAPON_DAMAGE_PER_SECOND_FRACTION.get(weapon.upper(), 0.10)
    atk_mult = _per_member_atk_damage_multiplier(snap)
    def_factor = max(
        MIN_DAMAGE_FRACTION_THROUGH_DEF,
        _def_reduction_factor(eff_atk, opponent_avg_def),
    )
    # Per-shot damage = (DPS / shots-per-sec).
    dps = (
        eff_atk * atk_mult * def_factor * weapon_factor
        + eff_atk * (snap.true_damage_buff_pct / 100.0) * weapon_factor
        + eff_atk * (
            (snap.pierce_damage_buff_pct / 100.0) * 0.5
            + (snap.shield_damage_buff_pct / 100.0) * 0.3
            + (snap.sustained_damage_buff_pct / 100.0) * 0.2
        ) * weapon_factor
    )
    # Burst payload precomputed from snapshot.
    burst = snap.burst_damage_magnitude * eff_atk * def_factor

    return EventLoopMember(
        name=snap.name,
        hp=float(snap.base_hp + snap.flat_hp_bonus),
        max_hp=float(snap.base_hp + snap.flat_hp_bonus),
        shield=float(snap.shield_value),
        atk=dps / sps if sps > 0 else 0.0,  # per-shot damage
        weapon_class=weapon,
        burst_position=snap.burst_position or "flex",
        burst_payload=burst,
        burst_cooldown_sec=float(snap.burst_cooldown_sec or 20.0),
        burst_ready_at=0.0,
        shots_per_sec=sps,
        next_shot_at=0.0,
        eff_def=float(snap.effective_def),
        is_taunting=snap.is_taunting,
        heal_per_second=float(snap.heal_per_second),
        heal_window_until=0.0,
        alive=True,
    )


def _team_burst_gen_rate(team: list[EventLoopMember]) -> float:
    """% gauge per second contributed by living members.

    Sums per-weapon weapon class rates plus per-character skill
    bonuses. Cubes/charge-speed handled at burst-time-derivation
    layer separately (see derive_first_burst_sec).
    """
    rate = 0.0
    for m in team:
        if not m.alive:
            continue
        rate += BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC.get(
            m.weapon_class, 1.8
        )
        rate += BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC.get(m.name, 0.0)
    return rate


def _select_burst_chain_eventloop(
    team: list[EventLoopMember], current_time: float
) -> list[EventLoopMember]:
    """Pick 3 chain members (B1, B2, B3) leftmost-eligible.

    Mirrors ``match_sim._select_burst_chain`` but takes EventLoopMember.
    """
    chain: list[EventLoopMember] = []
    used: set[int] = set()
    for position in ("1", "2", "3"):
        cand = None
        for i, m in enumerate(team):
            if i in used or not m.alive or m.burst_ready_at > current_time:
                continue
            if m.burst_position == position:
                cand = (i, m)
                break
        if cand is None:
            for i, m in enumerate(team):
                if i in used or not m.alive or m.burst_ready_at > current_time:
                    continue
                if m.burst_position == "flex":
                    cand = (i, m)
                    break
        if cand is not None:
            used.add(cand[0])
            chain.append(cand[1])
    return chain


def _apply_damage(team: list[EventLoopMember], damage: float) -> float:
    """Distribute incoming damage to living team — taunters first,
    then lowest-HP focus fire.
    """
    if damage <= 0:
        return 0.0
    living = [m for m in team if m.alive]
    if not living:
        return 0.0
    taunters = [m for m in living if m.is_taunting]
    targets = taunters if taunters else [min(living, key=lambda m: m.hp)]
    per = damage / len(targets)
    applied = 0.0
    for tgt in targets:
        rem = per
        if tgt.shield > 0:
            absorb = min(tgt.shield, rem)
            tgt.shield -= absorb
            rem -= absorb
        if rem > 0:
            absorb_hp = min(tgt.hp, rem)
            tgt.hp -= absorb_hp
            rem -= absorb_hp
            tgt.damage_taken += absorb_hp
            if tgt.hp <= 0:
                tgt.alive = False
                tgt.hp = 0.0
        applied += per - rem
    return applied


def simulate_event_loop(
    attacker: TeamEvaluation,
    defender: TeamEvaluation,
    *,
    tick_dt: float = DEFAULT_TICK_DT_SEC,
    match_length_sec: float = MATCH_LENGTH_SEC,
) -> EventLoopResult:
    """Event-loop match resolution at 10 Hz.

    Differences from ``simulate_per_character``:
    1. Burst gauge fills via per-shot accumulation, not preset
       ``first_burst_sec`` schedule. A team's first chain fires when
       the gauge actually hits 100.
    2. Each Nikke fires shots on her own ``shots_per_sec`` cadence
       (clip reload approximated by uniform fire rate).
    3. Death events propagate: when a Nikke dies, her shots stop AND
       team burst-gen rate recomputes for the next tick.
    """
    a_avg_def = sum(m.effective_def for m in attacker.members) / max(
        len(attacker.members), 1
    )
    d_avg_def = sum(m.effective_def for m in defender.members) / max(
        len(defender.members), 1
    )
    a_team = [_build_member(m, d_avg_def) for m in attacker.members]
    d_team = [_build_member(m, a_avg_def) for m in defender.members]

    a_gauge = 0.0
    d_gauge = 0.0
    a_first_burst_at = 0.0
    d_first_burst_at = 0.0
    a_chain_starts: list[float] = []
    d_chain_starts: list[float] = []
    a_total = 0.0
    d_total = 0.0
    end_reason = "timeout"
    notes: list[str] = []

    t = 0.0
    while t < match_length_sec:
        a_living = [m for m in a_team if m.alive]
        d_living = [m for m in d_team if m.alive]
        if not a_living:
            end_reason = "attacker_cleared"
            break
        if not d_living:
            end_reason = "defender_cleared"
            break

        # DPS decay outside burst windows — matches match_sim's
        # POST_BURST_DPS_RETENTION model. Pre-first-burst stays at
        # 1.0 (peak) since baseline ATK already excludes burst-window-
        # only buffs. Real fix: per-skill buff event scheduling so
        # individual buff durations decay correctly.
        a_in_burst = any(bt <= t < bt + FULL_BURST_WINDOW_SEC for bt in a_chain_starts)
        d_in_burst = any(bt <= t < bt + FULL_BURST_WINDOW_SEC for bt in d_chain_starts)
        a_dps_factor = 1.0 if (not a_chain_starts or a_in_burst) else 0.55
        d_dps_factor = 1.0 if (not d_chain_starts or d_in_burst) else 0.55

        # Each living Nikke fires shots whose timer has elapsed.
        for m in a_living:
            while m.next_shot_at <= t and m.alive:
                applied = _apply_damage(d_team, m.atk * a_dps_factor)
                a_total += applied
                m.damage_dealt += applied
                m.next_shot_at += 1.0 / max(m.shots_per_sec, 0.001)
                if not [x for x in d_team if x.alive]:
                    break
        for m in d_living:
            while m.next_shot_at <= t and m.alive:
                applied = _apply_damage(a_team, m.atk * d_dps_factor)
                d_total += applied
                m.damage_dealt += applied
                m.next_shot_at += 1.0 / max(m.shots_per_sec, 0.001)
                if not [x for x in a_team if x.alive]:
                    break

        # Burst gauge accumulation.
        a_gauge += _team_burst_gen_rate(a_team) * tick_dt
        d_gauge += _team_burst_gen_rate(d_team) * tick_dt

        # Fire burst chains when gauge >= 100.
        if a_gauge >= 100:
            chain = _select_burst_chain_eventloop(a_team, t)
            if chain:
                burst_total = sum(m.burst_payload for m in chain)
                a_total += _apply_damage(d_team, burst_total)
                for m in chain:
                    m.burst_ready_at = t + m.burst_cooldown_sec
                    m.heal_window_until = t + 10.0  # heal during burst window
                if not a_first_burst_at:
                    a_first_burst_at = t
                a_chain_starts.append(t)
                a_gauge = 0.0
        if d_gauge >= 100:
            chain = _select_burst_chain_eventloop(d_team, t)
            if chain:
                burst_total = sum(m.burst_payload for m in chain)
                d_total += _apply_damage(a_team, burst_total)
                for m in chain:
                    m.burst_ready_at = t + m.burst_cooldown_sec
                    m.heal_window_until = t + 10.0
                if not d_first_burst_at:
                    d_first_burst_at = t
                d_chain_starts.append(t)
                d_gauge = 0.0

        # Heal application (during heal windows after burst chains).
        for m in a_living:
            if m.heal_per_second > 0 and t < m.heal_window_until:
                healed = m.heal_per_second * tick_dt
                target = min(a_living, key=lambda x: x.hp / max(x.max_hp, 1))
                target.hp = min(target.max_hp, target.hp + healed)
        for m in d_living:
            if m.heal_per_second > 0 and t < m.heal_window_until:
                healed = m.heal_per_second * tick_dt
                target = min(d_living, key=lambda x: x.hp / max(x.max_hp, 1))
                target.hp = min(target.max_hp, target.hp + healed)

        t += tick_dt

    return EventLoopResult(
        attacker_wins=(end_reason == "defender_cleared"),
        match_ended_at_sec=t,
        end_reason=end_reason,
        attacker_total_damage=a_total,
        defender_total_damage=d_total,
        attacker_living_at_end=sum(1 for m in a_team if m.alive),
        defender_living_at_end=sum(1 for m in d_team if m.alive),
        a_first_burst_at=a_first_burst_at,
        d_first_burst_at=d_first_burst_at,
        notes=notes,
    )
