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

import random
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


# Phase 6 calibration constants — buff decay model.
#
# NIKKE post-burst-chain DPS is "peak DPS" with all burst-window
# buffs active. Outside the burst window, those time-bounded buffs
# (typically 10-15s) drop off. Sustained DPS averaged over a 40s
# cycle is much lower than peak.
#
# Burst window: the ~10s following each chain when team has full
# stacks. Approximated as ``BURST_WINDOW_DURATION_SEC`` after the
# chain time.
#
# Outside-burst-window factor: how much of peak DPS persists when
# burst buffs decay. Calibrated against the gap between published
# burst-window vs sustained DPS measurements (~50% retention is
# typical for Crown comps; lower for buff-heavy teams).
BURST_WINDOW_DURATION_SEC = 10.0
POST_BURST_DPS_RETENTION = 0.55


@dataclass
class MemberState:
    """Per-character runtime state during a per-char simulation."""

    name: str
    max_hp: float
    hp: float
    shield: float                # remaining shield, absorbs damage first
    sustained_dps: float         # PEAK damage rate (all burst buffs active)
    burst_payload: float         # per-target burst damage from this Nikke
    eff_def: float               # used by attacker's def_factor calc
    role: str                    # "attacker"/"defender"/"supporter"/etc.
    burst_position: str = "flex"  # "1"/"2"/"3"/"flex" — chain ordering
    burst_cooldown_sec: float = 20.0
    burst_ready_at: float = 0.0  # next sim-time the burst can fire
    is_taunting: bool = False    # taunters absorb most damage
    weapon_class: str = ""        # "ar" / "smg" / "mg" / "sg" / "sr" / "rl"
    element: str = ""             # "fire" / "water" / "electric" / "iron" / "wind"
    heal_per_second: float = 0.0
    heal_duration: float = 0.0
    heal_emit_per_second: float = 0.0
    heal_emit_duration: float = 0.0
    stunned_until: float = -1.0  # sim time until which this Nikke is stunned
                                  # (can't fire bursts, deals no damage)
    invuln_until: float = -1.0   # damage immunity / indomitability window
                                  # (incoming damage skips this member entirely)
    taunt_until: float = -1.0    # time-bounded taunt (replaces static is_taunting
                                  # for duration-bounded effects like Noah burst)
    concealment_until: float = -1.0  # Rosanna-style single-target-immunity state
                                       # (cannot be targeted; also triggers her
                                       # conditional burst-damage bonus)
    stack_count: int = 0         # for Cinderella's "Beautiful bonus", Modernia
                                  # reload stacks, etc. (set per tick)
    burst_target_count: int = 1  # how many enemies this caster's burst hits
    alive: bool = True
    damage_dealt: float = 0.0    # cumulative for output
    damage_taken: float = 0.0    # cumulative for output
    healing_dealt: float = 0.0   # cumulative healing this Nikke emitted

    @property
    def is_healer(self) -> bool:
        return self.heal_emit_per_second > 0 or self.heal_per_second > 0


def _dps_decay_factor(t: float, chain_starts: list[float]) -> float:
    """Return the effective DPS multiplier at time ``t``.

    Pre-first-burst (no chain has fired yet) and during any burst
    window (within BURST_WINDOW_DURATION_SEC of a chain start):
    return 1.0 — the team is at peak DPS.

    Between burst windows (after first chain has expired but before
    the next): return POST_BURST_DPS_RETENTION (0.55).
    """
    if not chain_starts:
        return 1.0
    in_burst_window = any(
        bt <= t < bt + BURST_WINDOW_DURATION_SEC for bt in chain_starts
    )
    return 1.0 if in_burst_window else POST_BURST_DPS_RETENTION


# State-machine ramps (Phase 7) — time-dependent damage scaling for
# Nikkes whose effective DPS is gated by a state machine the simulator
# doesn't model directly (Lock-On stacks, MP gauge, Relax stacks,
# Bay-Goddess pose toggles, etc.). Each entry is a callable
# ``factor(t, chain_starts) -> float`` so we can model real ramp-up
# rather than a flat constant.
#
# The shape follows the in-game pattern:
#   - SW:HA Lock-On: damage proportional to stack count, max around
#     full burst window; modeled as 0.4 → 1.0 ramp over the first 12s
#     and held while a chain has fired in the last 12s.
#   - Crown Relax: only active during burst window (3+ ally bursts in
#     chain); 0.4 baseline outside the window, 1.1 inside.
#   - Modernia: Reload Frequency stacks; ~50% pre-burst, 100% during
#     burst window, 80% sustained outside.
#   - Liberalio: Burst Skill 2 delayed cast on burst; effective DPS
#     during cooldown ramps with chain count; 0.4 base, 0.85 in window.
#   - Moran / Mary: Bay-Goddess pose toggle gates DPS to alternating
#     windows; ~0.55 average.
#   - Cinderella: S2 hit-counter gates one big shot per cycle; 0.6 avg.
#
# Conservative magnitudes — better than 1.0 for chars with verified
# in-game ramp behavior, but deliberately not so aggressive that close
# matches flip outcomes spuriously.

def _factor_swha(t: float, chain_starts: list[float]) -> float:
    # SW:HA Lock-On reticles build every 0.2s during charge, up to 5
    # targets, each +42.24% DEF and unlocks auto-fire sequential attack.
    # In PvP locks within 1-2s of first full-charge. Burst window adds
    # her sequential pierce attacks (105.59% per locked target).
    if not chain_starts:
        return 0.5 + min(0.4, t / 3.0 * 0.4)  # 0.5 → 0.9 over 3s lock-on
    last = chain_starts[-1]
    in_window = (t - last) <= BURST_WINDOW_DURATION_SEC
    return 1.6 if in_window else 0.85


def _factor_crown(t: float, chain_starts: list[float]) -> float:
    if not chain_starts:
        return 0.4
    last = chain_starts[-1]
    return 1.1 if (t - last) <= BURST_WINDOW_DURATION_SEC else 0.4


def _factor_modernia(t: float, chain_starts: list[float]) -> float:
    if not chain_starts:
        return 0.5
    last = chain_starts[-1]
    return 1.0 if (t - last) <= BURST_WINDOW_DURATION_SEC else 0.8


def _factor_liberalio(t: float, chain_starts: list[float]) -> float:
    # Liberalio's burst skill text "925% to all enemies" is conditional
    # on her Raging Current state, which requires a Full-Charge core
    # hit on the stage target FIRST. In short matches she rarely cycles
    # into the active state. Beta-29 R4 shows her dealing 4M total when
    # the formula predicts 50M+. Use a heavy gate to match observed
    # output. Outside Raging Current state the burst still fires but
    # at far reduced damage.
    if not chain_starts:
        return 0.15
    last = chain_starts[-1]
    return 0.20 if (t - last) <= BURST_WINDOW_DURATION_SEC else 0.10


def _factor_moran(t: float, chain_starts: list[float]) -> float:
    # Bay-Goddess pose toggles damage windows; effective average ~70%
    # (slightly above naive 0.5 because the high-damage poses are
    # consistently triggered during Full Burst).
    return 0.70


def _factor_cinderella(t: float, chain_starts: list[float]) -> float:
    # S2 hit-counter gates one charged shot per ~3s cycle.
    return 0.65


def _factor_pose_carry(t: float, chain_starts: list[float]) -> float:
    # Generic "pose carry" pattern — Bay variants, Mary variants, etc.
    return 0.65


def _factor_scarlet(t: float, chain_starts: list[float]) -> float:
    # OG Scarlet's burst remaps S1 proc threshold from 3/6/9 → 1/2/3
    # for 10s. During burst window she procs S1 ~3× more often.
    if not chain_starts:
        return 0.6
    last = chain_starts[-1]
    return 1.6 if (t - last) <= BURST_WINDOW_DURATION_SEC else 0.7


def _factor_sbs(t: float, chain_starts: list[float]) -> float:
    # Scarlet:BS — similar burst-window mechanic. Her burst buffs ATK
    # +115% and Charge Damage +150% for 10s. Already partially in
    # snapshot, but the multi-hit S1 proc compounds it.
    if not chain_starts:
        return 0.6
    last = chain_starts[-1]
    return 2.0 if (t - last) <= BURST_WINDOW_DURATION_SEC else 0.7


_RAMP_UP_FUNCS: dict[str, callable] = {
    "Snow White: Heavy Arms": _factor_swha,
    "Crown": _factor_crown,
    "Modernia": _factor_modernia,
    "Liberalio": _factor_liberalio,
    "Moran": _factor_moran,
    "Moran (Treasure)": _factor_moran,
    "Mary": _factor_pose_carry,
    "Mary: Bay Goddess": _factor_pose_carry,
    "Cinderella": _factor_cinderella,
    "Scarlet": _factor_scarlet,
    "Scarlet: Black Shadow": _factor_sbs,
    # Aggressive Lock-On family (Snow White / Drake-style triple-shot)
    "Drake": _factor_swha,
    "Drake (Treasure)": _factor_swha,
}


