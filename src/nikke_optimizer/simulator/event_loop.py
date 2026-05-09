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

from . import registry
from .damage import (
    DEFAULT_FIRST_BURST_SEC,
    MATCH_LENGTH_SEC,
    MIN_DAMAGE_FRACTION_THROUGH_DEF,
    WEAPON_DAMAGE_PER_SECOND_FRACTION,
    _def_reduction_factor,
    _per_member_atk_damage_multiplier,
)
from .dsl import (
    CharacterSkillSet,
    EffectKind,
    TargetKind,
    TriggerKind,
)
from .evaluator import TeamEvaluation
from .timeline import (
    BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC,
    BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC,
)


# Effect kinds that multiply outgoing damage. Each adds a flat % to a
# team-wide damage multiplier while the buff is active. (BUFF_ATK is
# the most common; the *_DAMAGE kinds are damage-type specific.)
_DAMAGE_BUFF_KINDS: frozenset[EffectKind] = frozenset({
    EffectKind.BUFF_ATK,
    EffectKind.BUFF_ATTACK_DAMAGE,
    EffectKind.BUFF_TRUE_DAMAGE,
    EffectKind.BUFF_CRIT_DAMAGE,
    EffectKind.BUFF_CHARGE_DAMAGE,
    EffectKind.BUFF_PIERCE_DAMAGE,
    EffectKind.BUFF_ELEMENT_DAMAGE,
    EffectKind.BUFF_CORE_DAMAGE,
    EffectKind.BUFF_DAMAGE_TO_PARTS,
    EffectKind.BUFF_SUSTAINED_DAMAGE,
    EffectKind.BUFF_BURST_SKILL_DAMAGE,
    EffectKind.BUFF_SHIELD_DAMAGE,
})

# Trigger kinds that fire during a chain. ALWAYS triggers are baked into
# baseline already; we only schedule the chain-conditional ones.
_BURST_TRIGGER_KINDS: frozenset[TriggerKind] = frozenset({
    TriggerKind.ON_BURST_USE,
    TriggerKind.ON_ALLY_BURST_USE,
    TriggerKind.ON_FULL_BURST_START,
})

# Target kinds that count as buffing the team (i.e. boosting our DPS).
_ALLY_TARGET_KINDS: frozenset[TargetKind] = frozenset({
    TargetKind.SELF,
    TargetKind.ALL_ALLIES,
    TargetKind.NEAREST_ALLIES,
    TargetKind.ALLY_HIGHEST_ATK,
    TargetKind.ALLY_LOWEST_HP,
    TargetKind.BURST_USER,
})

# Target kinds that count as debuffing the enemy (i.e. boosting our DPS
# via reduced enemy DEF or ATK).
_ENEMY_TARGET_KINDS: frozenset[TargetKind] = frozenset({
    TargetKind.ALL_ENEMIES,
    TargetKind.ENEMY_HIGHEST_HP,
    TargetKind.ENEMY_LOWEST_HP,
    TargetKind.ENEMY_FRONT,
    TargetKind.ENEMIES_RANDOM_K,
    TargetKind.PRIMARY_TARGET,
})


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


