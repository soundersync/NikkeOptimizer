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

# Element advantage: +10% damage on weakness. We assume ~50% of attacks
# land on weak targets (rainbow teams average) → +5% steady-state proxy.
ELEMENT_ADVANTAGE_AVERAGE = 1.05

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

# Charge damage bonus: SR and RL hit harder per shot when fully charged.
# Most NIKKE SR/RL units sit at the +150% tier (1 + 1.5 = 2.5× per shot).
# Fold this in as an average-case multiplier on the weapon factor
# inside ``_per_member_atk_damage_multiplier``. Per nikke.gg, this
# applies to charged shots only; for the steady-state DPS proxy we
# treat it as always-on (valid for PvP since SR/RL chars in arena
# almost always fire fully charged).
CHARGE_DAMAGE_DEFAULT_MULTIPLIER = 2.5  # 1 + 1.5 base
CHARGED_WEAPON_CLASSES = frozenset({"SR", "RL"})

# Effective Range bonus: +30% when weapon class matches the engagement
# distance. PvP arena distance is generally medium and most arena-
# relevant units carry their effective-range bonus. We treat this as
# always-on for PvP simulation (per nikke.gg arena-mechanics).
EFFECTIVE_RANGE_BONUS = 1.30

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
class DamageResolution:
    """Result of the Team A vs Team B resolution."""

    # Per-team aggregates (5-Nikke totals)
    attacker_team_dps: float = 0.0  # attacker damage output per second
    attacker_burst_payload: float = 0.0  # attacker one-shot burst total
    defender_effective_hp: float = 0.0  # defender pool to deplete

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

    def to_dict(self) -> dict:
        return {
            "attacker_team_dps": self.attacker_team_dps,
            "attacker_burst_payload": self.attacker_burst_payload,
            "defender_effective_hp": self.defender_effective_hp,
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


def _per_member_atk_damage_multiplier(member: NikkeSnapshot) -> float:
    """Compute the multiplicative ATK-channel damage scaler for one Nikke.

    Combines:
      * attack_damage_buff_pct (Crown / Asuka / Mihara / Mast: RM ...)
        — distinct from ``atk_buff_pct``, which is already baked into
        :attr:`NikkeSnapshot.effective_atk`. We do NOT add atk_buff_pct
        here or it would double-count.
      * crit expectation (rate × bonus damage)
      * full burst average
      * element advantage average
      * effective range bonus (+30%, always-on for PvP)
      * charge damage bonus (SR/RL only; +150% by default)

    Source: nikke.gg/damage-formula and West Games NIKKE DPS calculator,
    cross-referenced May 2026.
    """
    atk_mult = 1.0 + member.attack_damage_buff_pct / 100.0
    crit_rate = (DEFAULT_CRIT_RATE_PCT + member.crit_rate_buff_pct) / 100.0
    crit_dmg = (DEFAULT_CRIT_DAMAGE_PCT + member.crit_damage_buff_pct) / 100.0
    crit_mult = 1.0 + crit_rate * crit_dmg
    weapon_class = (member.weapon_class or "").upper()
    charge_mult = (
        CHARGE_DAMAGE_DEFAULT_MULTIPLIER
        if weapon_class in CHARGED_WEAPON_CLASSES
        else 1.0
    )
    return (
        atk_mult
        * crit_mult
        * FULL_BURST_AVERAGE_MULTIPLIER
        * ELEMENT_ADVANTAGE_AVERAGE
        * (1.0 + member.element_damage_buff_pct / 100.0)
        * EFFECTIVE_RANGE_BONUS
        * charge_mult
    )


def _def_reduction_factor(attacker_atk: float, defender_def: float) -> float:
    """Fraction of damage that gets through the defender's DEF.

    Per the published NIKKE formula. Floored at 5% so high-DEF defenders
    can't reduce damage below the floor. Returned as a multiplier in [0.05, 1.0].
    """
    if attacker_atk + defender_def <= 0:
        return 1.0
    fraction = attacker_atk / (attacker_atk + defender_def)
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

    # Defender side: use mean DEF across the team and effective HP totals.
    defender_team_hp = sum(m.effective_hp for m in defender.members)
    defender_avg_def = (
        sum(m.effective_def for m in defender.members) / max(len(defender.members), 1)
    )
    out.defender_effective_hp = defender_team_hp

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
        if eff_atk <= 0:
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
        atk_mult = _per_member_atk_damage_multiplier(m)
        def_factor = max(def_floor, _def_reduction_factor(eff_atk, defender_avg_def))
        atk_per_sec = eff_atk * atk_mult * def_factor * weapon_factor
        atk_dps += atk_per_sec

        # True damage — bypasses DEF entirely. Drives matchups vs Centi/
        # Crown shield comps. Applied as % of ATK output (base ATK only,
        # not the multiplier — this is the "deal X% of ATK as true damage"
        # in-game wording). Same weapon factor applies.
        true_per_sec = (
            eff_atk * (m.true_damage_buff_pct / 100.0) * weapon_factor
        )
        true_dps += true_per_sec

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

        # Burst payload — DEAL_DAMAGE in burst skills, accumulated on each
        # member's burst_damage_magnitude (one-shot, so multiply by ATK once).
        burst_total += m.burst_damage_magnitude * eff_atk * def_factor

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
    if cycle_period_sec > 0 and first_burst_sec < MATCH_LENGTH_SEC:
        bursts_in_match = max(
            1,
            int((MATCH_LENGTH_SEC - first_burst_sec) / cycle_period_sec) + 1,
        )
        burst_dps_equivalent = burst_total / cycle_period_sec
    else:
        bursts_in_match = 1
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