def _state_machine_factor(
    member_name: str,
    t: float = 0.0,
    chain_starts: Optional[list[float]] = None,
) -> float:
    """Return the time-dependent damage factor for a state-machine carry.

    Defaults to 1.0 (no adjustment) for characters without a registered
    ramp function. ``t`` is current sim time; ``chain_starts`` is the
    list of (this character's team's) chain fire times so far so the
    ramp can react to burst windows.
    """
    fn = _RAMP_UP_FUNCS.get(member_name)
    if fn is None:
        return 1.0
    return fn(t, chain_starts or [])


def _sustained_stack_multiplier(
    member_name: str, t: float, chain_starts: list[float],
) -> float:
    """Compute the per-character stack multiplier on sustained DPS.

    Integrates time × hit_rate to estimate stack count at time ``t``.
    For chars where stacks only apply during burst window, returns 1.0
    outside the window.

    Returns 1.0 for chars without a stack rule (most chars).
    """
    spec = _SUSTAINED_STACK_RULES.get(member_name)
    if spec is None:
        return 1.0
    hit_rate, hits_per_stack, max_stacks, dmg_per_stack_pct, only_in_burst = spec
    if only_in_burst:
        # Only stack during burst window. Count hits since most recent
        # chain start (or 0 if no chain has fired).
        if not chain_starts:
            return 1.0
        last_chain = chain_starts[-1]
        if t > last_chain + BURST_WINDOW_DURATION_SEC:
            return 1.0  # outside burst window
        elapsed = t - last_chain
    else:
        elapsed = t  # from battle start
    hits = max(0.0, elapsed) * hit_rate
    stacks = min(max_stacks, int(hits / hits_per_stack))
    return 1.0 + (stacks * dmg_per_stack_pct / 100.0)


def _select_burst_chain(
    team: list[MemberState],
    current_time: float,
) -> list[MemberState]:
    """Return the 3 Nikkes that fire in this burst chain, in fire order.

    NIKKE PvP chain rule (per the user's note 2026-05-09):
      - One B1, one B2, one B3 fire per chain.
      - For each position, the LEFTMOST eligible (alive + off-cooldown)
        Nikke fires.
      - Flex-burst Nikkes fill any open slot.

    If a position has no eligible filler, that slot is empty for this
    chain (rare with proper team comps). Returns the chain ordered
    [B1_pick, B2_pick, B3_pick] — that's the in-game cast order.
    """
    chain: list[MemberState] = []
    used: set[int] = set()
    # team is in left-to-right order (member position).
    for position in ("1", "2", "3"):
        # First-pass: exact match leftmost.
        candidate = None
        for i, m in enumerate(team):
            if i in used or not m.alive:
                continue
            if m.stunned_until > current_time:
                continue  # stunned — can't fire burst
            if m.burst_ready_at > current_time:
                continue
            if m.burst_position == position:
                candidate = (i, m)
                break
        # Second-pass: flex fill.
        if candidate is None:
            for i, m in enumerate(team):
                if i in used or not m.alive:
                    continue
                if m.stunned_until > current_time:
                    continue
                if m.burst_ready_at > current_time:
                    continue
                if m.burst_position == "flex":
                    candidate = (i, m)
                    break
        if candidate is not None:
            used.add(candidate[0])
            chain.append(candidate[1])
    return chain


_ROLE_DPS_SCALE = {
    # Calibrated against beta-29 captures (4/5 outcome accuracy).
    "attacker": 0.20,
    "defender": 0.08,
    "supporter": 0.04,
}

# Per-name overrides for Nikkes whose role tag doesn't match their PvP
# damage profile. E.g. Liberalio is a single-target carry (attacker)
# but in beta-29 captures her real damage is 5–25% of "attacker" yield
# because her burst skill is conditional on Raging Current / focuses ST.
_NAME_DPS_SCALE = {
    # Per-name overrides — relative to the role default.
    # Pure-DPS carries with sustained channels: full attacker rate.
    "Vesti: Tactical Upgrade": 0.85,
    "Scarlet": 0.40,
    "Scarlet: Black Shadow": 0.35,
    "Snow White: Heavy Arms": 0.85,
    "Modernia": 0.85,
    "Red Hood": 0.05,
    "Emilia": 0.10,                    # actual varies; lower scale fits both R2 + R3 KYU
    "Nayuta": 0.05,
    "Rumani": 0.07,
    # Pilgrim B1 carries — these are SUPPORTS in PvP, not damage dealers
    "Liberalio": 0.03,
    "Anis: Star": 0.04,
    "Rapunzel": 0.05,
    "Rapunzel: Pure Grace": 0.30,
    "Anis: Sparkling Summer": 0.55,
    # Defenders / utility w/ "attacker" tag
    "Cinderella": 0.50,
    "Helm (Treasure)": 0.10,
    "Helm: Aquamarine": 0.20,
    "Drake": 0.55,
    "Drake (Treasure)": 0.90,
    "Rosanna": 1.40,                         # actual 12.4M in ~7s — heavy B1 carry
    "Rosanna: Chic Ocean": 0.85,
    "Soda: Twinkling Bunny": 0.95,
    "Maiden: Ice Rose": 0.50,
    "Mary": 0.50,
    "Mary: Bay Goddess": 0.50,
    # Healers / supports — light auto-fire damage in PvP (they mostly
    # cast skills, but their basic shots still hit). Validation showed
    # 0.05 wiped out outcome accuracy by removing too much offense.
    "Bay": 0.10,
    "Bay (Treasure)": 0.12,
    "Biscuit": 0.10,
    "Moran": 0.10,
    "Moran (Treasure)": 0.10,
    "Helm": 0.20,
    "Noah": 0.10,
    "Noise": 0.15,
    "Blanc": 0.05,
    "Centi": 0.15,
    "Centi (Treasure)": 0.18,
    "Little Mermaid (Siren)": 0.03,
    "Trina": 0.15,
    "Poli": 0.10,
    "Poli (Treasure)": 0.15,
    "Soda": 0.18,
    "Anis": 0.15,
    "Noir": 0.30,
    "Laplace": 0.30,
    "Laplace (Treasure)": 0.35,
    "Jackal": 0.15,
    "Ada Wong": 0.05,                   # collab B3 RL; actuals show very low dps
    "Label": 0.08,
}


def _dps_role_scale(
    name: str, role: Optional[str], burst_position: Optional[str] = None,
    weapon_class: Optional[str] = None,
) -> float:
    """Per-character DPS realism scale.

    Resolution order:
      1. Explicit ``_NAME_DPS_SCALE`` override (per-character).
      2. Archetype-derived default: combines burst_position + role +
         weapon_class into a "PvP profile" guess.
      3. Role default from ``_ROLE_DPS_SCALE`` as final fallback.

    Archetype rules (derived from beta-29 observations):
      - B3 attackers with SR/AR/RL → 0.55 (canonical carry slot)
      - B3 attackers with SG/MG/SMG → 0.45 (sub-carry, conditional)
      - B2 supporter with SR/AR → 0.10 (utility, not damage)
      - B2 supporter/defender with any → 0.08
      - B1 supporter → 0.05 (almost no damage in PvP)
      - B1 attacker (Liter-type) → 0.15 (some autofire, mostly buff)
      - flex SR → 0.25 (one-shot snipers)
    """
    if name in _NAME_DPS_SCALE:
        return _NAME_DPS_SCALE[name]
    role_lc = (role or "").lower()
    bp = (burst_position or "flex").lower()
    wc = (weapon_class or "").lower()
    # B3 carries
    if bp == "3":
        if role_lc == "attacker":
            return 0.55 if wc in ("sr", "ar", "rl") else 0.45
        return 0.15  # B3 defender/supporter — unusual but exists
    # B1 buffers / healers
    if bp == "1":
        if role_lc == "attacker":
            return 0.15
        return 0.05
    # B2 utility
    if bp == "2":
        if role_lc == "attacker":
            return 0.30
        return 0.08
    # Flex
    if wc == "sr":
        return 0.25
    return _ROLE_DPS_SCALE.get(role_lc, 0.20)


# Per-character burst-magnitude override. Some encoded ALL_ENEMIES /
# ENEMY_HIGHEST_HP bursts list the FULL conditional damage (e.g. Helm
# Treasure's 8237% which is the max-phase max-state value). In typical
# arena conditions the actual one-shot damage is far smaller. These
# overrides cap the encoded magnitude to a more realistic value.
_BURST_MAG_OVERRIDE = {
    "Helm (Treasure)": 3.0,            # 8237% in-game is conditional max
    "Helm: Aquamarine": 4.0,
    "Cinderella": 8.0,                 # lowered to compensate for stack accum bonus
    "Drake (Treasure)": 12.0,
    "Liberalio": 1.0,                  # 925% AOE × 5; 1.1s delay often cancels
    "Nayuta": 4.0,
    "Soda: Twinkling Bunny": 4.0,
    "Maiden: Ice Rose": 6.0,
    "Rosanna": 6.0,
    "Scarlet: Black Shadow": 8.0,
    "Snow White: Heavy Arms": 6.0,
    "Vesti: Tactical Upgrade": 12.0,
    "Scarlet": 8.0,
    "Laplace (Treasure)": 14.0,
    "Laplace": 8.0,
    "Anis: Star": 4.0,
    "Modernia": 10.0,
    "Red Hood": 8.0,
    "Rumani": 6.0,
    "Bay (Treasure)": 4.0,
    "Bay": 4.0,
    "Moran (Treasure)": 4.0,
    "Moran": 4.0,
    "Biscuit": 4.0,
    "Anis: Sparkling Summer": 8.0,
    "Noir": 6.0,
}


