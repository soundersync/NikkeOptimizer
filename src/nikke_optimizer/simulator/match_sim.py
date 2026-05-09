"""Time-stepped match simulator — Phase 3 slice 4.

Where ``damage.py`` produces a single "who clears whom faster" comparison
from snapshot stats, this module simulates a 5-minute match second-by-
second. The two key behaviors it adds:

1. **Burst timing is concrete.** First burst chain lands at t=first_burst,
   not amortized over 300s. A team that one-shots 70% of the opposing
   defender HP at t=10s wins fast even if its sustained DPS is mediocre —
   ``damage.py``'s amortized model misses this.

2. **Death events change DPS.** When a team's HP hits zero, their damage
   output stops. Real matches can end at t=20s with 80% of the *would-be*
   damage uncollected. Champions Arena LV-400 matchups especially live
   in this regime — both teams have so much DPS relative to defender HP
   that 5-minute amortization completely blurs out the actual outcome.

The model is still **team-aggregate** (not per-character HP tracking) for
simplicity. Per-char attribution can come in a later slice.

Inputs: two TeamEvaluation snapshots.
Output: TimeSteppedResult with per-second HP timelines + the same
outcome fields as DamageResolution for drop-in comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .damage import (
    DamageResolution,
    DEFAULT_CYCLE_PERIOD_SEC,
    DEFAULT_FIRST_BURST_SEC,
    MATCH_LENGTH_SEC,
    MIN_DAMAGE_FRACTION_THROUGH_DEF,
    WEAPON_DAMAGE_PER_SECOND_FRACTION,
    _def_reduction_factor,
    _per_member_atk_damage_multiplier,
)
from .evaluator import TeamEvaluation
from .timeline import compute_burst_chain_offsets


def derive_first_burst_sec(
    team: TeamEvaluation,
    member_cubes: Optional[list[tuple[Optional[str], Optional[int]]]] = None,
) -> float:
    """Compute when the team's first burst chain completes.

    Uses ``compute_burst_chain_offsets`` from timeline.py with weapon
    classes + member names (for skill-based gauge bonuses) + optional
    cube info (Quantum LV15 = +1.5%/s gauge per Nikke equipped).

    Returns the time of the FIRST burst (offsets[0]). Subsequent
    bursts in the chain land 1s apart; the Full Burst window opens
    at offsets[2].
    """
    weapons = [m.weapon_class for m in team.members]
    names = [m.name for m in team.members]
    offsets = compute_burst_chain_offsets(
        weapons, member_names=names, member_cubes=member_cubes
    )
    return offsets[0]


@dataclass
class TimeSteppedResult:
    """Outcome of a time-stepped match simulation."""

    # Outcome
    attacker_wins: bool = False
    match_ended_at_sec: float = 0.0  # when did combat resolve (or 300 for timeout)
    end_reason: str = "timeout"  # "attacker_cleared", "defender_cleared", "timeout"

    # Total damage actually dealt (truncated by match end, unlike DamageResolution)
    attacker_total_damage: float = 0.0
    defender_total_damage: float = 0.0

    # End-state HP for diagnostic
    attacker_hp_remaining: float = 0.0
    defender_hp_remaining: float = 0.0

    # Per-second timelines for diagnostic / future per-char extension
    attacker_hp_timeline: list[float] = field(default_factory=list)
    defender_hp_timeline: list[float] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)

    @property
    def win_margin(self) -> float:
        """Attacker advantage in seconds (positive = won earlier than 300s)."""
        return MATCH_LENGTH_SEC - self.match_ended_at_sec if self.attacker_wins else -(MATCH_LENGTH_SEC - self.match_ended_at_sec)

    def to_dict(self) -> dict:
        return {
            "attacker_wins": self.attacker_wins,
            "match_ended_at_sec": self.match_ended_at_sec,
            "end_reason": self.end_reason,
            "attacker_total_damage": self.attacker_total_damage,
            "defender_total_damage": self.defender_total_damage,
            "attacker_hp_remaining": self.attacker_hp_remaining,
            "defender_hp_remaining": self.defender_hp_remaining,
            "win_margin": self.win_margin,
            "notes": list(self.notes),
        }


def _team_metrics(team: TeamEvaluation, opponent_avg_def: float) -> dict:
    """Pre-compute per-team aggregates: sustained DPS rate, burst payload,
    heal rate, total HP/shield. These are constant during the match
    (we don't model death-induced DPS loss yet — TODO follow-up).
    """
    sustained_dps = 0.0
    burst_payload = 0.0
    has_shields_to_break = opponent_avg_def > 0  # placeholder; refine when needed

    for m in team.members:
        eff_atk = m.effective_atk
        if eff_atk <= 0:
            continue
        weapon_factor = WEAPON_DAMAGE_PER_SECOND_FRACTION.get(
            (m.weapon_class or "").upper(), 0.10
        )
        atk_mult = _per_member_atk_damage_multiplier(m)
        def_factor = max(
            MIN_DAMAGE_FRACTION_THROUGH_DEF,
            _def_reduction_factor(eff_atk, opponent_avg_def),
        )
        # Sustained channels (atk + true + other)
        sustained_dps += eff_atk * atk_mult * def_factor * weapon_factor
        sustained_dps += eff_atk * (m.true_damage_buff_pct / 100.0) * weapon_factor
        other_mult = (
            (m.pierce_damage_buff_pct / 100.0) * 0.5
            + (m.shield_damage_buff_pct / 100.0) * 0.3
            + (m.sustained_damage_buff_pct / 100.0) * 0.2
        )
        sustained_dps += eff_atk * other_mult * weapon_factor
        # Burst payload — landed in one shot at burst time, not amortized.
        burst_payload += m.burst_damage_magnitude * eff_atk * def_factor

    base_hp = sum(m.base_hp + m.flat_hp_bonus for m in team.members)
    shield = sum(m.shield_value for m in team.members)
    # Team heal rate: take MAX (as in damage.py) to avoid 5× over-counting
    # all-allies heal effects which populate every member's heal_per_second
    # with the same source value.
    heal_per_sec = max((m.heal_per_second for m in team.members), default=0.0)
    heal_duration = max((m.heal_duration for m in team.members), default=0.0)

    return {
        "sustained_dps": sustained_dps,
        "burst_payload": burst_payload,
        "base_hp": base_hp,
        "shield": shield,
        "heal_per_sec": heal_per_sec,
        "heal_duration": heal_duration,
    }


def simulate(
    attacker: TeamEvaluation,
    defender: TeamEvaluation,
    *,
    first_burst_sec: Optional[float] = None,
    defender_first_burst_sec: Optional[float] = None,
    cycle_period_sec: float = DEFAULT_CYCLE_PERIOD_SEC,
    match_length_sec: float = MATCH_LENGTH_SEC,
    dt: float = 1.0,
    attacker_cubes: Optional[list[tuple[Optional[str], Optional[int]]]] = None,
    defender_cubes: Optional[list[tuple[Optional[str], Optional[int]]]] = None,
) -> TimeSteppedResult:
    """Run a discrete-time match simulation and return who's left standing.

    Both teams take damage simultaneously each second. Bursts fire at
    each team's own derived first_burst_sec (and every
    ``cycle_period_sec`` afterwards). Heals apply for ``heal_duration``
    seconds following each burst. The match ends when either team's HP
    hits 0 or the timer reaches ``match_length_sec``. In NIKKE PvP, the
    defender wins on timeout.

    When ``first_burst_sec`` / ``defender_first_burst_sec`` are None,
    they're auto-derived from each team's weapon mix + character skill
    bonuses + cube contributions (Quantum cubes accelerate burst gen,
    decisive in tight Champions Arena matches). Pass cube info via
    ``attacker_cubes`` / ``defender_cubes`` as ``[(cube_name,
    cube_level), ...]`` lists in member order.
    """
    if first_burst_sec is None:
        first_burst_sec = derive_first_burst_sec(attacker, attacker_cubes)
    if defender_first_burst_sec is None:
        defender_first_burst_sec = derive_first_burst_sec(defender, defender_cubes)
    # Pre-compute team metrics — both teams use the OPPOSING team's avg
    # DEF for damage-through calculations.
    a_avg_def = (
        sum(m.effective_def for m in attacker.members) / max(len(attacker.members), 1)
    )
    d_avg_def = (
        sum(m.effective_def for m in defender.members) / max(len(defender.members), 1)
    )
    a = _team_metrics(attacker, opponent_avg_def=d_avg_def)
    d = _team_metrics(defender, opponent_avg_def=a_avg_def)

    # Initial HP including post-burst-chain shields (one-time, granted at t=0).
    a_hp = a["base_hp"] + a["shield"]
    d_hp = d["base_hp"] + d["shield"]
    a_max_hp = a_hp
    d_max_hp = d_hp

    a_total_damage_dealt = 0.0
    d_total_damage_dealt = 0.0

    a_timeline: list[float] = []
    d_timeline: list[float] = []
    notes: list[str] = []

    # Per-team burst schedules — each team bursts at their own derived
    # first_burst_sec. Faster team bursts first; this is THE pivotal
    # PvP advantage at peer LV-400.
    def _burst_schedule(t0: float) -> list[float]:
        out: list[float] = []
        t_b = t0
        while t_b < match_length_sec:
            out.append(t_b)
            t_b += cycle_period_sec
        return out
    a_burst_times = _burst_schedule(first_burst_sec)
    d_burst_times = _burst_schedule(defender_first_burst_sec)
    a_burst_set = set(int(t) for t in a_burst_times)
    d_burst_set = set(int(t) for t in d_burst_times)

    t = 0.0
    end_reason = "timeout"
    while t < match_length_sec:
        # Sustained damage — applied each second.
        d_dmg_this_tick = a["sustained_dps"] * dt
        a_dmg_this_tick = d["sustained_dps"] * dt

        # Burst payload — each team's burst lands on their own schedule.
        if int(t) in a_burst_set:
            d_dmg_this_tick += a["burst_payload"]
        if int(t) in d_burst_set:
            a_dmg_this_tick += d["burst_payload"]

        # Apply damage (both simultaneously)
        d_hp -= d_dmg_this_tick
        a_hp -= a_dmg_this_tick
        a_total_damage_dealt += d_dmg_this_tick
        d_total_damage_dealt += a_dmg_this_tick

        # Healing — applies during heal_duration seconds following each
        # team's burst. Each team only heals during their OWN burst
        # windows.
        if a["heal_per_sec"] > 0 and any(
            bt <= t < bt + a["heal_duration"] for bt in a_burst_times
        ):
            a_hp = min(a_max_hp, a_hp + a["heal_per_sec"] * dt)
        if d["heal_per_sec"] > 0 and any(
            bt <= t < bt + d["heal_duration"] for bt in d_burst_times
        ):
            d_hp = min(d_max_hp, d_hp + d["heal_per_sec"] * dt)

        a_timeline.append(max(0, a_hp))
        d_timeline.append(max(0, d_hp))

        # Death checks — if both hit 0 in the same tick, the team that
        # had more remaining HP at start-of-tick wins (tiebreaker by
        # damage rate proxy — but in practice ties are rare).
        attacker_dead = a_hp <= 0
        defender_dead = d_hp <= 0
        if attacker_dead and defender_dead:
            # Mutual KO — defender wins per NIKKE convention (defender
            # advantage on edge cases).
            end_reason = "mutual_ko_defender_wins"
            t += dt
            break
        if defender_dead:
            end_reason = "defender_cleared"
            t += dt
            break
        if attacker_dead:
            end_reason = "attacker_cleared"
            t += dt
            break

        t += dt

    out = TimeSteppedResult(
        attacker_wins=(end_reason == "defender_cleared"),
        match_ended_at_sec=t,
        end_reason=end_reason,
        attacker_total_damage=a_total_damage_dealt,
        defender_total_damage=d_total_damage_dealt,
        attacker_hp_remaining=max(0, a_hp),
        defender_hp_remaining=max(0, d_hp),
        attacker_hp_timeline=a_timeline,
        defender_hp_timeline=d_timeline,
        notes=notes,
    )
    return out
