"""Damage-formula resolution — Phase 3 simulator slice 3.

Pairs two TeamEvaluation snapshots (Team A, Team B) and computes a
comparable "would A overcome B in PvP?" number using the published
NIKKE damage formula. The current pipeline (slices #88, #96, #97):

    1. Per-Nikke base stats from ``OwnedCharacter.total_atk/hp/def``
       (auto-loaded by ``evaluate_by_names``; defaults if unowned).
    2. Per-WeaponClass damage-per-second fraction (sustained-DPS
       weapons MG/SMG/AR > slow-but-big SR/RL):

           weapon_factor = WEAPON_DAMAGE_PER_SECOND_FRACTION[wc]
           atk_dps      += eff_atk × atk_mult × def_factor × weapon_factor
           true_dps     += eff_atk × true_dmg_pct × weapon_factor
           other_dps    += eff_atk × other_mult × weapon_factor

    3. Burst contribution as TIME-AVERAGED DPS (slice #96 — replaces
       the older "head-start subtract burst payload from HP" model):

           burst_dps_eq = burst_total / cycle_period_sec
           team_dps     = atk_dps + true_dps + other_dps + burst_dps_eq

    4. Clear time scales linearly with HP / DPS:

           seconds_to_clear = first_burst_sec + defender_hp / team_dps

The ``atk_mult`` factor combines ``attack_damage_buff_pct`` with crit
expectation, Full-Burst-window average, and element-advantage average.
``atk_buff_pct`` is NOT folded in here — it's already baked into
``effective_atk`` upstream (slice #88 fixed a double-count).

Damage-type bonuses that sit alongside ATK:
  * true_damage_buff_pct      → bypasses defender DEF entirely
  * pierce_damage_buff_pct    → multi-target through cover (proxy)
  * shield_damage_buff_pct    → bonus only on shielded targets
  * core_damage_buff_pct      → boss-leaning, near-zero PvP relevance
  * sustained_damage_buff_pct → DOT amp; folded into per-second budget

This is **not** a full event-loop simulator. It produces a **deterministic
comparison number** so the optimizer can prefer "Team A more likely to
overcome Team B's defense" without an actual match playback. The full
event-loop simulator (state machines, RNG, target selection, HP depletion)
remains the long-term Phase 3 capability.

What this slice IGNORES:
  * Hit-by-hit RNG (whiffs, crit variance — uses expected values)
  * State machines (Crown's Relax, SW:HA's Lock-On, etc. — assumed active)
  * Death events (assumes 5 vs 5 throughout)
  * Timeline decay (treats buffs as steady-state for the 5-min window)
  * Burst-skill cooldowns (every cycle assumed to fire its full payload)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .evaluator import NikkeSnapshot, TeamEvaluation, evaluate_by_names


# ---------------------------------------------------------------------------
# Constants — published NIKKE damage-formula coefficients
# ---------------------------------------------------------------------------


# Full Burst window contributes a flat +50% damage multiplier for 10 sec
# inside a typical 60-sec rotation. Across a 5-min match: ~25% of time
# in Full Burst → effective average multiplier of 1 + 0.5 × 0.25 = 1.125.
# We use that as a steady-state proxy.
FULL_BURST_AVERAGE_MULTIPLIER = 1.125

# Element advantage: +10% damage on weakness. NIKKE element wheel is
# Fire ↦ Wind ↦ Iron ↦ Electric ↦ Water ↦ Fire (each beats next).
# When the actual defender composition is known we compute a
# per-attacker fraction-favored multiplier; the constant below is kept
# as a fallback for callers that don't pass defender elements.
ELEMENT_ADVANTAGE_AVERAGE = 1.05
ELEMENT_ADVANTAGE_BONUS = 0.10  # +10% damage when attacking a weak element

# Cyclic advantage table — keyed/valued by NikkeSnapshot.element strings
# (lowercased Element enum values: "fire", "water", "electric", "iron", "wind").
ELEMENT_BEATS: dict[str, str] = {
    "fire": "wind",
    "wind": "iron",
    "iron": "electric",
    "electric": "water",
    "water": "fire",
}


def element_advantage_factor(
    attacker_element: Optional[str],
    defender_elements: list[Optional[str]],
) -> float:
    """Multiplier in [1.0, 1.10] given an attacker's element vs a defender team.

    Returns ``1.0 + 0.10 × (favored_count / total)`` — i.e. proportional
    bonus based on how many defenders the attacker has element advantage
    over. With unknown attacker element or empty defender list, returns
    the steady-state proxy ``ELEMENT_ADVANTAGE_AVERAGE`` so existing
    callers behave the same as before.
    """
    if not attacker_element or not defender_elements:
        return ELEMENT_ADVANTAGE_AVERAGE
    weak = ELEMENT_BEATS.get(attacker_element.lower())
    if not weak:
        return ELEMENT_ADVANTAGE_AVERAGE
    known = [e for e in defender_elements if e]
    if not known:
        return ELEMENT_ADVANTAGE_AVERAGE
    favored = sum(1 for e in known if e.lower() == weak)
    return 1.0 + ELEMENT_ADVANTAGE_BONUS * (favored / len(known))

# Crit baseline: PvP teams typically run ~25% crit rate, ~150% crit
# damage multiplier (1.5×). Expected damage multiplier: 1 + 0.25 × 0.5 = 1.125.
DEFAULT_CRIT_RATE_PCT = 25.0
DEFAULT_CRIT_DAMAGE_PCT = 50.0  # 50% bonus → 1.5× total

# DEF reduction in NIKKE follows a published formula:
#   damage_taken = max(0.05, 1 - defender_DEF / (defender_DEF + attacker_ATK))
# Floor of 5% damage gets through even at extreme DEF advantage.
MIN_DAMAGE_FRACTION_THROUGH_DEF = 0.05

# Match length cap (defender wins on timeout in PvP)
MATCH_LENGTH_SEC = 300.0

# Slice #88 — per-shot ATK fraction. Real NIKKE weapons deal far less than
# 100% of ATK per shot: AR ≈ 13.5% × 5 shots/sec, SMG ≈ 7% × 10 shots/sec,
# RL ≈ 1500% × 0.4 shots/sec, etc. The team-wide average lands around 10%
# of ATK × ~4 shots/sec/member when amortized.
#
# Slice #97 split the global into a per-WeaponClass table — the relative
# differentiation between classes (AR baseline vs SR/RL slower-but-bigger
# shots) shows up in the win-margin numbers, helping the optimizer prefer
# weapon mixes that suit the matchup. Values are tuned around the
# previous global default of 0.10 so absolute clear times don't shift
# dramatically; the variation captures the per-class personality.
DAMAGE_PER_SHOT_FRACTION = 0.10  # legacy fallback for None / unknown weapon class

WEAPON_DAMAGE_PER_SECOND_FRACTION: dict[str, float] = {
    # Per-shot ATK fraction × fire rate per sec, calibrated against
    # nikke.gg published damage-formula numbers and West Games DPS
    # calculator (May 2026). Prior values (0.07-0.13) were ~10-15× too
    # low and produced a systematic 2-4× under-prediction of total
    # match damage — root cause of the validation undershoot.
    "AR":  1.62,   # ≈ 13.5% per shot × 12 shots/sec
    "SMG": 1.95,   # ≈ 6.5% per shot × 30 shots/sec
    "MG":  1.40,   # ≈ 3.5% per shot × 40 shots/sec
    # SG: in arena all 10 pellets always land (Hit Rate stat is
    # worthless in PvP — confirmed by nikke.gg arena-mechanics).
    "SG":  1.50,   # ≈ 2.46% × 10 pellets × ~0.6 shots/sec, arena-buffed
    # SR/RL pay this in slow tempo but charge damage compensates,
    # applied separately in _per_member_atk_damage_multiplier.
    "SR":  1.28,   # ≈ 256% per shot × 0.5 shots/sec (pre-charge)
    "RL":  0.64,   # ≈ 256% per shot × 0.25 shots/sec (pre-charge)
}

# Charge damage bonus: SR/RL hit harder ONLY on fully-charged shots.
# Charge time is ~1s for SR, ~1.5s for RL (with no charge-speed buffs).
# In PvP arena, the canonical SR comp delivers ~70% of shots fully
# charged during burst window (uncharged auto-fire fills the rest).
# Realistic uptime-weighted multiplier:
#   SR full charge mult = 2.5× (1 + 1.5)
#   Average across charged + uncharged = ~1.5× (was 2.5× — over-counted
#   uncharged shots that get NO bonus per nikke.gg/damage-formula).
# Updated 2026-05-10 after beta-29 calibration showed sustained-DPS was
# 2-3× too high.
CHARGE_DAMAGE_DEFAULT_MULTIPLIER = 2.5  # full-charge value (legacy export)
CHARGE_DAMAGE_AVG_MULT = 1.8  # uptime-weighted realistic average (beta-29 fit, 4/5)
CHARGED_WEAPON_CLASSES = frozenset({"SR", "RL"})

# Effective Range +30% — applies ONLY to weapons in optimal range, and
# ONLY to normal-attack damage (not bursts). In PvP arena all targets
# sit at mid-range, so only SR is in optimal range; RL/SG/MG/AR/SMG
# do NOT benefit. Citations: nikke.gg/arena-mechanics, Prydwen PvP
# guide. Pre-2026-05-10 sim applied this 1.30× to ALL weapons → 30%
# global over-prediction on arena DPS.
EFFECTIVE_RANGE_BONUS = 1.30
RANGE_BONUS_WEAPONS = frozenset({"SR"})

# Burst rotation period (seconds between Full-Burst windows after the
# first chain). Used to convert the one-shot burst payload into a
# multi-cycle total over the 5-minute match. Approximately:
#   * 10s pre-burst (gauge fill, mostly skipped after cycle 1)
#   * 10s Full Burst window
#   * ~20s recovery / next gauge fill
# Total ≈ 40s per subsequent cycle.
DEFAULT_CYCLE_PERIOD_SEC = 40.0

# Default first-burst time when neither weapons nor an explicit
# ``first_burst_sec`` is supplied. Mirrors the legacy timeline default
# (Crown comp lands here).
DEFAULT_FIRST_BURST_SEC = 10.0


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class MemberContribution:
    """Per-Nikke breakdown of one side's contribution to ``DamageResolution``.

    The validation page uses this to compare the sim's per-Nikke estimates
    against actual captured values (Champion duel screenshots give us
    per-Nikke damage_dealt / damage_taken / healing / hp_remaining).
    Aggregating these across members reproduces the team-level numbers on
    ``DamageResolution`` (within rounding).
    """

    name: str

    # Attacker-side contributions (what this Nikke deals to the defender)
    atk_damage_per_sec: float = 0.0         # ATK-channel DPS
    true_damage_per_sec: float = 0.0        # true-damage DPS (bypasses DEF)
    other_damage_per_sec: float = 0.0       # pierce + shield + sustained
    burst_payload_per_cycle: float = 0.0    # one-shot burst payload per cycle
    estimated_damage_dealt: float = 0.0     # total over the match

    # Defender-side contributions (what this Nikke is/can absorb)
    base_hp: float = 0.0
    flat_hp_bonus: float = 0.0
    shield_value: float = 0.0
    heal_per_second: float = 0.0
    heal_duration: float = 0.0
    estimated_heal_performed: float = 0.0   # heal_per_second × heal_active_seconds
    estimated_damage_taken: float = 0.0     # share of team incoming, minus shield/heal
    estimated_hp_remaining_pct: float = 100.0  # 0-100 after damage_taken applied

    # Identity (for joining against captured names)
    weapon_class: Optional[str] = None
    element: Optional[str] = None


@dataclass
class DamageResolution:
    """Result of the Team A vs Team B resolution."""

    # Per-team aggregates (5-Nikke totals)
    attacker_team_dps: float = 0.0  # attacker damage output per second
    attacker_burst_payload: float = 0.0  # attacker one-shot burst total
    defender_effective_hp: float = 0.0  # defender pool to deplete (HP + post-burst shield + heals over match)

    # Defender sustainability breakdown — added 2026-05-09 in support
    # of heal/shield modeling. Validation against tournament match
    # data showed the prior model under-predicted opponent EHP by 3×
    # because heal-per-second was tracked but never applied to the
    # damage-budget calculation. Shield was only counted at one-time
    # post-burst-chain value; multi-cycle re-application is deferred.
    defender_base_hp: float = 0.0       # raw HP only (no shield, no heal)
    defender_shield_total: float = 0.0  # shields applied (post-burst-chain)
    defender_heal_total: float = 0.0    # cumulative healing over match duration

    # Composite damage breakdown
    attacker_atk_damage_per_sec: float = 0.0  # base ATK channel
    attacker_true_damage_per_sec: float = 0.0  # bypasses DEF
    attacker_other_damage_per_sec: float = 0.0  # pierce + shield + sustained

    # Outcome heuristic
    seconds_to_clear_defender: float = 0.0  # ehp / dps
    attacker_wins_within_5min: bool = False
    win_margin: float = 0.0  # (match_length - seconds_to_clear); negative = loss

    # Diagnostics
    notes: list[str] = field(default_factory=list)

    # Per-member breakdown (slice — populated 2026-05-19 so the
    # /simulator/validation page can show sim per-Nikke estimates next
    # to captured per-Nikke ground truth for Champion duels)
    attacker_per_member: list[MemberContribution] = field(default_factory=list)
    defender_per_member: list[MemberContribution] = field(default_factory=list)
    # Number of burst rotations modelled in this match — used to convert
    # ``burst_payload_per_cycle`` × N to the over-match estimate.
    bursts_in_match: int = 1

    def to_dict(self) -> dict:
        return {
            "attacker_team_dps": self.attacker_team_dps,
            "attacker_burst_payload": self.attacker_burst_payload,
            "defender_effective_hp": self.defender_effective_hp,
            "defender_base_hp": self.defender_base_hp,
            "defender_shield_total": self.defender_shield_total,
            "defender_heal_total": self.defender_heal_total,
            "attacker_atk_damage_per_sec": self.attacker_atk_damage_per_sec,
            "attacker_true_damage_per_sec": self.attacker_true_damage_per_sec,
            "attacker_other_damage_per_sec": self.attacker_other_damage_per_sec,
            "seconds_to_clear_defender": self.seconds_to_clear_defender,
            "attacker_wins_within_5min": self.attacker_wins_within_5min,
            "win_margin": self.win_margin,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Damage formula
# ---------------------------------------------------------------------------


def _per_member_atk_damage_multiplier(
    member: NikkeSnapshot,
    *,
    defender_elements: Optional[list[Optional[str]]] = None,
) -> float:
    """Compute the multiplicative ATK-channel damage scaler for one Nikke.

    Per nikke.gg/damage-formula and Prydwen PvP guide (verified
    2026-05-10): the canonical layer order is:
      Base × Final ATK × Major Modifiers × Element × Charge × DamageUp

    Layers folded in here (multiplicative):
      * attack_damage_buff_pct (Crown / Mihara / Mast: RM …) — separate
        from ``atk_buff_pct`` which is already baked into ``effective_atk``.
      * crit expectation
      * Full Burst average — only ~25% match uptime → 1.125 proxy
      * element advantage — per-pair vs ``defender_elements``
      * element-damage % buffs (additive on element layer)
      * Effective Range +30% — **NORMAL ATTACKS ONLY, and only when the
        unit is in optimal range.** In PvP arena all targets sit at
        mid-range, so only SR units consistently benefit. RL/SG/MG/AR/SMG
        do NOT get the bonus in arena. (Cited: nikke.gg/arena-mechanics.)
      * Charge damage — SR/RL only, ON FULLY CHARGED SHOTS only. Average
        over a match accounting for partial charging is far below the
        2.5× full-charge multiplier. We use ``CHARGE_DAMAGE_AVG_MULT``
        (≈1.5×) as the realistic uptime-weighted figure.

    Layers NOT folded in here (handled separately or skipped):
      * True damage — bypasses DEF, skips Full Burst, skips charge,
        skips element advantage, doesn't crit. See ``_true_damage_dps``.
    """
    atk_mult = 1.0 + member.attack_damage_buff_pct / 100.0
    crit_rate = (DEFAULT_CRIT_RATE_PCT + member.crit_rate_buff_pct) / 100.0
    crit_dmg = (DEFAULT_CRIT_DAMAGE_PCT + member.crit_damage_buff_pct) / 100.0
    crit_mult = 1.0 + crit_rate * crit_dmg
    weapon_class = (member.weapon_class or "").upper()
    if weapon_class in CHARGED_WEAPON_CLASSES:
        # Base charge multiplier plus a fraction of any +charge_damage%
        # buffs the Nikke has accumulated. We dampen by 0.3 because most
        # of these buffs are burst-window-only (10s of a 30s match) and
        # the snapshot bakes them in as steady-state, over-counting.
        # Cap the buff at 300% — beyond that is unrealistic average
        # (some characters like Emilia accumulate 1300%+ from stacked
        # team buffs in the post-burst snapshot, but only briefly).
        capped_charge_dmg = min(member.charge_damage_buff_pct, 300.0)
        charge_mult = CHARGE_DAMAGE_AVG_MULT * (
            1.0 + 0.3 * capped_charge_dmg / 100.0
        )
    else:
        charge_mult = 1.0
    range_mult = EFFECTIVE_RANGE_BONUS if weapon_class in RANGE_BONUS_WEAPONS else 1.0
    elem_mult = element_advantage_factor(member.element, defender_elements or [])
    favored_frac = _favored_fraction(member.element, defender_elements or [])
    elem_dmg_mult = 1.0 + (member.element_damage_buff_pct / 100.0) * favored_frac
    # NOTE: Full Burst +50% IS NOT folded in here. match_sim's
    # _dps_decay_factor applies the FB window separately (1.0× during
    # window, 0.55× outside). Folding the steady-state average here
    # would double-count.
    return (
        atk_mult
        * crit_mult
        * elem_mult
        * elem_dmg_mult
        * range_mult
        * charge_mult
    )


def _favored_fraction(
    attacker_element: Optional[str],
    defender_elements: list[Optional[str]],
) -> float:
    """Fraction of defenders the attacker has element advantage over."""
    if not attacker_element:
        return 0.5  # unknown — split the bonus
    weak = ELEMENT_BEATS.get(attacker_element.lower())
    if not weak:
        return 0.5
    known = [e for e in defender_elements if e]
    if not known:
        return 0.5
    return sum(1 for e in known if e.lower() == weak) / len(known)


def _true_damage_dps(member: NikkeSnapshot, weapon_factor: float) -> float:
    """True damage per second for one member.

    True damage skips DEF, Full Burst, charge, range, element layers.
    Only scales with ATK × td_buff_pct × weapon shot rate. Element-damage
    buffs (e.g. flame damage +X%) DO apply per nikke.gg/damage-formula
    "Element Damage Up" layer.
    """
    if member.true_damage_buff_pct <= 0:
        return 0.0
    return (
        member.effective_atk
        * (member.true_damage_buff_pct / 100.0)
        * weapon_factor
        * (1.0 + member.element_damage_buff_pct / 100.0)
    )


def _def_reduction_factor(attacker_atk: float, defender_def: float) -> float:
    """Fraction of damage that gets through the defender's DEF.

    Per nikke.gg/damage-formula (verified 2026-05-10):
      Base Damage = (Buffed ATK + scaling) − (Buffed DEF + scaling)

    This is **subtractive**, not ratio-based. Floor at 5% of attacker ATK
    so that high-DEF defenders can't reduce damage below a minimum.
    Returned as the fraction of ATK that survives DEF mitigation:
        factor = max(0.05, (ATK - DEF) / ATK)

    With ATK ≫ DEF (typical PvP: 600k vs 60k → factor 0.90), this gives
    similar results to the old ratio model. The subtractive model matters
    more for ATK ≈ DEF cases (high-DEF tanks vs supports).
    """
    if attacker_atk <= 0:
        return 1.0
    net = attacker_atk - defender_def
    fraction = net / attacker_atk
    return max(MIN_DAMAGE_FRACTION_THROUGH_DEF, fraction)


def resolve(
    attacker: TeamEvaluation,
    defender: TeamEvaluation,
    *,
    base_normal_atks_per_sec: float = 8.0,
    first_burst_sec: float = DEFAULT_FIRST_BURST_SEC,
    cycle_period_sec: float = DEFAULT_CYCLE_PERIOD_SEC,
    damage_per_shot_fraction: Optional[float] = None,
    weapon_damage_per_second: Optional[dict[str, float]] = None,
    min_damage_fraction_through_def: Optional[float] = None,
) -> DamageResolution:
    """Compute attacker output vs defender effective HP for a 5-min PvP match.

    ``base_normal_atks_per_sec`` is the team-wide normal-attack rate the
    formula uses to translate ATK into a per-second damage budget. The
    default 8 hits/sec corresponds to typical PvP cadence (e.g., 4 fast-
    weapon Nikkes firing 2 shots/sec each).

    Slice #77 — ``first_burst_sec`` is when the first burst chain
    completes (computed from weapon mix by ``resolve_by_names``).
    ``cycle_period_sec`` is the time between subsequent burst chains.
    The burst payload is multiplied by the number of full bursts that
    fit in the match, giving SG/RL-fast comps a multi-cycle advantage
    over slow comps.

    Returns a :class:`DamageResolution` with the comparison numbers
    and a boolean win/loss verdict. Deterministic — same inputs always
    produce the same output.
    """
    # Slice #123 — runtime-tunable constants. Caller can override the
    # global defaults so the /validate page can recompute predictions
    # under different calibration assumptions and find a better fit.
    fallback_per_shot = (
        damage_per_shot_fraction
        if damage_per_shot_fraction is not None
        else DAMAGE_PER_SHOT_FRACTION
    )
    weapon_table = (
        weapon_damage_per_second
        if weapon_damage_per_second is not None
        else WEAPON_DAMAGE_PER_SECOND_FRACTION
    )
    def_floor = (
        min_damage_fraction_through_def
        if min_damage_fraction_through_def is not None
        else MIN_DAMAGE_FRACTION_THROUGH_DEF
    )

    out = DamageResolution()

    # Defender side breakdown:
    #   base_hp          = raw HP totals (excl. shield)
    #   shield_total     = shields applied during the burst chain
    #   heal_total       = healing accumulated over the match duration,
    #                      bounded by heal_duration × number_of_burst_cycles
    #                      (most NIKKE heals are 10-15s window per burst,
    #                      not always-on for the full 5-minute match).
    #   effective_hp     = base_hp + shield_total + heal_total
    # Pre-2026-05-09 the model used (base_hp + shield) only and never
    # applied healing — leading to ~3× under-prediction of defender
    # EHP on shield/heal-heavy tournament defenses.
    defender_base_hp = sum(m.base_hp + m.flat_hp_bonus for m in defender.members)
    defender_shield_total = sum(m.shield_value for m in defender.members)
    # Take MAX heal-per-sec across team rather than summing — when an
    # "all-allies" heal lands, every member's heal_per_second slot
    # captures the same source, so summing 5× over-counts. Max gives
    # the dominant healer's contribution. Multi-healer comps undercount
    # slightly but stay in the same order of magnitude.
    defender_heal_per_sec = max(
        (m.heal_per_second for m in defender.members), default=0.0
    )
    # Compute bursts_in_match here — used both for heal cycle count
    # and shield refresh below.
    if cycle_period_sec > 0 and first_burst_sec < MATCH_LENGTH_SEC:
        bursts_in_match = max(
            1,
            int((MATCH_LENGTH_SEC - first_burst_sec) / cycle_period_sec) + 1,
        )
    else:
        bursts_in_match = 1
    # Heal duration per cycle = the longest active heal-window across
    # the team (typically 10-15s). Total heal active time = duration ×
    # number of burst rotations.
    defender_heal_duration_per_cycle = max(
        (m.heal_duration for m in defender.members), default=0.0
    )
    heal_active_seconds = min(
        MATCH_LENGTH_SEC,
        defender_heal_duration_per_cycle * bursts_in_match,
    )
    defender_heal_total = defender_heal_per_sec * heal_active_seconds
    defender_team_hp = defender_base_hp + defender_shield_total + defender_heal_total

    defender_avg_def = (
        sum(m.effective_def for m in defender.members) / max(len(defender.members), 1)
    )
    out.defender_effective_hp = defender_team_hp
    out.defender_base_hp = defender_base_hp
    out.defender_shield_total = defender_shield_total
    out.defender_heal_total = defender_heal_total

    # Per-member damage budget — sum a per-second contribution and a one-
    # shot burst payload. The DEF-reduction depends on per-member ATK,
    # so compute it inside the loop.
    atk_dps = 0.0
    true_dps = 0.0
    other_dps = 0.0
    burst_total = 0.0

    defender_has_shields = any(d.shield_value > 0 for d in defender.members)
    for m in attacker.members:
        eff_atk = m.effective_atk
        contrib = MemberContribution(
            name=m.name,
            weapon_class=m.weapon_class,
            element=m.element,
        )

        if eff_atk <= 0:
            out.attacker_per_member.append(contrib)
            continue

        # Slice #97 — per-WeaponClass fraction-of-ATK-per-second instead
        # of a team-wide constant divided by member count. This lets
        # SR/RL-heavy comps (slower fire rate) score lower steady-state
        # DPS than AR/SMG/MG-heavy comps, which matches observed PvP
        # behavior. ``base_normal_atks_per_sec`` is kept as a kwarg for
        # backward-compat callers but is no longer multiplied in — its
        # job is now folded into the per-weapon table.
        weapon_factor = (
            weapon_table.get(m.weapon_class.upper(), fallback_per_shot)
            if m.weapon_class
            else fallback_per_shot
        )

        # ATK-channel damage per second (mitigated by defender DEF).
        atk_mult = _per_member_atk_damage_multiplier(
            m, defender_elements=[d.element for d in defender.members]
        )
        def_factor = max(def_floor, _def_reduction_factor(eff_atk, defender_avg_def))
        atk_per_sec = eff_atk * atk_mult * def_factor * weapon_factor
        atk_dps += atk_per_sec
        contrib.atk_damage_per_sec = atk_per_sec

        # True damage — bypasses DEF entirely AND skips the
        # Full Burst / charge / range / element-advantage / crit
        # layers per nikke.gg/damage-formula. Only scales with ATK ×
        # td% × element-damage % × shot rate.
        true_per_sec = _true_damage_dps(m, weapon_factor)
        true_dps += true_per_sec
        contrib.true_damage_per_sec = true_per_sec

        # Other damage channels — pierce/shield/sustained. We give partial
        # credit for the pierce + sustained buffs, and shield-damage only
        # when the defender team has shields (proxy via avg shield > 0).
        shield_credit = m.shield_damage_buff_pct if defender_has_shields else 0.0
        other_mult = (
            (m.pierce_damage_buff_pct / 100.0) * 0.5
            + shield_credit / 100.0 * 0.3
            + (m.sustained_damage_buff_pct / 100.0) * 0.2
        )
        other_per_sec = eff_atk * other_mult * weapon_factor
        other_dps += other_per_sec
        contrib.other_damage_per_sec = other_per_sec

        # Burst payload — DEAL_DAMAGE in burst skills, accumulated on each
        # member's burst_damage_magnitude (one-shot, so multiply by ATK once).
        member_burst = m.burst_damage_magnitude * eff_atk * def_factor
        burst_total += member_burst
        contrib.burst_payload_per_cycle = member_burst

        out.attacker_per_member.append(contrib)

    out.attacker_atk_damage_per_sec = atk_dps
    out.attacker_true_damage_per_sec = true_dps
    out.attacker_other_damage_per_sec = other_dps

    # Slice #96 — burst contribution as steady-state DPS, not as a
    # t=0 head-start subtraction. The previous model multiplied
    # `burst_total × bursts_in_match` and credited it ALL at the
    # first burst time, which overcounted because (a) the 8th burst
    # doesn't land until ~t=290s and can't help if the defender is
    # already cleared, and (b) most NIKKE burst skills have
    # cooldowns that prevent firing every cycle. Treating burst as
    # `burst_total / cycle_period_sec` time-averaged DPS gives a
    # closer first-order approximation: the 5-minute window slowly
    # accumulates cumulative burst damage at a steady rate.
    # bursts_in_match was already computed above for heal cycle counting.
    if cycle_period_sec > 0 and first_burst_sec < MATCH_LENGTH_SEC:
        burst_dps_equivalent = burst_total / cycle_period_sec
    else:
        burst_dps_equivalent = 0.0

    # ``attacker_burst_payload`` keeps its display semantics —
    # "what's the total burst-skill damage accumulated over the
    # match if every cycle fires" — but ``attacker_team_dps`` and
    # the clear-time calc now use the time-averaged equivalent so
    # win-margin numbers are honest.
    burst_total_over_match = burst_total * bursts_in_match
    out.attacker_burst_payload = burst_total_over_match
    out.attacker_team_dps = atk_dps + true_dps + other_dps + burst_dps_equivalent

    if out.attacker_team_dps > 0:
        seconds_to_clear = first_burst_sec + defender_team_hp / out.attacker_team_dps
    else:
        seconds_to_clear = float("inf")
    out.seconds_to_clear_defender = seconds_to_clear

    if bursts_in_match > 1:
        out.notes.append(
            f"team fits {bursts_in_match} burst rotations in match "
            f"(first @ {first_burst_sec:.1f}s, period {cycle_period_sec:.0f}s, "
            f"avg burst-DPS ~{burst_dps_equivalent:,.0f})"
        )

    out.attacker_wins_within_5min = seconds_to_clear < MATCH_LENGTH_SEC
    out.win_margin = MATCH_LENGTH_SEC - seconds_to_clear
    out.bursts_in_match = bursts_in_match

    # Estimated damage dealt per attacker over the match.
    # match_active = min(MATCH_LENGTH, seconds_to_clear) — once the
    # defender is cleared the attacker stops dealing damage.
    #
    # T1 fix (2026-05-19): cap burst cycles by match_active too. The
    # team-level ``bursts_in_match`` is still computed against the full
    # 5-minute window (left alone so defender heal modeling stays as
    # the current calibration — T5 reworks that), but per-attacker
    # contribution must respect the actual clear time. Previously a
    # Helm (Treasure) on a 12s clear got credit for 8 burst cycles,
    # producing 140M sim vs 744K actual.
    match_active = min(MATCH_LENGTH_SEC, max(0.0, seconds_to_clear))
    if cycle_period_sec > 0 and first_burst_sec <= match_active:
        attacker_active_bursts = max(
            1,
            int((match_active - first_burst_sec) / cycle_period_sec) + 1,
        )
    elif first_burst_sec <= match_active:
        attacker_active_bursts = 1
    else:
        # Defender clears in less than first_burst time — no bursts fire.
        attacker_active_bursts = 0
    for c in out.attacker_per_member:
        sustained = (
            c.atk_damage_per_sec + c.true_damage_per_sec + c.other_damage_per_sec
        )
        c.estimated_damage_dealt = (
            sustained * match_active
            + c.burst_payload_per_cycle * attacker_active_bursts
        )

    # Defender per-member rows: HP / shield / heal contribution. The
    # validation page joins these with the captured per-Nikke heal
    # ground truth from the Champion duel screen.
    #
    # Per-defender estimated_damage_taken: distribute team incoming
    # damage evenly across 5 defenders, then subtract per-Nikke
    # shield + share of team heal. Even-split is a known
    # approximation — real NIKKE uses position-based targeting (per
    # nikke-pvp-mechanics memory) which isn't modeled yet.
    attacker_total_damage = sum(
        c.estimated_damage_dealt for c in out.attacker_per_member
    )
    n_defenders = max(1, len(defender.members))
    per_defender_damage_in = attacker_total_damage / n_defenders
    per_defender_heal_share = defender_heal_total / n_defenders
    for d in defender.members:
        max_hp = d.base_hp + d.flat_hp_bonus
        net_damage_taken = max(
            0.0,
            per_defender_damage_in - d.shield_value - per_defender_heal_share,
        )
        hp_remaining_pct = (
            max(0.0, min(100.0, (max_hp - net_damage_taken) / max_hp * 100.0))
            if max_hp > 0 else 0.0
        )
        contrib = MemberContribution(
            name=d.name,
            weapon_class=d.weapon_class,
            element=d.element,
            base_hp=d.base_hp,
            flat_hp_bonus=d.flat_hp_bonus,
            shield_value=d.shield_value,
            heal_per_second=d.heal_per_second,
            heal_duration=d.heal_duration,
            estimated_heal_performed=(
                d.heal_per_second
                * min(MATCH_LENGTH_SEC, d.heal_duration * bursts_in_match)
            ),
            estimated_damage_taken=per_defender_damage_in,
            estimated_hp_remaining_pct=hp_remaining_pct,
        )
        out.defender_per_member.append(contrib)

    # Diagnostic notes — only the ones a human-reader would want to see.
    if burst_total >= defender_team_hp:
        out.notes.append("burst payload alone clears defender HP")
    if true_dps >= atk_dps * 0.3:
        out.notes.append("≥30% of damage is true damage (DEF-bypass carry)")
    if def_factor := _def_reduction_factor(
        sum(m.effective_atk for m in attacker.members) / max(len(attacker.members), 1),
        defender_avg_def,
    ):
        if def_factor <= 0.15:
            out.notes.append(
                f"defender DEF severely mitigates ATK channel "
                f"({def_factor*100:.1f}% gets through)"
            )

    return out


def resolve_by_names(
    attacker_names: Iterable[str],
    defender_names: Iterable[str],
    **kwargs,
) -> Optional[DamageResolution]:
    """Convenience wrapper — accepts character-name lists.

    Returns ``None`` when either team can't be fully evaluated (one or
    more members not in the encoded skill registry).

    Slice #77: derives ``first_burst_sec`` from the attacker's weapon
    mix when the caller didn't override it, so SG/RL-fast comps get a
    multi-cycle burst-payload bonus over slow MG/SMG comps.
    """
    attacker_list = list(attacker_names)
    defender_list = list(defender_names)
    a = evaluate_by_names(attacker_list)
    if a is None:
        return None
    d = evaluate_by_names(defender_list)
    if d is None:
        return None

    if "first_burst_sec" not in kwargs:
        from .timeline import compute_burst_chain_offsets, _load_weapons
        weapons = _load_weapons(attacker_list)
        if any(weapons):
            kwargs["first_burst_sec"] = compute_burst_chain_offsets(
                weapons, member_names=attacker_list
            )[2]

    return resolve(a, d, **kwargs)