def _effective_burst_magnitude(m) -> float:
    """Return burst_damage_magnitude capped by per-name overrides."""
    base = m.burst_damage_magnitude
    if m.name in _BURST_MAG_OVERRIDE:
        return min(base, _BURST_MAG_OVERRIDE[m.name])
    return base


# Per-character burst delivery delay (seconds between burst CAST and
# DAMAGE LAND). When the caster dies in the delay window, the burst
# is CANCELLED and deals no damage. Per nikke.gg analysis:
#   - Liberalio: 1.1s — explicit weakness, often blocked in PvP
#   - Cinderella: ~1.0s spread over 10 sequential hits
# Most Nikkes have no delay (delivery is instant on cast).
_BURST_DELIVERY_DELAY_SEC: dict[str, float] = {
    "Liberalio": 1.1,
    "Cinderella": 1.0,    # 10 sequential hits over ~1s; average lands at 0.5s
}


def _burst_delivery_delay(name: str) -> float:
    return _BURST_DELIVERY_DELAY_SEC.get(name, 0.0)


# Per-character stun-on-burst effects. Each entry is (target_count, duration_sec).
# When this character fires their burst, the simulator picks ``target_count``
# random enemies and sets their stunned_until = current_t + duration_sec.
# Stunned Nikkes cannot fire bursts and deal no sustained damage during
# the stun window. Per nikke.gg / library text (2026-05-10 audit).
_STUN_ON_BURST: dict[str, tuple[int, float]] = {
    "Soda":                  (2, 1.0),
    # Rapunzel: 5 (all) but gated by HP < 30% — handled by gates
    "Rapunzel":              (5, 1.0),
    "Privaty":               (5, 3.0),   # burst stuns all enemies 3s
    "Privaty (Treasure)":    (5, 3.0),   # Treasure form: same stun
    "Takina Inoue":          (5, 2.0),   # S2 periodic stun all enemies 2s
    "Little Mermaid (Siren)": (1, 3.0),  # Explosive Bubble target stun (conditional)
}


def _stun_on_burst(name: str) -> Optional[tuple[int, float]]:
    return _STUN_ON_BURST.get(name)


def _apply_stun_to_random(
    team: list["MemberState"], count: int, stunned_until: float,
    rng: Optional["random.Random"] = None,
) -> None:
    """Stun ``count`` random living members of ``team`` until ``stunned_until``.

    When ``rng`` is provided, uses real randomization for Monte Carlo
    variance estimation. Without rng, uses a deterministic name-hash
    shuffle for reproducibility in single-run validation.
    """
    living = [(i, m) for i, m in enumerate(team) if m.alive]
    if not living:
        return
    if rng is not None:
        rng.shuffle(living)
    else:
        living.sort(key=lambda im: (hash(im[1].name) % 7, im[0]))
    for _, m in living[:count]:
        if stunned_until > m.stunned_until:
            m.stunned_until = stunned_until


# Per-character invulnerability-on-burst.
# Tuple: (target_scope, duration_sec).
# target_scope:
#   "ALLIES_ALL"        — every living ally (Noah's "Invincible 3 sec")
#   "ALLY_LOWEST_HP"    — single lowest-HP-fraction ally (Blanc indomit)
#   "ALLY_DEFENDER_LOW" — defenders with HP < 50% (Biscuit conditional)
#   "SELF"              — caster only (Poli Treasure indomitability)
_INVULN_ON_BURST: dict[str, tuple[str, float]] = {
    "Noah":            ("ALLIES_ALL",        1.0),
    "Blanc":           ("ALLY_LOWEST_HP",   10.0),
    "Biscuit":         ("ALLY_DEFENDER_LOW", 5.0),
    "Poli (Treasure)": ("SELF",              5.0),
    "Label":           ("SELF",             10.0),
    # Viper: Vamp self-invuln 1s on Full Burst entry. Pairs with her
    # concealment (cannot be single-target-attacked for 10s — modeled
    # as battle-start concealment below).
    "Viper":           ("SELF",              1.0),
}


# Indomitability-on-lethal-damage (one-shot, character can't die when
# damage would lethal). Different trigger than burst-cast invuln —
# triggers when HP would drop to 0. Limited to N uses per match.
# Tuple: (uses_per_match, duration_sec)
_INDOMIT_ON_LETHAL: dict[str, tuple[int, float]] = {
    "Makima": (1, 7.0),                  # 1×/battle indomit 7s on lethal
}


# Battle-start invulnerability windows (applied at t=0 in _per_char_states).
# Tuple: (duration_sec, target_scope).
# target_scope here is per-character — when the trigger condition fires,
# we apply invuln to the named caster. For team-target effects, set
# scope="LEFTMOST_ELECTRIC_RIFLE_ALLY" and the team-init code routes it.
_INVULN_ON_START: dict[str, tuple[float, str]] = {
    "Nayuta": (9.0, "SELF"),               # Unchanging Heart, 1×/battle
    "Trina":  (2.0, "LEFTMOST_ELECTRIC_RIFLE_ALLY"),
}


# Per-character taunt-on-burst (time-bounded; replaces static is_taunting).
# Tuple: (target_scope, duration_sec). Most are SELF.
_TAUNT_ON_BURST: dict[str, tuple[str, float]] = {
    "Noah":             ("SELF", 10.0),
    "Red Hood":         ("SELF", 10.0),
    "Moran":            ("SELF", 10.0),
    "Moran (Treasure)": ("SELF", 10.0),
    "Diesel":           ("SELF", 5.06),
    "Diesel (Treasure)":("SELF", 10.0),
    "Maiden":           ("SELF", 10.0),
}


# Battle-start sticky taunt (permanent or near-permanent aggro from t=0).
# Tuple: (duration_sec) where 99999 = effectively permanent.
_TAUNT_ON_START: dict[str, float] = {
    "Emma: Tactical Upgrade": 99999.0,   # undispellable battle-start taunt
}


# Periodic taunts triggered by sustained mechanics (every-N-normals,
# every-N-shots, etc.). Modeled as: taunt fires once at battle start,
# then refreshes every refresh_sec. (refresh_sec, duration_sec).
_TAUNT_PERIODIC: dict[str, tuple[float, float]] = {
    "Tia":      (5.0,  5.0),    # every ~5 normals (~5s) Attract-taunt 5s
    "Makima":   (20.0, 3.0),    # every 120 normals (~20s) taunt 3s
    "Mori":     (15.0, 4.0),    # every 60 normals (~15s) during Struggle taunt 4s
    "Anchor":   (4.0,  5.0),    # last-bullet (~every 4s) target taunt 5s
    "Noise":    (3.0,  2.0),    # full-charge target taunt 2s
    "Sin":      (4.0,  5.0),    # last-bullet Attract-taunt 5s
    "Folkwang": (8.0,  5.0),    # S2 single-target taunt 5s on highest-ATK
    "Crown":    (14.0, 5.0),    # Relax stacks → taunt + invuln 5s
}


# Conditional burst-fire gates: lambda taking caster MemberState
# (with `t` bound at call time via closures or via .stunned_until /
# concealment_until / etc fields). Returns bool. If False, the
# conditional bonus effects (stuns, extra damage) don't trigger.
_BURST_CONDITION_GATES: dict[str, callable] = {
    # Scarlet's burst Crit Rate +19.57% is HP < 50% gated.
    "Scarlet":     lambda m, t: (m.hp / max(m.max_hp, 1.0)) < 0.50,
    # Rapunzel's all-enemies 1s stun fires only when HP < 30%.
    "Rapunzel":    lambda m, t: (m.hp / max(m.max_hp, 1.0)) < 0.30,
    # Rosanna's +561.6% additional burst damage requires Concealment.
    "Rosanna":     lambda m, t: m.concealment_until > t,
    # Guillotine: target HP < 50% doubles burst damage. Modeled as the
    # caster's own HP < 70% (her self-stacking buff threshold) instead
    # since we can't easily check target HP at burst-fire time.
    "Guillotine":  lambda m, t: (m.hp / max(m.max_hp, 1.0)) < 0.70,
    # Alice: HP < 80% conditional buff.
    "Alice":       lambda m, t: (m.hp / max(m.max_hp, 1.0)) < 0.80,
    # Mast: HP < 70% Crit Damage buff (also applies to top-2 ATK allies).
    "Mast":        lambda m, t: (m.hp / max(m.max_hp, 1.0)) < 0.70,
}




# Battle-start state triggers. Some characters enter a special state
# (Concealment, Indomitability, etc.) when battle starts.
_CONCEALMENT_ON_START: dict[str, float] = {
    "Rosanna": 5.0,  # S2 — self Concealment 5 sec at battle start
    # Viper: Vamp grants single-target-attack immunity 10s on Full Burst
    # entry. Modeled as battle-start since FB activates fast in PvP.
    "Viper": 10.0,
}