# Per-character shots-per-second overrides. Most Nikkes follow the
# weapon-class default, but a few have unique mechanics that change
# their effective per-shot cadence:
#
# - Snow White: Heavy Arms — technically SR but her "Seven Dwarves"
#   weapon fires 5 sequential pierce shots per 1.2s charge (15 during
#   burst). Effective shots/sec = 5 / 1.2 = ~4.17 out of burst. Without
#   this override the per-shot damage is ~8x too large in the event-loop
#   per-shot damage model, which one-shots defenders before bursts fire.
#   Source: nikke.gg/snow-white-heavy-arms-analysis-should-you-pull
# - Modernia — wind-up MG with full-auto sustained fire, fires faster
#   than baseline MG once spun up.
# - SAnis (Anis: Sparkling Summer) — burst-skill-modified weapon.
SHOTS_PER_SEC_OVERRIDES: dict[str, float] = {
    "Snow White: Heavy Arms": 4.17,  # 5 shots / 1.2s charge cycle
    "Modernia": 50.0,                # ~50/s post wind-up
    "Alice": 0.6,                    # charge SR with ammo magazine
    "Maxwell": 0.5,                  # SR-style charge
    "Red Hood": 12.0,                # AR/SMG hybrid in PvE; AR base in PvP
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
    atk: float                # peak per-shot damage (full-burst stack)
    base_atk: float           # baseline per-shot damage (passive only)
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
    skills: Optional[CharacterSkillSet] = None  # DSL data for this Nikke
    alive: bool = True
    damage_dealt: float = 0.0
    damage_taken: float = 0.0


@dataclass
class _ActiveBuff:
    """One scheduled buff with an expiration time."""
    expires_at: float
    magnitude_pct: float  # added to team-wide damage multiplier
    kind: EffectKind


@dataclass
class _ActiveDebuff:
    """Defense debuff applied to enemy team."""
    expires_at: float
    magnitude_pct: float  # % DEF reduction


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


def _enumerate_burst_buffs(
    skills: CharacterSkillSet,
) -> tuple[float, float]:
    """Return (team_damage_uplift_pct, enemy_def_reduction_pct).

    Sums all burst-window damage % buffs targeting allies, and all
    DEF debuffs targeting enemies. Used to:
      1. Decompose snapshot ATK into baseline (passive) + burst-window.
      2. Identify what to schedule when a chain fires.

    Effects with NEAREST_ALLIES weight by count/5 since they only hit
    a subset of the team.
    """
    team_uplift = 0.0
    enemy_def_reduction = 0.0
    for slot in (skills.skill1, skills.skill2, skills.burst_skill):
        for se in slot:
            if se.trigger.kind not in _BURST_TRIGGER_KINDS:
                continue
            for eff in se.effects:
                if eff.duration_seconds <= 0:
                    continue
                if (eff.kind in _DAMAGE_BUFF_KINDS
                        and eff.target.kind in _ALLY_TARGET_KINDS):
                    weight = (
                        eff.target.count / 5.0
                        if eff.target.kind == TargetKind.NEAREST_ALLIES
                        else 1.0
                    )
                    team_uplift += eff.magnitude * weight
                elif (eff.kind == EffectKind.DEBUFF_DEFENSE
                        and eff.target.kind in _ENEMY_TARGET_KINDS):
                    enemy_def_reduction += eff.magnitude
    return team_uplift, enemy_def_reduction


def _team_burst_uplift_total(team_skills: list[Optional[CharacterSkillSet]]) -> tuple[float, float]:
    """Sum of (uplift, def_reduction) across team."""
    u_total = 0.0
    d_total = 0.0
    for skills in team_skills:
        if skills is None:
            continue
        u, d = _enumerate_burst_buffs(skills)
        u_total += u
        d_total += d
    return u_total, d_total


def _build_member(
    snap, opponent_avg_def: float, total_burst_uplift_pct: float,
    member_peak_dps: float,
) -> EventLoopMember:
    """Convert a NikkeSnapshot into runtime EventLoopMember state.

    ``member_peak_dps`` is the calibrated allocation from team
    ``dps_estimate`` (already calibrated against tournament data) so we
    don't re-derive DPS from scratch — that path produces nonphysical
    per-shot damages because snapshot ATK has many compounding buffs
    baked in.
    """
    weapon = (snap.weapon_class or "").lower()
    sps = SHOTS_PER_SEC_OVERRIDES.get(
        snap.name, SHOTS_PER_SEC_BY_WEAPON.get(weapon, 5.0)
    )
    eff_atk = snap.effective_atk
    def_factor = max(
        MIN_DAMAGE_FRACTION_THROUGH_DEF,
        _def_reduction_factor(eff_atk, opponent_avg_def),
    )
    # Burst payload precomputed from snapshot.
    burst = snap.burst_damage_magnitude * eff_atk * def_factor
    peak_per_shot = member_peak_dps / sps if sps > 0 else 0.0
    # Decompose into baseline (passive only) and burst-window peak.
    # Snapshot is the "all buffs active" peak; baseline divides out the
    # burst-window uplift so out-of-burst damage doesn't double-count it.
    base_per_shot = peak_per_shot / max(1.0 + total_burst_uplift_pct / 100.0, 1.0)
    skills = registry.get(snap.name)

    return EventLoopMember(
        name=snap.name,
        hp=float(snap.base_hp + snap.flat_hp_bonus),
        max_hp=float(snap.base_hp + snap.flat_hp_bonus),
        shield=float(snap.shield_value),
        atk=peak_per_shot,
        base_atk=base_per_shot,
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
        skills=skills,
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


def _schedule_chain_buffs(
    chain: list[EventLoopMember],
    ally_team: list[EventLoopMember],
    enemy_team: list[EventLoopMember],
    current_time: float,
    active_buffs: list[_ActiveBuff],
    active_debuffs: list[_ActiveDebuff],
) -> None:
    """Walk each chain member's burst-triggered effects and schedule them.

    Chain firing makes ON_BURST_USE / ON_FULL_BURST_START / ON_ALLY_BURST_USE
    triggers fire. For each effect, we schedule a buff/debuff that
    expires at current_time + duration_seconds.

    Cross-stat scaling effects (CASTER_ATK etc.) are skipped here — those
    are flat ATK additions, not % multipliers, and the snapshot already
    bakes them in.
    """
    for caster in chain:
        if caster.skills is None:
            continue
        for slot in (caster.skills.skill1, caster.skills.skill2,
                     caster.skills.burst_skill):
            for se in slot:
                if se.trigger.kind not in _BURST_TRIGGER_KINDS:
                    continue
                for eff in se.effects:
                    if eff.duration_seconds <= 0:
                        continue
                    # Skip cross-stat scaling — flat additions, baked into snapshot.
                    from .dsl import ScalingSource
                    if eff.scaling_source != ScalingSource.NONE:
                        continue
                    if (eff.kind in _DAMAGE_BUFF_KINDS
                            and eff.target.kind in _ALLY_TARGET_KINDS):
                        weight = (
                            eff.target.count / 5.0
                            if eff.target.kind == TargetKind.NEAREST_ALLIES
                            else 1.0
                        )
                        active_buffs.append(_ActiveBuff(
                            expires_at=current_time + eff.duration_seconds,
                            magnitude_pct=eff.magnitude * weight,
                            kind=eff.kind,
                        ))
                    elif (eff.kind == EffectKind.DEBUFF_DEFENSE
                            and eff.target.kind in _ENEMY_TARGET_KINDS):
                        active_debuffs.append(_ActiveDebuff(
                            expires_at=current_time + eff.duration_seconds,
                            magnitude_pct=eff.magnitude,
                        ))


def _current_buff_multiplier(
    buffs: list[_ActiveBuff], current_time: float
) -> float:
    """Sum of currently-active damage buff %s, returned as a multiplier.

    Side effect: prunes expired buffs from the list to keep it small.
    """
    total_pct = 0.0
    buffs[:] = [b for b in buffs if b.expires_at > current_time]
    for b in buffs:
        total_pct += b.magnitude_pct
    return 1.0 + total_pct / 100.0


def _current_debuff_multiplier(
    debuffs: list[_ActiveDebuff], current_time: float
) -> float:
    """Multiplier for damage-through-DEF when enemy DEF is debuffed.

    Side effect: prunes expired debuffs.
    """
    debuffs[:] = [d for d in debuffs if d.expires_at > current_time]
    if not debuffs:
        return 1.0
    total_red = sum(d.magnitude_pct for d in debuffs)
    # Approximation: each 1% DEF reduction → ~0.5% damage uplift through
    # the def-reduction formula in the typical level-difference regime.
    # Real formula is in damage._def_reduction_factor; this is a
    # first-order linearization.
    return 1.0 + total_red / 200.0


def simulate_event_loop(
    attacker: TeamEvaluation,
    defender: TeamEvaluation,
    *,
    tick_dt: float = DEFAULT_TICK_DT_SEC,
    match_length_sec: float = MATCH_LENGTH_SEC,
) -> EventLoopResult:
    """Event-loop match resolution at 10 Hz with DSL effect scheduling.

    Differences from ``simulate_per_character``:
    1. Burst gauge fills via per-shot accumulation, not preset
       ``first_burst_sec`` schedule. A team's first chain fires when
       the gauge actually hits 100.
    2. Each Nikke fires shots on her own ``shots_per_sec`` cadence
       (clip reload approximated by uniform fire rate).
    3. Death events propagate: when a Nikke dies, her shots stop AND
       team burst-gen rate recomputes for the next tick.
    4. Buffs are scheduled per-chain-fire from the DSL: each chain
       activates burst-window buffs that expire at +duration_seconds.
       Out-of-burst-window damage uses ``base_atk`` (snapshot ATK with
       burst-window uplift removed).
    """
    a_avg_def = sum(m.effective_def for m in attacker.members) / max(
        len(attacker.members), 1
    )
    d_avg_def = sum(m.effective_def for m in defender.members) / max(
        len(defender.members), 1
    )

    # Compute team-wide burst-window uplift from DSL to decompose snapshot.
    a_skills = [registry.get(m.name) for m in attacker.members]
    d_skills = [registry.get(m.name) for m in defender.members]
    a_uplift_pct, _ = _team_burst_uplift_total(a_skills)
    d_uplift_pct, _ = _team_burst_uplift_total(d_skills)

    # Allocate calibrated team DPS proportionally by member ATK weight.
    # ``dps_estimate`` is the in-burst peak (already calibrated against
    # tournament outcomes) — we slice it by member contribution.
    def _member_dps_alloc(team_eval) -> list[float]:
        weights = [max(m.effective_atk, 1.0) for m in team_eval.members]
        total = sum(weights)
        return [team_eval.dps_estimate * w / total for w in weights]

    a_member_dps = _member_dps_alloc(attacker)
    d_member_dps = _member_dps_alloc(defender)

    a_team = [
        _build_member(m, d_avg_def, a_uplift_pct, dps)
        for m, dps in zip(attacker.members, a_member_dps)
    ]
    d_team = [
        _build_member(m, a_avg_def, d_uplift_pct, dps)
        for m, dps in zip(defender.members, d_member_dps)
    ]

    a_gauge = 0.0
    d_gauge = 0.0
    a_first_burst_at = 0.0
    d_first_burst_at = 0.0
    a_chain_starts: list[float] = []
    d_chain_starts: list[float] = []
    a_total = 0.0
    d_total = 0.0
    a_active_buffs: list[_ActiveBuff] = []
    d_active_buffs: list[_ActiveBuff] = []
    a_active_debuffs: list[_ActiveDebuff] = []  # debuffs ON enemy team
    d_active_debuffs: list[_ActiveDebuff] = []
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

        # Damage multipliers from DSL-scheduled buffs/debuffs. Replaces
        # the constant 0.55 decay heuristic — buffs decay individually
        # as they expire, so e.g. a 10s ATK buff lasts exactly 10s.
        a_buff_mult = _current_buff_multiplier(a_active_buffs, t)
        d_buff_mult = _current_buff_multiplier(d_active_buffs, t)
        a_def_debuff_mult = _current_debuff_multiplier(a_active_debuffs, t)
        d_def_debuff_mult = _current_debuff_multiplier(d_active_debuffs, t)

        # Each living Nikke fires shots whose timer has elapsed.
        # Damage = base_per_shot × team_buff_mult × enemy_def_debuff_mult.
        for m in a_living:
            shot_dmg = m.base_atk * a_buff_mult * a_def_debuff_mult
            while m.next_shot_at <= t and m.alive:
                applied = _apply_damage(d_team, shot_dmg)
                a_total += applied
                m.damage_dealt += applied
                m.next_shot_at += 1.0 / max(m.shots_per_sec, 0.001)
                if not [x for x in d_team if x.alive]:
                    break
        for m in d_living:
            shot_dmg = m.base_atk * d_buff_mult * d_def_debuff_mult
            while m.next_shot_at <= t and m.alive:
                applied = _apply_damage(a_team, shot_dmg)
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
                _schedule_chain_buffs(
                    chain, a_team, d_team, t,
                    a_active_buffs, a_active_debuffs,
                )
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
                _schedule_chain_buffs(
                    chain, d_team, a_team, t,
                    d_active_buffs, d_active_debuffs,
                )
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