# Conditional burst-payload bonus multiplier. When the character's
# gate (_BURST_CONDITION_GATES) returns True, multiply the base burst
# payload by this factor to capture the "+X% additional damage if
# condition" effects baked into many burst skills.
_CONDITIONAL_BURST_BONUS_MULT: dict[str, float] = {
    # Rosanna: base 1310.4% + 561.6% if Concealment = 1432% (+43%)
    "Rosanna":    1.43,
    # Guillotine: 2× burst damage if target HP < 50% (we proxy with
    # caster's own HP).
    "Guillotine": 1.50,
    "Alice":      1.20,
}


# Stack-accumulation model: characters whose burst payload scales with
# a stack count accumulated over time. (stacks_per_sec, max_stacks,
# damage_per_stack_pct). Stacks are gained from t=0 onward — at
# burst-fire time, stack count is min(t * rate, max).
# Per-character SUSTAINED-DPS stack model. Each tick, stacks accumulate
# based on time × hit_rate / threshold. Stacks scale sustained_dps via
# the per-stack damage bonus. Outside the active window (e.g. only in
# burst window), stacks are 0.
# Tuple: (hit_rate_per_sec, hits_per_stack, max_stacks, dmg_per_stack_pct, only_in_burst_window)
_SUSTAINED_STACK_RULES: dict[str, tuple[float, int, int, float, bool]] = {
    # Scarlet OG: S1 procs at 3/6/9 hits; during burst window the
    # threshold remaps to 1/2/3 hits. AR fire rate ~12/s, so during
    # burst window she procs S1 every 0.08s. Burst phase damage:
    # 250%/500%/750%. Use averaged stack bonus of ~30%/stack with
    # max 3 stacks during burst window.
    "Scarlet":              (12.0, 1, 3, 55.0, True),
    "Scarlet: Black Shadow": (12.0, 1, 3, 70.0, True),
    # Modernia: 200-hit reload-frequency stack threshold. MG fires
    # ~40/s, so reaches threshold at t=5s. After that, +29.38% ATK.
    "Modernia":             (40.0, 200, 5, 6.0, False),
    # SW:HA Lock-On builds every 0.2s during charge, max 5 targets,
    # +42.24% DEF each. We treat DEF buff as damage amp proxy.
    "Snow White: Heavy Arms": (5.0, 1, 5, 8.0, False),
    # Crown Relax: every 43 hits → 1 stack, max 20. SMG fire rate ~30/s
    # so 43 hits in ~1.5s. Each stack provides team utility, not damage.
    # Model as small +1% damage per stack on Crown's own DPS.
    "Crown":                (30.0, 43, 20, 1.0, False),
}


_STACK_ACCUMULATING_BURST: dict[str, tuple[float, int, float]] = {
    # Cinderella: 1 stack per 3 sec while decoy alive, max 12 stacks,
    # +28.9% per stack. In practice decoy dies in PvP, so stacks
    # accumulate slower than nominal.
    "Cinderella": (1.0 / 5.0, 12, 28.9),
    # Dorothy: Brand accumulates damage over 10s, delivers at burst end
    # up to 8900.83% ATK. Approximated as stack accumulation that scales
    # her burst payload with elapsed time at fire.
    "Dorothy":    (1.0 / 1.0, 10, 25.0),
    # Mihara: Bonding Chain: burst mirrors Ensnaring Chains stack count
    # (max 20) for 10s cross-target sustained damage.
    "Mihara: Bonding Chain": (1.0 / 2.0, 20, 8.0),
    # Mast: Romantic Maid: burst ATK +20.06%/stack of caster's ATK (10s).
    "Mast: Romantic Maid":   (1.0 / 1.5, 10, 20.06),
    # Asuka: WILLE: burst-end finisher mirrors Anti A.T. Field stacks
    # (max 30) on each tagged enemy.
    "Asuka Shikinami Langley: Wille": (1.0 / 0.5, 30, 6.0),
}


def _invuln_on_burst(name: str) -> Optional[tuple[str, float]]:
    return _INVULN_ON_BURST.get(name)


def _taunt_on_burst(name: str) -> Optional[tuple[str, float]]:
    return _TAUNT_ON_BURST.get(name)


def _apply_invuln_on_burst(
    team: list["MemberState"], scope: str, until: float, caster: "MemberState",
) -> None:
    """Apply an invuln window to ally targets based on scope."""
    if scope == "ALLIES_ALL":
        targets = [m for m in team if m.alive]
    elif scope == "ALLY_LOWEST_HP":
        living = [m for m in team if m.alive]
        if not living:
            return
        targets = [min(living, key=lambda m: m.hp / max(m.max_hp, 1.0))]
    elif scope == "ALLY_DEFENDER_LOW":
        targets = [
            m for m in team
            if m.alive and m.role == "defender"
            and (m.hp / max(m.max_hp, 1.0)) < 0.50
        ]
    elif scope == "SELF":
        targets = [caster] if caster.alive else []
    else:
        targets = []
    for m in targets:
        if until > m.invuln_until:
            m.invuln_until = until


def _apply_taunt_on_burst(
    team: list["MemberState"], scope: str, until: float, caster: "MemberState",
) -> None:
    """Set a taunt window on the caster (or other target based on scope)."""
    if scope == "SELF":
        if caster.alive and until > caster.taunt_until:
            caster.taunt_until = until


def _per_char_states(
    team: TeamEvaluation,
    opponent_avg_def: float,
    *,
    opponent_elements: Optional[list[Optional[str]]] = None,
) -> list[MemberState]:
    """Build MemberState for each Nikke on the team."""
    out: list[MemberState] = []
    for m in team.members:
        eff_atk = m.effective_atk
        if eff_atk <= 0:
            sustained = 0.0
            burst = 0.0
        else:
            weapon_factor = WEAPON_DAMAGE_PER_SECOND_FRACTION.get(
                (m.weapon_class or "").upper(), 0.10
            )
            atk_mult = _per_member_atk_damage_multiplier(
                m, defender_elements=opponent_elements
            )
            def_factor = max(
                MIN_DAMAGE_FRACTION_THROUGH_DEF,
                _def_reduction_factor(eff_atk, opponent_avg_def),
            )
            from .damage import _true_damage_dps
            role_scale = _dps_role_scale(
                m.name, m.role,
                burst_position=m.burst_position,
                weapon_class=m.weapon_class,
            )
            # Charge speed buff applies to charged weapons — reduces
            # charge time proportionally, increasing effective shot rate.
            # We model this as a weapon_factor multiplier: +40% charge
            # speed = ~1/(1-0.4) = 1.67× shots/sec on SR/RL.
            charge_speed_mult = 1.0
            if (m.weapon_class or "").lower() in ("sr", "rl"):
                # Charge speed reduces charge time. Effective shots/sec
                # scales as 1/(1-cs/100). Dampen by 0.5 because not all
                # shots are charge-attacks in PvP (some are uncharged
                # auto-fire which doesn't benefit from cs).
                cs = max(0.0, min(80.0, m.charge_speed_buff_pct))
                full_mult = 1.0 / max(0.2, 1.0 - cs / 100.0)
                charge_speed_mult = 1.0 + 0.5 * (full_mult - 1.0)
            weapon_factor_eff = weapon_factor * charge_speed_mult
            sustained = role_scale * (
                # ATK channel — DEF-mitigated, gets all the multiplicative
                # layers (Final ATK × Major × Element × Charge × Range).
                eff_atk * atk_mult * def_factor * weapon_factor_eff
                # True damage — bypasses DEF and the multiplier stack;
                # only ATK × td% × weapon hit rate × element-damage layer.
                + _true_damage_dps(m, weapon_factor_eff)
                # Pierce/shield/sustained damage-up buffs — partial credit.
                # These channels feed ATK damage, so they should be
                # def-mitigated like ATK channel.
                + eff_atk * (
                    (m.pierce_damage_buff_pct / 100.0) * 0.5
                    + (m.shield_damage_buff_pct / 100.0) * 0.3
                    + (m.sustained_damage_buff_pct / 100.0) * 0.2
                ) * weapon_factor_eff * def_factor
            )
            burst = _effective_burst_magnitude(m) * eff_atk * def_factor
        out.append(MemberState(
            name=m.name,
            max_hp=float(m.base_hp + m.flat_hp_bonus),
            hp=float(m.base_hp + m.flat_hp_bonus),
            shield=float(m.shield_value),
            sustained_dps=sustained,
            burst_payload=burst,
            eff_def=float(m.effective_def),
            role=(m.role or "").lower(),
            weapon_class=(m.weapon_class or "").lower(),
            element=(m.element or "").lower(),
            burst_position=(m.burst_position or "flex"),
            burst_cooldown_sec=float(m.burst_cooldown_sec or _canonical_burst_cd(m.name)),
            burst_target_count=int(getattr(m, "burst_aoe_target_count", 1) or 1),
            burst_ready_at=0.0,
            is_taunting=m.is_taunting,
            heal_per_second=float(m.heal_per_second),
            heal_duration=float(m.heal_duration),
            heal_emit_per_second=float(m.heal_emit_per_second),
            heal_emit_duration=float(m.heal_emit_duration),
        ))

    # Apply battle-start invulnerability windows. Per audit:
    #   Nayuta self Indomitability 9s (1x/battle)
    #   Trina  leftmost Electric SR/AR ally invuln 2s
    for m in out:
        spec = _INVULN_ON_START.get(m.name)
        if spec is None:
            continue
        duration, scope = spec
        if scope == "SELF":
            m.invuln_until = duration
        elif scope == "LEFTMOST_ELECTRIC_RIFLE_ALLY":
            # Find leftmost ally that is Electric element + AR/SR weapon
            for ally in out:
                if ally.element == "electric" and ally.weapon_class in ("ar", "sr"):
                    if duration > ally.invuln_until:
                        ally.invuln_until = duration
                    break

    # Apply battle-start Concealment / state triggers.
    for m in out:
        conceal = _CONCEALMENT_ON_START.get(m.name)
        if conceal is not None:
            m.concealment_until = conceal

    # Apply battle-start sticky taunts (Emma:TU undispellable).
    for m in out:
        taunt_dur = _TAUNT_ON_START.get(m.name)
        if taunt_dur is not None:
            m.taunt_until = taunt_dur

    return out


_FRONT_PRIORITY_WEAPONS = {"ar", "smg", "mg"}
_BACK_PRIORITY_WEAPONS = {"sg", "sr", "rl"}


# Canonical burst cooldowns for PvP-relevant characters (seconds).
# Per in-game data + Prydwen confirmation. Used as fallback when
# OwnedCharacter.burst_cooldown_seconds is NULL (most rows in our DB).
# Default 20s for unlisted chars.
_CANONICAL_BURST_COOLDOWN: dict[str, float] = {
    # B1 supports — most 20s
    "Liter": 20.0,
    "Tia": 20.0,
    "Dorothy": 20.0,
    "Volume": 20.0,
    "Rapunzel: Pure Grace": 20.0,
    "Anis: Star": 20.0,
    "Mary: Bay Goddess": 20.0,
    "Pepper": 20.0,
    "Soldier OW": 20.0,
    "Soda": 20.0,
    "Liberalio": 20.0,
    "Anis": 20.0,
    "Mary": 20.0,
    "Rapunzel": 20.0,
    "Noise": 20.0,
    "Moran": 20.0,
    "Moran (Treasure)": 20.0,
    "Bay": 20.0,
    "Bay (Treasure)": 20.0,
    "Sin": 20.0,
    "Folkwang": 20.0,
    "Mica: Snow Buddy": 20.0,
    "Naga": 20.0,
    "Rumani": 20.0,
    "Yan": 20.0,
    "Quency": 20.0,
    "Belorta": 20.0,
    "Mari Makinami Illustrious": 20.0,
    "Misato Katsuragi": 20.0,
    "D": 20.0,
    "Jackal": 20.0,
    "Trony": 20.0,
    "Pascal": 20.0,
    "Frima": 20.0,
    "Frima (Treasure)": 20.0,
    # B2 utility — most 20s, some 40s for bigger AOE
    "Crown": 20.0,
    "Helm": 20.0,
    "Helm (Treasure)": 40.0,
    "Helm: Aquamarine": 20.0,
    "Centi": 20.0,
    "Centi (Treasure)": 20.0,
    "Trina": 20.0,
    "Blanc": 40.0,
    "Anchor": 20.0,
    "Anchor: Innocent Maid": 20.0,
    "Diesel": 20.0,
    "Diesel (Treasure)": 20.0,
    "Diesel: Winter Sweets": 20.0,
    "Mast": 20.0,
    "Mast: Romantic Maid": 40.0,
    "Maiden": 20.0,
    "Tove": 20.0,
    "Tove (Treasure)": 20.0,
    "Soda: Twinkling Bunny": 40.0,
    "Miranda": 20.0,
    "Miranda (Treasure)": 20.0,
    "Privaty": 20.0,
    "Privaty (Treasure)": 20.0,
    "Privaty: Unkind Maid": 20.0,
    "Soldier EG": 20.0,
    "Soldier FA": 20.0,
    # B3 carries — most 40s
    "Scarlet": 40.0,
    "Snow White: Heavy Arms": 40.0,
    "Snow White": 40.0,
    "Modernia": 40.0,
    "Red Hood": 40.0,
    "Vesti: Tactical Upgrade": 40.0,
    "Ada Wong": 40.0,
    "Laplace": 40.0,
    "Laplace (Treasure)": 40.0,
    "Cinderella": 60.0,                  # big nuke
    "Drake": 40.0,
    "Drake (Treasure)": 40.0,
    "Maiden: Ice Rose": 40.0,
    "Nayuta": 40.0,
    "Emilia": 40.0,
    "Asuka Shikinami Langley": 40.0,
    "Asuka Shikinami Langley: Wille": 40.0,
    "Mihara": 40.0,
    "Mihara: Bonding Chain": 40.0,
    "Chisato Nishikigi": 40.0,
    "Takina Inoue": 40.0,
    "Power": 40.0,
    "Phantom": 40.0,
    "2B": 40.0,
    "A2": 40.0,
    "Rapi": 40.0,
    "Rapi: Red Hood": 40.0,
    "Scarlet: Black Shadow": 40.0,
    "Maxwell": 40.0,
    "Ein": 40.0,
    "Brid": 40.0,
    "Brid: Silent Track": 40.0,
    "Alice": 60.0,
    "Alice: Wonderland Bunny": 40.0,
    "Guillotine": 60.0,
    "Guillotine: Winter Slayer": 40.0,
    "Noir": 40.0,
    "Rosanna": 20.0,
    "Rosanna: Chic Ocean": 40.0,
    "Anis: Sparkling Summer": 40.0,
    "Bready": 40.0,
    "Biscuit": 20.0,
    "Sakura": 40.0,
    "Sakura: Bloom in Summer": 40.0,
    "Exia": 40.0,
    "Exia (Treasure)": 40.0,
    "Julia": 40.0,
    "Julia (Treasure)": 40.0,
    "Crow": 40.0,
    "Crust": 40.0,
    "Ade": 20.0,
    "Ade: Agent Bunny": 20.0,
    "Avistar": 40.0,
    "Aria": 40.0,
    "Chime": 40.0,
    "Cocoa": 40.0,
    "Eve": 40.0,
    "Folkwang (Treasure)": 20.0,
    "Grave": 40.0,
    "Marciana": 20.0,
    "Misato Katsuragi": 20.0,
    "Mori": 40.0,
    "Mast (Treasure)": 20.0,
    "Privaty (Treasure)": 20.0,
    "Quency: Escape Queen": 40.0,
    "Quiry": 40.0,
    "Raven": 40.0,
    "Rei Ayanami (Tentative Name)": 40.0,
    "Rem": 40.0,
    "Snow Crane": 40.0,
    "Soldier OW": 20.0,
    "Soline: Frost Ticket": 40.0,
    "Viper": 20.0,
    "Yulha": 20.0,
    "Volume": 20.0,
    "Eunhwa": 40.0,
    "Eunhwa: Tactical Upgrade": 40.0,
    "Emma: Tactical Upgrade": 20.0,
    "Elegg": 40.0,
    "Elegg: Boom and Shock": 40.0,
    "Diesel (Treasure)": 20.0,
    "Drake (Treasure)": 40.0,
    "Dolla": 40.0,
    "Anne: Miracle Fairy": 40.0,
    "Arcana": 40.0,
    "Arcana: Fortune Mate": 40.0,
    "Asuka Shikinami Langley": 40.0,
    "Asuka Shikinami Langley: Wille": 40.0,
    "Bay (Treasure)": 20.0,
    "Bay": 20.0,
    "Belorta": 20.0,
    "Bready": 40.0,
    "Brid: Silent Track": 40.0,
    "Brid": 40.0,
    "D: Killer Wife": 40.0,
    "Diesel: Winter Sweets": 20.0,
    "Diesel": 20.0,
    "Folkwang": 20.0,
    "Frima": 20.0,
    "Harran": 20.0,
    "Helm: Aquamarine": 20.0,
    "Jill Valentine": 40.0,
    "Julia": 40.0,
    "K": 40.0,
    "Kilo": 40.0,
    "Label": 20.0,
    "Leona": 40.0,
    "Liter": 20.0,
    "Little Mermaid (Siren)": 20.0,
    "Ludmilla": 40.0,
    "Ludmilla: Winter Owner": 40.0,
    "Makima": 40.0,
    "Mana": 40.0,
    "Mihara": 40.0,
    "Mihara: Bonding Chain": 40.0,
    "Milk": 20.0,
    "Milk (Treasure)": 20.0,
    "Milk: Blooming Bunny": 20.0,
    "Naga": 20.0,
    "Neon: Blue Ocean": 20.0,
    "Neon: Vision Eye": 40.0,
    "Nihilister": 40.0,
    "Noah": 20.0,
    "Pepper": 20.0,
    "Power": 40.0,
}


def _canonical_burst_cd(name: str) -> float:
    return _CANONICAL_BURST_COOLDOWN.get(name, 20.0)


# Damage-share characters: take a portion of damage targeted at allies.
# Tuple: (share_fraction, duration_sec_after_burst). Currently encoded
# as notes only on Anis/Bay/Centi but PvP-relevant.
_DAMAGE_SHARE_AFTER_BURST: dict[str, tuple[float, float]] = {
    "Anis":             (0.30, 10.0),   # S2: shares damage taken
    "Bay":              (0.30, 10.0),
    "Bay (Treasure)":   (0.35, 10.0),
    "Centi":            (0.25, 10.0),
    "Centi (Treasure)": (0.30, 10.0),
}


def cp_deficit_penalty(my_cp: float, opp_cp: float) -> float:
    """Combat Power deficit penalty per nikke.gg/combat-power.

    When CP deficit > 15.4%, the lower-CP team gets a stat penalty
    that grows linearly. Returns multiplier in [0.5, 1.0] applied
    to ATK/DEF/HP of the disadvantaged team.

    No penalty within 15.4% gap. At 50% gap: ~30% penalty. At 100%
    gap: 50% penalty (floor).
    """
    if my_cp <= 0 or opp_cp <= 0:
        return 1.0
    if my_cp >= opp_cp:
        return 1.0
    deficit = (opp_cp - my_cp) / opp_cp
    if deficit <= 0.154:
        return 1.0
    # Linear growth: 20% penalty at 15.4% gap, +1% per +1% gap beyond.
    extra_deficit = deficit - 0.154
    penalty = 0.20 + extra_deficit * 1.5
    return max(0.50, 1.0 - penalty)


def _weapon_target_priority(weapon_class: Optional[str]) -> str:
    """Per-weapon target priority in PvP arena.

    nikke.gg Arena Mechanics (May 2026): AR/SMG/MG focus P1 (front);
    SG/SR/RL focus P5 (back).
    """
    w = (weapon_class or "").lower()
    if w in _BACK_PRIORITY_WEAPONS:
        return "back"
    return "front"


def _apply_damage_to_team(
    team: list[MemberState],
    damage: float,
    target_priority: str = "front",
    current_t: float = 0.0,
) -> float:
    """Distribute incoming damage across living team members.

    Per nikke.gg arena mechanics (verified 2026-05-10):
    Targeting is POSITION-BASED, not lowest-HP:
      - AR/SMG/MG attackers focus P1 (team position 0) after 1 P5 shot
      - SG/SR/RL attackers focus P5 (team position 4)
      - Taunts (via skill) override targeting to the taunter for
        TARGETED skills only (not auto-fire)

    ``target_priority``:
      - "front": damage flows P1 → P2 → P3 → P4 → P5 (AR/SMG/MG default)
      - "back":  damage flows P5 → P4 → P3 → P2 → P1 (SG/SR/RL default)

    Damage absorbed by shields first, then HP. When the primary target
    dies, remaining damage cascades to the next-priority target.
    Returns total damage actually applied (bounded by team HP+shields).
    """
    if damage <= 0:
        return 0.0
    living = [m for m in team if m.alive]
    if not living:
        return 0.0

    # Build target cascade in priority order. Time-bounded taunts and
    # the legacy static is_taunting flag both apply.
    taunters = [
        m for m in living
        if m.is_taunting or m.taunt_until > current_t
    ]
    if taunters:
        cascade = taunters
    else:
        team_in_order = list(range(len(team)))
        if target_priority == "back":
            team_in_order = list(reversed(team_in_order))
        cascade = [team[i] for i in team_in_order if team[i].alive]

    # Damage cascades down the priority list — focus-fire on the first
    # alive non-invulnerable target, overflow to the next.
    # Invulnerable AND concealed targets are SKIPPED (damage doesn't
    # hit them, but neither does it consume incoming damage).
    remaining = damage
    applied = 0.0
    for tgt in cascade:
        if remaining <= 0:
            break
        if not tgt.alive:
            continue
        if tgt.invuln_until > current_t:
            continue  # invulnerable — damage cascades past
        if tgt.concealment_until > current_t:
            continue  # concealed (single-target-immunity) — cascade past
        if tgt.shield > 0:
            absorb = min(tgt.shield, remaining)
            tgt.shield -= absorb
            remaining -= absorb
            applied += absorb
        if remaining > 0:
            absorb_hp = min(tgt.hp, remaining)
            tgt.hp -= absorb_hp
            remaining -= absorb_hp
            tgt.damage_taken += absorb_hp
            applied += absorb_hp
            if tgt.hp <= 0:
                # Indomit-on-lethal: chars like Makima get one save.
                indomit_spec = _INDOMIT_ON_LETHAL.get(tgt.name)
                if (indomit_spec is not None
                    and getattr(tgt, "_indomit_used", 0) < indomit_spec[0]):
                    tgt.hp = max(tgt.max_hp * 0.01, 1.0)  # snap to 1% HP
                    tgt.invuln_until = max(
                        tgt.invuln_until,
                        current_t + indomit_spec[1],
                    )
                    tgt._indomit_used = getattr(tgt, "_indomit_used", 0) + 1
                else:
                    tgt.alive = False
                    tgt.hp = 0.0
    return applied


def _apply_heal_to_team(team: list[MemberState], heal_amount: float) -> None:
    """Heal lowest-HP living ally up to their max HP."""
    if heal_amount <= 0:
        return
    living = [m for m in team if m.alive]
    if not living:
        return
    target = min(living, key=lambda m: m.hp / max(m.max_hp, 1))
    target.hp = min(target.max_hp, target.hp + heal_amount)


def simulate_per_character(
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
    seed: Optional[int] = None,
) -> TimeSteppedResult:
    """Per-character simulation with focus-fire damage distribution.

    When ``seed`` is provided, random effects (stun target selection,
    etc.) use a seeded random.Random for reproducibility across runs.
    When None, deterministic hash-based ordering is used (single-run
    consistency).

    Improvements over team-aggregate ``simulate``:
    1. Track each Nikke's HP/shield separately.
    2. Damage focuses on lowest-HP living defender (taunt-overridden).
    3. When a defender dies, attacker team's DPS doesn't change but
       living target count shrinks → remaining defenders die faster.
    4. When an attacker dies, that Nikke's sustained_dps drops out
       of the team total → defender survives longer.
    5. Heals target the lowest-HP-fraction living ally each tick.
    6. Match ends when all of one team dies (not just total HP=0).

    The model still doesn't capture per-skill cooldowns or burst-
    rotation timing within the chain — those are deferred. But the
    death-event accounting alone unlocks differentiation between
    teams that the team-aggregate model collapses together.
    """
    if first_burst_sec is None:
        first_burst_sec = derive_first_burst_sec(attacker, attacker_cubes)
    if defender_first_burst_sec is None:
        defender_first_burst_sec = derive_first_burst_sec(defender, defender_cubes)

    # Opponent avg DEF (used by each attacker's def_factor calc).
    a_avg_def = sum(m.effective_def for m in attacker.members) / max(len(attacker.members), 1)
    d_avg_def = sum(m.effective_def for m in defender.members) / max(len(defender.members), 1)

    a_elements = [m.element for m in attacker.members]
    d_elements = [m.element for m in defender.members]
    a_team = _per_char_states(
        attacker, opponent_avg_def=d_avg_def, opponent_elements=d_elements
    )
    d_team = _per_char_states(
        defender, opponent_avg_def=a_avg_def, opponent_elements=a_elements
    )

    # Burst-chain timeline: schedule WHEN each chain rotation BEGINS,
    # but membership of each chain is decided at fire-time based on
    # cooldowns + leftmost-eligible. This matches NIKKE PvP behavior:
    # 3 Nikkes per chain (one B1, one B2, one B3), each putting their
    # burst on per-character cooldown, so subsequent chains may pull
    # different members.
    a_chain_times = []
    t_b = first_burst_sec
    while t_b < match_length_sec:
        a_chain_times.append(t_b)
        t_b += cycle_period_sec
    d_chain_times = []
    t_b = defender_first_burst_sec
    while t_b < match_length_sec:
        d_chain_times.append(t_b)
        t_b += cycle_period_sec
    # Chain-firing detection: track scheduled chain times as sorted
    # lists; each tick, pop times <= current_t. Supports sub-tick dt.
    a_pending_chain_times: list[float] = sorted(a_chain_times)
    d_pending_chain_times: list[float] = sorted(d_chain_times)
    a_chain_set = set(int(t) for t in a_chain_times)  # legacy compat
    d_chain_set = set(int(t) for t in d_chain_times)

    # Track which chain rotations active heals were triggered by, so
    # heal-window detection persists for `heal_duration` seconds after
    # each chain begins.
    a_active_chain_starts: list[float] = []
    d_active_chain_starts: list[float] = []

    # Delayed-burst queues — (deliver_at, caster, payload, target_priority).
    # When a Nikke fires a burst with delivery delay > 0, we schedule the
    # damage to land later. If the caster dies in the interval, the entry
    # is skipped.
    a_pending_bursts: list[tuple[float, MemberState, float, str]] = []
    d_pending_bursts: list[tuple[float, MemberState, float, str]] = []

    rng: Optional[random.Random] = (
        random.Random(seed) if seed is not None else None
    )

    # Periodic taunt schedules — next_fire_at per (team, member).
    # When sim time crosses a member's next_fire_at, refresh their
    # taunt_until and bump next_fire_at by their refresh_sec.
    a_next_periodic_taunt: dict[str, float] = {
        m.name: _TAUNT_PERIODIC[m.name][0]
        for m in a_team if m.name in _TAUNT_PERIODIC
    }
    d_next_periodic_taunt: dict[str, float] = {
        m.name: _TAUNT_PERIODIC[m.name][0]
        for m in d_team if m.name in _TAUNT_PERIODIC
    }
    # Makima's lethal-damage indomit usage counter.
    a_indomit_used: dict[str, int] = {m.name: 0 for m in a_team}
    d_indomit_used: dict[str, int] = {m.name: 0 for m in d_team}

    a_total_damage = 0.0
    d_total_damage = 0.0
    a_hp_timeline: list[float] = []
    d_hp_timeline: list[float] = []
    end_reason = "timeout"

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

        # Periodic taunts — refresh based on each Nikke's interval.
        for m in a_team:
            if not m.alive:
                continue
            spec = _TAUNT_PERIODIC.get(m.name)
            if spec is None:
                continue
            refresh_sec, duration_sec = spec
            next_fire = a_next_periodic_taunt.get(m.name, 0.0)
            if t >= next_fire:
                m.taunt_until = t + duration_sec
                a_next_periodic_taunt[m.name] = t + refresh_sec
        for m in d_team:
            if not m.alive:
                continue
            spec = _TAUNT_PERIODIC.get(m.name)
            if spec is None:
                continue
            refresh_sec, duration_sec = spec
            next_fire = d_next_periodic_taunt.get(m.name, 0.0)
            if t >= next_fire:
                m.taunt_until = t + duration_sec
                d_next_periodic_taunt[m.name] = t + refresh_sec

        # Phase 6 — buff decay outside burst windows. Peak DPS only
        # while in the 10s window after each chain; ~55% retention
        # otherwise. Without this, matches at LV-400 cap end in 5s
        # because we're using "everything always full-buffed" math.
        a_dps_factor = _dps_decay_factor(t, a_active_chain_starts)
        d_dps_factor = _dps_decay_factor(t, d_active_chain_starts)
        # Phase 7 — state-machine ramp factor applied per Nikke.
        # SW:HA's Auto-Fire / Crown's Relax / Modernia's stacks
        # ramp over the burst window so peak DPS isn't full duration.
        # Track per-member contribution so attribution shares sum to 1.0.
        # Tag each contribution with target-priority based on weapon
        # class. Per nikke.gg arena mechanics:
        #   - AR/SMG/MG → front (P1 priority)
        #   - SG/SR/RL → back (P5 priority)
        # Stunned members contribute 0 sustained DPS during their stun
        # window — they can't shoot. We multiply by an alive-and-not-stunned
        # gate.
        def _active_factor(m):
            return 0.0 if m.stunned_until > t else 1.0
        a_member_dps = [
            (m, m.sustained_dps * a_dps_factor
             * _state_machine_factor(m.name, t, a_active_chain_starts)
             * _sustained_stack_multiplier(m.name, t, a_active_chain_starts)
             * _active_factor(m),
             _weapon_target_priority(getattr(m, "weapon_class", None)))
            for m in a_living
        ]
        d_member_dps = [
            (m, m.sustained_dps * d_dps_factor
             * _state_machine_factor(m.name, t, d_active_chain_starts)
             * _sustained_stack_multiplier(m.name, t, d_active_chain_starts)
             * _active_factor(m),
             _weapon_target_priority(getattr(m, "weapon_class", None)))
            for m in d_living
        ]
        a_sus = sum(d for _, d, _ in a_member_dps)
        d_sus = sum(d for _, d, _ in d_member_dps)

        # Split sustained by target priority.
        a_sus_front = sum(d for _, d, p in a_member_dps if p == "front")
        a_sus_back = sum(d for _, d, p in a_member_dps if p == "back")
        d_sus_front = sum(d for _, d, p in d_member_dps if p == "front")
        d_sus_back = sum(d for _, d, p in d_member_dps if p == "back")

        # Burst chain firing — select 3 leftmost-eligible (B1→B2→B3),
        # put each on cooldown. We track each chain member's payload
        # independently so damage attribution credits the casters
        # rather than smearing across the team via sustained-DPS share.
        a_chain_bursts: list[tuple[MemberState, float]] = []  # (caster, payload)
        d_chain_bursts: list[tuple[MemberState, float]] = []
        # When both teams burst on the same int(t) tick, the team with
        # earlier scheduled first_burst_sec lands first — their burst
        # damage applies to the slower team before the slower team's
        # chain has fired. This matches in-game behavior where a 0.2s
        # gap in chain-fill time can decide the match.
        # Fire chains whose scheduled time has been reached (sub-tick aware).
        a_fires_here = bool(a_pending_chain_times) and a_pending_chain_times[0] <= t + dt * 0.5
        d_fires_here = bool(d_pending_chain_times) and d_pending_chain_times[0] <= t + dt * 0.5
        if a_fires_here:
            a_pending_chain_times.pop(0)
        if d_fires_here:
            d_pending_chain_times.pop(0)
        a_first = first_burst_sec < defender_first_burst_sec

        def _conditional_satisfied(m: MemberState) -> bool:
            gate = _BURST_CONDITION_GATES.get(m.name)
            return gate is None or gate(m, t)

        def _payload_with_bonuses(m: MemberState) -> float:
            """Apply conditional bonus multiplier + stack-accumulator scaling
            on top of the base burst payload."""
            payload = m.burst_payload
            # Stack accumulation (Cinderella, Modernia, etc.)
            stack_spec = _STACK_ACCUMULATING_BURST.get(m.name)
            if stack_spec is not None:
                rate, max_stacks, per_stack_pct = stack_spec
                stacks = min(int(t * rate), max_stacks)
                payload *= 1.0 + (stacks * per_stack_pct / 100.0)
            # Conditional bonus (Rosanna +43% if Concealment)
            bonus = _CONDITIONAL_BURST_BONUS_MULT.get(m.name)
            if bonus is not None and _conditional_satisfied(m):
                payload *= bonus
            return payload

        def _fire_a():
            chain = _select_burst_chain(a_team, t)
            if chain:
                for m in chain:
                    sm = _state_machine_factor(m.name, t, a_active_chain_starts + [t])
                    a_chain_bursts.append((m, _payload_with_bonuses(m) * sm))
                    m.burst_ready_at = t + m.burst_cooldown_sec
                    gate_ok = _conditional_satisfied(m)
                    stun = _stun_on_burst(m.name)
                    if stun is not None and gate_ok:
                        _apply_stun_to_random(d_team, stun[0], t + stun[1], rng)
                    inv = _invuln_on_burst(m.name)
                    if inv is not None:
                        _apply_invuln_on_burst(a_team, inv[0], t + inv[1], m)
                    tnt = _taunt_on_burst(m.name)
                    if tnt is not None:
                        _apply_taunt_on_burst(a_team, tnt[0], t + tnt[1], m)
                a_active_chain_starts.append(t)

        def _fire_d():
            chain = _select_burst_chain(d_team, t)
            if chain:
                for m in chain:
                    sm = _state_machine_factor(m.name, t, d_active_chain_starts + [t])
                    d_chain_bursts.append((m, _payload_with_bonuses(m) * sm))
                    m.burst_ready_at = t + m.burst_cooldown_sec
                    gate_ok = _conditional_satisfied(m)
                    stun = _stun_on_burst(m.name)
                    if stun is not None and gate_ok:
                        _apply_stun_to_random(a_team, stun[0], t + stun[1])
                    inv = _invuln_on_burst(m.name)
                    if inv is not None:
                        _apply_invuln_on_burst(d_team, inv[0], t + inv[1], m)
                    tnt = _taunt_on_burst(m.name)
                    if tnt is not None:
                        _apply_taunt_on_burst(d_team, tnt[0], t + tnt[1], m)
                d_active_chain_starts.append(t)

        if a_fires_here and d_fires_here:
            if a_first:
                _fire_a(); _fire_d()
            else:
                _fire_d(); _fire_a()
        elif a_fires_here:
            _fire_a()
        elif d_fires_here:
            _fire_d()

        # Sustained damage — split by attacker weapon priority. AR/SMG/MG
        # damage focuses defender P1 (front); SG/SR/RL focuses P5 (back).
        applied_sustained_to_d = (
            _apply_damage_to_team(d_team, a_sus_front * dt, "front", t)
            + _apply_damage_to_team(d_team, a_sus_back * dt, "back", t)
        )
        applied_sustained_to_a = (
            _apply_damage_to_team(a_team, d_sus_front * dt, "front", t)
            + _apply_damage_to_team(a_team, d_sus_back * dt, "back", t)
        )

        # Burst payloads — apply in temporal order (earlier-fired team
        # first) so the slower team's chain has to hit a possibly-dying
        # defender team.
        applied_burst_to_d = 0.0
        applied_burst_to_a = 0.0

        def _apply_burst_payload(target_team, caster, payload, pri, current_t):
            """Apply caster's burst — per-target if AOE, single-cascade otherwise."""
            target_count = caster.burst_target_count
            if target_count <= 1:
                return _apply_damage_to_team(target_team, payload, pri, current_t)
            # AOE: apply per-target magnitude to each of N targets.
            # Use the cascade priority to pick the N "victims"; each
            # gets the FULL per-target payload independently (matches
            # nikke.gg per-target damage semantics).
            living = [m for m in target_team if m.alive]
            if not living:
                return 0.0
            n_targets = min(target_count, len(living))
            # Pick N targets via cascade priority
            team_in_order = list(range(len(target_team)))
            if pri == "back":
                team_in_order = list(reversed(team_in_order))
            picks: list[MemberState] = []
            for i in team_in_order:
                m = target_team[i]
                if m.alive and m.invuln_until <= current_t and m.concealment_until <= current_t:
                    picks.append(m)
                    if len(picks) == n_targets:
                        break
            total = 0.0
            for tgt in picks:
                # Apply payload to just this one target (no cascade).
                # Use one-member team for cascade semantics.
                total += _apply_damage_to_team([tgt], payload, pri, current_t)
            return total

        def _apply_a_bursts():
            nonlocal applied_burst_to_d
            for caster, payload in a_chain_bursts:
                if not caster.alive:
                    continue
                if caster.stunned_until > t:
                    continue
                pri = _weapon_target_priority(caster.weapon_class)
                delay = _burst_delivery_delay(caster.name)
                if delay > 0:
                    a_pending_bursts.append((t + delay, caster, payload, pri))
                else:
                    landed = _apply_burst_payload(d_team, caster, payload, pri, t)
                    applied_burst_to_d += landed
                    caster.damage_dealt += landed

        def _apply_d_bursts():
            nonlocal applied_burst_to_a
            for caster, payload in d_chain_bursts:
                if not caster.alive:
                    continue
                if caster.stunned_until > t:
                    continue
                pri = _weapon_target_priority(caster.weapon_class)
                delay = _burst_delivery_delay(caster.name)
                if delay > 0:
                    d_pending_bursts.append((t + delay, caster, payload, pri))
                else:
                    landed = _apply_burst_payload(a_team, caster, payload, pri, t)
                    applied_burst_to_a += landed
                    caster.damage_dealt += landed

        if a_chain_bursts and d_chain_bursts:
            if a_first:
                _apply_a_bursts(); _apply_d_bursts()
            else:
                _apply_d_bursts(); _apply_a_bursts()
        else:
            _apply_a_bursts(); _apply_d_bursts()

        # Deliver any pending (delayed) bursts whose time has come.
        # Cancel if caster died in the delay window — matches Liberalio's
        # in-game weakness where her 1.1s delay can be eaten by opponent
        # bursts/sustained damage.
        new_a_pending = []
        for deliver_at, caster, payload, pri in a_pending_bursts:
            if t < deliver_at:
                new_a_pending.append((deliver_at, caster, payload, pri))
                continue
            if not caster.alive:
                continue  # cancelled — caster died in delay window
            if caster.stunned_until > deliver_at:
                continue  # cancelled — caster stunned at delivery time
            landed = _apply_burst_payload(d_team, caster, payload, pri, t)
            applied_burst_to_d += landed
            caster.damage_dealt += landed
        a_pending_bursts = new_a_pending

        new_d_pending = []
        for deliver_at, caster, payload, pri in d_pending_bursts:
            if t < deliver_at:
                new_d_pending.append((deliver_at, caster, payload, pri))
                continue
            if not caster.alive:
                continue
            if caster.stunned_until > deliver_at:
                continue
            landed = _apply_burst_payload(a_team, caster, payload, pri, t)
            applied_burst_to_a += landed
            caster.damage_dealt += landed
        d_pending_bursts = new_d_pending

        a_total_damage += applied_sustained_to_d + applied_burst_to_d
        d_total_damage += applied_sustained_to_a + applied_burst_to_a

        # Sustained-DPS attribution (proportional to each Nikke's
        # contribution to the team's effective DPS this tick).
        if a_sus > 0:
            for m, d, _ in a_member_dps:
                m.damage_dealt += applied_sustained_to_d * (d / a_sus)
        if d_sus > 0:
            for m, d, _ in d_member_dps:
                m.damage_dealt += applied_sustained_to_a * (d / d_sus)

        # Healing — applies for ``heal_duration`` seconds following
        # each chain. Per-emitter attribution: each healer uses their
        # OWN heal_emit_per_second + heal_emit_duration window so two
        # healers on one team each contribute (vs. the prior "max-only"
        # heuristic that under-credited multi-healer comps).
        for healer in a_living:
            if healer.heal_emit_per_second <= 0 or healer.heal_emit_duration <= 0:
                continue
            if any(bt <= t < bt + healer.heal_emit_duration for bt in a_active_chain_starts):
                healed = healer.heal_emit_per_second * dt
                _apply_heal_to_team(a_team, healed)
                healer.healing_dealt += healed
        for healer in d_living:
            if healer.heal_emit_per_second <= 0 or healer.heal_emit_duration <= 0:
                continue
            if any(bt <= t < bt + healer.heal_emit_duration for bt in d_active_chain_starts):
                healed = healer.heal_emit_per_second * dt
                _apply_heal_to_team(d_team, healed)
                healer.healing_dealt += healed
        a_hp_timeline.append(sum(m.hp for m in a_team))
        d_hp_timeline.append(sum(m.hp for m in d_team))

        t += dt

    def _per_char_dict(team: list[MemberState]) -> dict[str, dict[str, float]]:
        return {
            m.name: {
                "damage_dealt": m.damage_dealt,
                "damage_taken": m.damage_taken,
                "healing_dealt": m.healing_dealt,
                "hp": m.hp,
                "max_hp": m.max_hp,
                "hp_pct": (m.hp / m.max_hp * 100.0) if m.max_hp > 0 else 0.0,
                "alive": float(m.alive),
            }
            for m in team
        }

    return TimeSteppedResult(
        attacker_wins=(end_reason == "defender_cleared"),
        match_ended_at_sec=t,
        end_reason=end_reason,
        attacker_total_damage=a_total_damage,
        defender_total_damage=d_total_damage,
        attacker_hp_remaining=sum(m.hp for m in a_team),
        defender_hp_remaining=sum(m.hp for m in d_team),
        attacker_hp_timeline=a_hp_timeline,
        defender_hp_timeline=d_hp_timeline,
        attacker_per_char=_per_char_dict(a_team),
        defender_per_char=_per_char_dict(d_team),
        notes=[
            f"a_first_burst={first_burst_sec:.1f}s d_first_burst={defender_first_burst_sec:.1f}s",
            f"a_living_at_end={sum(1 for m in a_team if m.alive)}/{len(a_team)}",
            f"d_living_at_end={sum(1 for m in d_team if m.alive)}/{len(d_team)}",
        ],
    )


def derive_first_burst_sec(
    team: TeamEvaluation,
    member_cubes: Optional[list[tuple[Optional[str], Optional[int]]]] = None,
) -> float:
    """Compute when the team's first burst chain completes.

    Uses ``compute_burst_chain_offsets`` from timeline.py with:
    - weapon classes (per-class burst gen rate)
    - member names (skill-based gauge bonuses for ~20 chars)
    - cube info (Quantum LV15 = +1.5%/s gauge per Nikke)
    - per-member charge_speed_buff_pct (boosts SR/RL gauge gen
      proportionally — Phase 5 of 2026-05-09 sim improvements)

    Returns the time of the FIRST burst (offsets[0]). Subsequent
    bursts in the chain land 1s apart; the Full Burst window opens
    at offsets[2].
    """
    weapons = [m.weapon_class for m in team.members]
    names = [m.name for m in team.members]
    charge_speeds = [m.charge_speed_buff_pct for m in team.members]
    offsets = compute_burst_chain_offsets(
        weapons,
        member_names=names,
        member_cubes=member_cubes,
        member_charge_speed_pct=charge_speeds,
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

    # Per-character end-state, indexed by Nikke name. Populated by
    # ``simulate_per_character`` so callers can read out individual
    # damage_dealt / damage_taken / healing_dealt / hp_pct without
    # re-running the sim. Empty dict for callers of older entry points.
    attacker_per_char: dict[str, dict[str, float]] = field(default_factory=dict)
    defender_per_char: dict[str, dict[str, float]] = field(default_factory=dict)

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


def _team_metrics(
    team: TeamEvaluation,
    opponent_avg_def: float,
    *,
    opponent_elements: Optional[list[Optional[str]]] = None,
) -> dict:
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
        atk_mult = _per_member_atk_damage_multiplier(
            m, defender_elements=opponent_elements
        )
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
    a_elements = [m.element for m in attacker.members]
    d_elements = [m.element for m in defender.members]
    a = _team_metrics(
        attacker, opponent_avg_def=d_avg_def, opponent_elements=d_elements
    )
    d = _team_metrics(
        defender, opponent_avg_def=a_avg_def, opponent_elements=a_elements
    )

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
