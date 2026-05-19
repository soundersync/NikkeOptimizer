"""Static team evaluator — first slice of the Phase-3 simulator.

This isn't a full event-loop simulator yet. It computes a *snapshot* of
a 5-Nikke team's combat state at the moment immediately after a Full
Burst chain has fired and all initial buffs / shields are active. From
that snapshot we derive aggregate metrics:

  * **dps_estimate**     — sum of per-Nikke ATK after buffs (proxy for
                           sustained damage output)
  * **burst_payload**    — sum of one-shot burst damage magnitudes
                           (proxy for burst windows)
  * **ehp_estimate**     — sum of effective HP including shields
  * **sustain_index**    — sum of HEAL_PER_SECOND magnitudes × duration
                           (proxy for stall capacity)
  * **team_atk_buff_pct**— total stacked ATK buff % applied to the team
  * **team_def_buff_pct**— same for DEF

The evaluator is **stateless** and **deterministic** — same inputs
always produce the same output. It's used by the optimizer to score
teams more rigorously than the hand-curated synergy table can.

Crucially, this evaluator IGNORES:
  * timing, turn order, burst chain order
  * hit-by-hit damage accumulation
  * RNG (whiffs, target selection)
  * conditional triggers (it applies them all greedily)
  * state machines (it treats them as fully active)

These are the responsibility of the future event-loop simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    TargetKind,
    TriggerKind,
)
from .registry import get as registry_get

# Ceiling for heal-per-second magnitude as a fraction of caster's max
# HP. NIKKE's strongest realistic healers sit around 3-5% of HP per
# second; values above this in the DSL are usually mis-encoded buff
# amplifiers (e.g. "HP Potency +13.65%" being shoehorned into a
# HEAL_PER_SECOND effect). The cap bounds simulator-side error from
# those inconsistencies. Should be relaxed once DSL heal encodings
# are audited and ``scaling_source`` is set everywhere.
HEAL_RATE_CEILING = 0.05  # 5% of caster max HP per second


# D1 duty-cycle modeling: representative PvP match length used to
# scale short-duration buffs. A 3-second buff in a 30-second match
# only contributes 10% uptime; treating it as always-on (the prior
# behavior) over-credited burst-window buffs by 2-5×.
#
# Calibrated against tournament observed match lengths: most resolved
# PvP duels (rookie + champion) finish in 20-40s before the 5-min
# timeout. Picked the midpoint as the typical sustained window.
PVP_AVG_MATCH_LENGTH_SEC = 20.0


def _duty_cycle_factor(duration_seconds: Optional[float]) -> float:
    """Return min(1.0, duration / PVP_AVG_MATCH_LENGTH_SEC).

    duration None or 0 → 1.0 (treat unspecified as always-on; lots of
    encodings omit duration for permanent passives). Long durations
    (≥ match length) → 1.0 (always-on within the match). Short
    durations (e.g. 3-15s burst window buffs) → fractional uptime.
    """
    if not duration_seconds or duration_seconds <= 0:
        return 1.0
    if duration_seconds >= PVP_AVG_MATCH_LENGTH_SEC:
        return 1.0
    return duration_seconds / PVP_AVG_MATCH_LENGTH_SEC


# Triggers that the evaluator considers "active" in the snapshot. We
# treat the team as if these conditions have all been met — i.e. burst
# chain has fired, full burst window is active, the unit has been hit
# enough times, etc. Skipping ON_KILL / ON_TIMER / ON_HIT-once-only
# triggers because they're per-event and not per-snapshot.
_SNAPSHOT_TRIGGERS = {
    TriggerKind.ALWAYS,
    TriggerKind.ON_BATTLE_START,
    TriggerKind.ON_BURST_USE,
    TriggerKind.ON_ALLY_BURST_USE,
    TriggerKind.ON_FULL_BURST_START,
    # D4 — ON_FULL_BURST_END fires after every burst chain (typically
    # ~10s post-burst). Used by stall-comp staples (Trina S1 = team
    # heal 4.06%/s for 5s, Centi S1 = team shield, Blanc S2 = team
    # heal, etc.). Previously this trigger was silently dropped which
    # massively under-credited stall-comp heal/shield output.
    TriggerKind.ON_FULL_BURST_END,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NikkeSnapshot:
    """Per-Nikke runtime state after the burst chain has fired."""

    name: str
    base_atk: int = 100_000
    base_hp: int = 1_000_000
    base_def: int = 30_000

    # Identity fields used by Target filter narrowing (element/weapon/role).
    # Strings to avoid coupling to data.enums; values are lower-cased
    # forms of the canonical enum (e.g. "water", "rl", "defender").
    # Empty/None means the filter doesn't match this Nikke for filtered
    # effects — but unfiltered effects still apply normally.
    element: Optional[str] = None
    weapon_class: Optional[str] = None
    role: Optional[str] = None
    # Burst position: "1", "2", "3", or "flex". Used by match_sim's
    # burst-chain model to determine fire order (B1 → B2 → B3 by
    # leftmost-eligible per chain).
    burst_position: Optional[str] = None
    # Per-Nikke burst-skill cooldown in seconds. Default 20s matches
    # the most common cooldown in NIKKE; some Nikkes have 40s, 30s,
    # 15s. Loaded from OwnedCharacter.burst_cooldown_seconds when
    # available.
    burst_cooldown_sec: float = 20.0

    # Flat bonuses from cross-stat scaling effects ("ATK +30% of caster's ATK").
    # Added to base_<stat> before the multiplicative buff_pct is applied.
    flat_atk_bonus: float = 0.0
    flat_hp_bonus: float = 0.0
    flat_def_bonus: float = 0.0

    atk_buff_pct: float = 0.0
    def_buff_pct: float = 0.0
    crit_rate_buff_pct: float = 0.0
    crit_damage_buff_pct: float = 0.0
    charge_damage_buff_pct: float = 0.0
    charge_speed_buff_pct: float = 0.0
    element_damage_buff_pct: float = 0.0

    # Damage-type-specific buffs — distinct from atk_buff_pct. Tracked
    # separately so the simulator can apply each multiplier only on the
    # correct damage instances.
    attack_damage_buff_pct: float = 0.0
    true_damage_buff_pct: float = 0.0
    pierce_damage_buff_pct: float = 0.0
    shield_damage_buff_pct: float = 0.0
    core_damage_buff_pct: float = 0.0
    parts_damage_buff_pct: float = 0.0
    sustained_damage_buff_pct: float = 0.0
    burst_skill_damage_buff_pct: float = 0.0

    shield_value: float = 0.0
    heal_per_second: float = 0.0
    heal_duration: float = 0.0
    # D3 — continuous shield absorption rate for shields that REFRESH
    # within the match. A 7%-HP shield with duration=5s refreshes every
    # 5s in-game (60 cycles in a 5min match); its effective absorption
    # rate is shield_value / duration. This is summed alongside the
    # one-shot ``shield_value`` so refreshing-shield characters like
    # Centi (Treasure) get proper credit for continuous damage soak.
    # Only set when duration_seconds is short (< 30s); long-duration
    # shields are treated as one-shot.
    shield_absorption_per_sec: float = 0.0

    # Source-attribution fields. ``heal_per_second`` is the rate the
    # snapshot RECEIVES (max across all incoming heal effects, since
    # all-allies heals broadcast the same value to every member).
    # ``heal_emit_per_second`` is the rate the snapshot SOURCES — only
    # set when this character's own skill emits the heal effect, so
    # match_sim can attribute heal output to the actual healer instead
    # of guessing via "max heal_per_second across team".
    heal_emit_per_second: float = 0.0
    heal_emit_duration: float = 0.0

    burst_damage_magnitude: float = 0.0  # sum of burst-skill DEAL_DAMAGE × ATK
    burst_aoe_target_count: int = 1      # how many enemies the burst hits
                                          # (per nikke.gg, AOE bursts apply
                                          # FULL magnitude to EACH enemy)
    has_pierce: bool = False
    is_taunting: bool = False

    @property
    def effective_atk(self) -> float:
        return (self.base_atk + self.flat_atk_bonus) * (1.0 + self.atk_buff_pct / 100.0)

    @property
    def effective_def(self) -> float:
        return (self.base_def + self.flat_def_bonus) * (1.0 + self.def_buff_pct / 100.0)

    @property
    def effective_hp(self) -> float:
        return self.base_hp + self.flat_hp_bonus + self.shield_value


@dataclass
class TeamEvaluation:
    """Aggregate snapshot of a 5-Nikke team."""

    members: list[NikkeSnapshot] = field(default_factory=list)

    @property
    def dps_estimate(self) -> float:
        """Sum of effective ATK across the team."""
        return sum(m.effective_atk for m in self.members)

    @property
    def burst_payload(self) -> float:
        """Sum of one-shot burst damage from each member's burst skill."""
        return sum(m.burst_damage_magnitude * m.effective_atk for m in self.members)

    @property
    def ehp_estimate(self) -> float:
        """Effective HP — base HP + shield."""
        return sum(m.effective_hp for m in self.members)

    @property
    def sustain_index(self) -> float:
        """Total healing across the team over its heal-per-second window."""
        return sum(m.heal_per_second * m.heal_duration for m in self.members)

    @property
    def team_atk_buff_pct(self) -> float:
        return sum(m.atk_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def team_def_buff_pct(self) -> float:
        return sum(m.def_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def total_shield(self) -> float:
        return sum(m.shield_value for m in self.members)

    # ---- Damage-type buff aggregates (from DSL slice #55) -----------------

    @property
    def total_flat_atk_bonus(self) -> float:
        """Sum of cross-stat flat ATK bonuses (e.g. Naga's 'ATK +16% of caster's ATK')."""
        return sum(m.flat_atk_bonus for m in self.members)

    @property
    def team_true_damage_buff_pct(self) -> float:
        return sum(m.true_damage_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def team_attack_damage_buff_pct(self) -> float:
        return sum(m.attack_damage_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def team_pierce_damage_buff_pct(self) -> float:
        return sum(m.pierce_damage_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def team_shield_damage_buff_pct(self) -> float:
        return sum(m.shield_damage_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def team_core_damage_buff_pct(self) -> float:
        return sum(m.core_damage_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def team_burst_skill_damage_buff_pct(self) -> float:
        return sum(m.burst_skill_damage_buff_pct for m in self.members) / max(len(self.members), 1)

    @property
    def vs_high_def_damage_index(self) -> float:
        """Heuristic: how well this team punches through high-DEF defenders.

        Combines true-damage buffs (which bypass DEF entirely), pierce
        damage (multi-target through cover), and shield-damage buffs
        (relevant against shielded targets like Centi/Crown comps).
        Higher score = better matchup vs durable defenders.
        """
        per_member = []
        for m in self.members:
            score = (
                m.true_damage_buff_pct * 1.0
                + m.pierce_damage_buff_pct * 0.7
                + m.shield_damage_buff_pct * 0.5
                + (100.0 if m.has_pierce else 0.0)
            )
            per_member.append(score)
        return sum(per_member)

    def to_dict(self) -> dict:
        return {
            "members": [m.name for m in self.members],
            "dps_estimate": self.dps_estimate,
            "burst_payload": self.burst_payload,
            "ehp_estimate": self.ehp_estimate,
            "sustain_index": self.sustain_index,
            "team_atk_buff_pct": self.team_atk_buff_pct,
            "team_def_buff_pct": self.team_def_buff_pct,
            "total_shield": self.total_shield,
            "total_flat_atk_bonus": self.total_flat_atk_bonus,
            "team_true_damage_buff_pct": self.team_true_damage_buff_pct,
            "team_attack_damage_buff_pct": self.team_attack_damage_buff_pct,
            "team_pierce_damage_buff_pct": self.team_pierce_damage_buff_pct,
            "team_shield_damage_buff_pct": self.team_shield_damage_buff_pct,
            "team_core_damage_buff_pct": self.team_core_damage_buff_pct,
            "team_burst_skill_damage_buff_pct": self.team_burst_skill_damage_buff_pct,
            "vs_high_def_damage_index": self.vs_high_def_damage_index,
        }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


_ENEMY_TARGET_KINDS = {
    TargetKind.ALL_ENEMIES,
    TargetKind.ENEMY_HIGHEST_HP,
    TargetKind.ENEMY_LOWEST_HP,
    TargetKind.ENEMY_FRONT,
    TargetKind.ENEMIES_RANDOM_K,
    TargetKind.PRIMARY_TARGET,
}


def _enemy_target_multiplicity(target) -> int:
    """How many enemies an enemy-targeting effect hits in a 5-Nikke fight.

    Per nikke.gg, AOE bursts hit each enemy at FULL magnitude (not split).
    So a "925% to all enemies" effect contributes 5× the magnitude to the
    caster's total burst potential.
    """
    if target.kind == TargetKind.ALL_ENEMIES:
        return 5
    if target.kind == TargetKind.ENEMIES_RANDOM_K:
        return max(1, target.count)
    if target.kind == TargetKind.ENEMY_FRONT:
        return min(2, max(1, target.count))  # taunters typically 1-2
    # ST: ENEMY_HIGHEST_HP, ENEMY_LOWEST_HP, PRIMARY_TARGET
    return 1


def _apply_effect_to_snapshot(
    effect: Effect,
    caster: NikkeSnapshot,
    team: list[NikkeSnapshot],
    burst_user: Optional[NikkeSnapshot] = None,
) -> None:
    """Apply a single Effect to the appropriate target(s) in the team.

    ``burst_user`` is the Nikke whose burst is currently being resolved —
    used by ``BURST_USER`` target kind. When ``None`` we fall back to the
    caster.
    """
    # Burst damage tracking: enemy-targeted DEAL_DAMAGE effects don't
    # have a snapshot target on our team, but they still represent damage
    # this Nikke contributes. Accumulate on the caster so burst_payload
    # rolls up correctly at the team level.
    #
    # Per nikke.gg/damage-formula: AOE bursts apply FULL magnitude to
    # EACH enemy (not split). Store per-target magnitude AND the target
    # count separately so match_sim can apply payload per-target.
    if (
        effect.kind in (EffectKind.DEAL_DAMAGE, EffectKind.DEAL_TRUE_DAMAGE)
        and effect.target.kind in _ENEMY_TARGET_KINDS
    ):
        target_mult = _enemy_target_multiplicity(effect.target)
        # Store per-target magnitude (NOT multiplied).
        caster.burst_damage_magnitude += effect.magnitude
        # Track max target count seen on this caster.
        caster.burst_aoe_target_count = max(
            caster.burst_aoe_target_count, target_mult
        )

    targets = _resolve_targets(effect, caster, team, burst_user)
    for t in targets:
        _apply_to_one(effect, t, caster)


def _matches_filters(snap: NikkeSnapshot, target) -> bool:
    """Slice #68: narrow ally targets by element/weapon/role filters.

    When the Target has filter_element / filter_weapon / filter_role set,
    only allies whose ``NikkeSnapshot`` identity matches pass through.
    When the snapshot's identity field is ``None`` (identity not threaded
    through), the filter falls back to "match" — preserves the
    pre-#68 behavior where buffs without identity data apply to all
    allies. This keeps tests that don't pass identities from regressing.
    """
    fe = getattr(target, "filter_element", None)
    if fe is not None and snap.element is not None:
        if snap.element != fe.value.lower():
            return False
    fw = getattr(target, "filter_weapon", None)
    if fw is not None and snap.weapon_class is not None:
        if snap.weapon_class != fw.value.lower():
            return False
    fr = getattr(target, "filter_role", None)
    if fr is not None and snap.role is not None:
        if snap.role != fr.value.lower():
            return False
    return True


def _resolve_targets(
    effect: Effect,
    caster: NikkeSnapshot,
    team: list[NikkeSnapshot],
    burst_user: Optional[NikkeSnapshot],
) -> list[NikkeSnapshot]:
    """Map a Target spec to the actual NikkeSnapshot(s) it applies to.

    Enemy-targeting effects are dropped here — the static evaluator only
    tracks ally state. The future simulator will add an opposing team.

    Element/weapon/role filters (slice #68) narrow ally targets when
    the snapshot's identity is known. See ``_matches_filters``.
    """
    kind = effect.target.kind
    if kind is TargetKind.SELF:
        # SELF ignores filters — the cast-self pattern always applies.
        return [caster]
    if kind is TargetKind.ALL_ALLIES:
        return [m for m in team if _matches_filters(m, effect.target)]
    if kind is TargetKind.NEAREST_ALLIES:
        # Static evaluator has no notion of "nearest" — apply to all
        # allies as an upper bound. The simulator will model proximity.
        return [m for m in team if _matches_filters(m, effect.target)]
    if kind is TargetKind.BURST_USER:
        target_snap = burst_user if burst_user is not None else caster
        return [target_snap] if _matches_filters(target_snap, effect.target) else []
    if kind is TargetKind.ALLY_HIGHEST_ATK:
        candidates = [m for m in team if _matches_filters(m, effect.target)]
        if not candidates:
            return []
        return [max(candidates, key=lambda m: m.effective_atk)]
    if kind is TargetKind.ALLY_LOWEST_HP:
        # Static eval has uniform HP; pick first ``count`` members from
        # the filtered set.
        candidates = [m for m in team if _matches_filters(m, effect.target)]
        n = max(1, effect.target.count)
        return candidates[:n]
    # Enemy targets — silently dropped at this layer.
    return []


def _apply_to_one(effect: Effect, target: NikkeSnapshot, caster: NikkeSnapshot) -> None:
    """Apply a single typed effect to a single target snapshot."""
    kind = effect.kind
    mag = effect.magnitude
    scaling = effect.scaling_source

    # Cross-stat scaling: when set, the magnitude is interpreted as
    # caster.<stat> × magnitude/100, added as a flat bonus to the target.
    # Example: "ATK +30% of caster's ATK" with caster ATK 100k → +30k
    # flat ATK on the target. We only honor this for ATK/HP/DEF buffs;
    # other kinds with a scaling_source are ambiguous and fall through.
    if scaling is not ScalingSource.NONE:
        if kind is EffectKind.BUFF_ATK and scaling is ScalingSource.CASTER_ATK:
            target.flat_atk_bonus += caster.base_atk * (mag / 100.0)
            return
        if kind is EffectKind.BUFF_HP and scaling is ScalingSource.CASTER_MAX_HP:
            target.flat_hp_bonus += caster.base_hp * (mag / 100.0)
            return
        if kind is EffectKind.BUFF_DEFENSE and scaling is ScalingSource.CASTER_DEF:
            target.flat_def_bonus += caster.base_def * (mag / 100.0)
            return
        # HEAL_PER_SECOND with scaling_source — magnitude is %-of-caster
        # ATK/MAX_HP/DEF (most NIKKE healing skills are scaled this way).
        # Without this the magnitude was treated as a literal HP-per-sec
        # number, producing 100x-1000x under-prediction of heal totals.
        if kind in (EffectKind.HEAL_PER_SECOND, EffectKind.HEAL_HP_FLAT):
            base = (
                caster.base_atk if scaling is ScalingSource.CASTER_ATK
                else caster.base_hp if scaling is ScalingSource.CASTER_MAX_HP
                else caster.base_def if scaling is ScalingSource.CASTER_DEF
                else 0
            )
            scaled_mag = base * (mag / 100.0)
            dur = effect.duration_seconds or 1.0
            target.heal_per_second = max(target.heal_per_second, scaled_mag)
            target.heal_duration = max(target.heal_duration, dur)
            caster.heal_emit_per_second = max(caster.heal_emit_per_second, scaled_mag)
            caster.heal_emit_duration = max(caster.heal_emit_duration, dur)
            return
        # GRANT_SHIELD — same treatment for ATK/DEF scaled shields. The
        # default branch below already handles CASTER_MAX_HP shields
        # (via caster.base_hp × mag/100), so only fix non-HP scaling.
        if kind is EffectKind.GRANT_SHIELD and scaling is not ScalingSource.NONE:
            base = (
                caster.base_atk if scaling is ScalingSource.CASTER_ATK
                else caster.base_hp if scaling is ScalingSource.CASTER_MAX_HP
                else caster.base_def if scaling is ScalingSource.CASTER_DEF
                else caster.base_hp  # safe fallback
            )
            target.shield_value += base * (mag / 100.0)
            return
        # Unhandled scaling+kind combo — fall through to literal % below
        # so the value isn't silently dropped.

    # D1 duty-cycle: scale short-duration buffs by their fraction of a
    # typical PvP match. A 3-second +160% ATK buff with PVP_AVG=30s
    # contributes effectively +16% rather than +160%. Effects without
    # duration (passives) or with very long duration are untouched.
    duty = _duty_cycle_factor(effect.duration_seconds)
    scaled_mag = mag * duty

    if kind is EffectKind.BUFF_ATK:
        target.atk_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_DEFENSE:
        target.def_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_HP:
        target.base_hp = int(target.base_hp * (1.0 + scaled_mag / 100.0))
    elif kind is EffectKind.BUFF_CRIT_RATE:
        target.crit_rate_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_CRIT_DAMAGE:
        target.crit_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_CHARGE_DAMAGE:
        target.charge_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_CHARGE_SPEED:
        target.charge_speed_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_ELEMENT_DAMAGE:
        target.element_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_ATTACK_DAMAGE:
        target.attack_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_TRUE_DAMAGE:
        target.true_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_PIERCE_DAMAGE:
        target.pierce_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_SHIELD_DAMAGE:
        target.shield_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_CORE_DAMAGE:
        target.core_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_DAMAGE_TO_PARTS:
        target.parts_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_SUSTAINED_DAMAGE:
        target.sustained_damage_buff_pct += scaled_mag
    elif kind is EffectKind.BUFF_BURST_SKILL_DAMAGE:
        target.burst_skill_damage_buff_pct += scaled_mag
    elif kind is EffectKind.GRANT_SHIELD:
        # Magnitude is % of caster's max HP — caster's HP, not target's.
        shield_amount = caster.base_hp * (mag / 100.0)
        target.shield_value += shield_amount
        # D3 — if this shield has a short duration (< 30s) it's most
        # likely a refreshing shield (Centi Treasure's 7%/5s pattern).
        # Track continuous absorption rate so damage.resolve can credit
        # the full refresh cycle, not just one-shot value.
        dur = effect.duration_seconds or 0.0
        if 0 < dur < 30.0:
            target.shield_absorption_per_sec += shield_amount / dur
    elif kind is EffectKind.HEAL_PER_SECOND:
        # Most NIKKE heals are %-of-caster-HP per second. The DSL
        # encoders didn't always set scaling_source, but the magnitude
        # is in percent. Treat unscaled heal magnitudes as
        # CASTER_MAX_HP-scaled. Cap at HEAL_RATE_CEILING of caster HP/s
        # to bound damage from inconsistent DSL encodings (some skills
        # mis-encode buff amplifiers like 'HP Potency +13.65%' as
        # HEAL_PER_SECOND with mag=13.65, which would otherwise inflate
        # heal magnitudes by 100×).
        scaled = caster.base_hp * (mag / 100.0)
        capped = min(scaled, caster.base_hp * HEAL_RATE_CEILING)
        dur = effect.duration_seconds or 0.0
        target.heal_per_second = max(target.heal_per_second, capped)
        target.heal_duration = max(target.heal_duration, dur)
        caster.heal_emit_per_second = max(caster.heal_emit_per_second, capped)
        caster.heal_emit_duration = max(caster.heal_emit_duration, dur)
    elif kind is EffectKind.HEAL_HP_FLAT:
        scaled = caster.base_hp * (mag / 100.0)
        capped = min(scaled, caster.base_hp * HEAL_RATE_CEILING)
        target.heal_per_second = max(target.heal_per_second, capped)
        target.heal_duration = max(target.heal_duration, 1.0)
        caster.heal_emit_per_second = max(caster.heal_emit_per_second, capped)
        caster.heal_emit_duration = max(caster.heal_emit_duration, 1.0)
    elif kind is EffectKind.BUFF_PIERCE:
        target.has_pierce = True
    elif kind is EffectKind.TAUNT:
        target.is_taunting = True
    elif kind is EffectKind.DEAL_DAMAGE and target is caster:
        # Burst-skill direct damage — accumulate on the caster so we can
        # report burst payload at the team level.
        target.burst_damage_magnitude += mag
    # GAIN_BURST_GAUGE / REDUCE_BURST_COOLDOWN / DEBUFF_* / DEAL_TRUE_DAMAGE
    # / CLEANSE / INFLICT_BURN — not modeled in the static evaluator.


def _walk_skill_effects(
    skills: list[SkillEffect],
    caster: NikkeSnapshot,
    team: list[NikkeSnapshot],
    burst_user: Optional[NikkeSnapshot],
    *,
    include_triggers: set[TriggerKind] = _SNAPSHOT_TRIGGERS,
) -> None:
    for se in skills:
        if se.trigger.kind not in include_triggers:
            continue
        for eff in se.effects:
            _apply_effect_to_snapshot(eff, caster, team, burst_user)


# Map captured OL gear bonus types to NikkeSnapshot buff fields. PvP
# is 100% hit rate so HIT_RATE / AMMUNITION_CAPACITY are dropped.
_GEAR_BONUS_TYPE_TO_SNAPSHOT_FIELD = {
    "ATK":              "atk_buff_pct",
    "DEFENSE":          "def_buff_pct",
    "ELEMENT_DAMAGE":   "element_damage_buff_pct",
    "CHARGE_DAMAGE":    "charge_damage_buff_pct",
    "CHARGE_SPEED":     "charge_speed_buff_pct",
    "CRITICAL_RATE":    "crit_rate_buff_pct",
    "CRITICAL_DAMAGE":  "crit_damage_buff_pct",
    # HP gear buffs apply multiplicatively to base_hp instead of
    # going into a *_buff_pct field — handled separately in
    # apply_gear_buffs.
}

# Map Doll-effect stat names (from DollSkillPhase.effects[*].stat) to
# NikkeSnapshot buff fields. Effects without a mapped field are dropped
# (e.g. "Max HP of Cover" — we don't model cover mechanics; "Max
# Ammunition Capacity" — PvP irrelevant).
_DOLL_STAT_TO_SNAPSHOT_FIELD = {
    "DEF":                              "def_buff_pct",
    "Charge Damage Multiplier":         "charge_damage_buff_pct",
    "Normal Attack Damage Multiplier":  "attack_damage_buff_pct",
    "Damage dealt when attacking core": "core_damage_buff_pct",
    # "Damage Taken" is a defensive multiplier (attacker side), modeled
    # as an HP equivalent in apply_doll_buffs by dividing damage we
    # absorb (i.e. effectively boosting our HP). Direction-aware.
}


def evaluate_team(
    team_skills: Iterable[CharacterSkillSet],
    *,
    base_atk: int = 100_000,
    base_hp: int = 1_000_000,
    base_def: int = 30_000,
    identities: Optional[dict[str, dict]] = None,
    per_name_stats: Optional[dict[str, dict]] = None,
    per_name_gear_buffs: Optional[dict[str, dict[str, float]]] = None,
    per_name_doll_buffs: Optional[dict[str, dict[str, float]]] = None,
    per_name_treasure_buffs: Optional[dict[str, dict[str, float]]] = None,
) -> TeamEvaluation:
    """Compute the post-burst-chain snapshot for a 5-Nikke team.

    ``base_atk`` / ``base_hp`` / ``base_def`` are global fallback stats
    used when no ``per_name_stats`` entry exists for a member. They're
    sized for a generic mid-game roster so a tests-only invocation
    without DB access still produces reasonable numbers.

    ``identities`` is an optional mapping of ``character_name -> {
    "element": str, "weapon_class": str, "role": str}`` used by Target
    filter narrowing (slice #68). When omitted, filtered effects fall
    back to the un-narrowed behavior — i.e. Water-code-only buffs
    apply to all allies because we don't know who's Water-code.

    ``per_name_stats`` (slice #88) is an optional mapping of
    ``character_name -> {"base_atk": int, "base_hp": int, "base_def":
    int}`` taken from the user's ``OwnedCharacter`` total stats so the
    damage formula reflects each Nikke's actual investment level
    instead of the coarse defaults. Missing entries fall back to the
    global ``base_*`` defaults. Auto-loaded by ``evaluate_by_names``.
    """
    sets = list(team_skills)
    identities = identities or {}
    per_name_stats = per_name_stats or {}
    per_name_gear_buffs = per_name_gear_buffs or {}
    per_name_doll_buffs = per_name_doll_buffs or {}
    per_name_treasure_buffs = per_name_treasure_buffs or {}

    def _stat(name: str, key: str, fallback: int) -> int:
        value = per_name_stats.get(name, {}).get(key)
        if value is None or value <= 0:
            return fallback
        return int(value)

    def _identity(name, key):
        return identities.get(name, {}).get(key)

    team = [
        NikkeSnapshot(
            name=cs.character_name,
            base_atk=_stat(cs.character_name, "base_atk", base_atk),
            base_hp=_stat(cs.character_name, "base_hp", base_hp),
            base_def=_stat(cs.character_name, "base_def", base_def),
            element=(_identity(cs.character_name, "element") or "").lower() or None,
            weapon_class=(_identity(cs.character_name, "weapon_class") or "").lower() or None,
            role=(_identity(cs.character_name, "role") or "").lower() or None,
            burst_position=(_identity(cs.character_name, "burst_position") or "").lower() or None,
            burst_cooldown_sec=float(_identity(cs.character_name, "burst_cooldown_sec") or 20.0),
        )
        for cs in sets
    ]

    # ----- Phase 0: Apply gear % buffs BEFORE DSL effects -----
    # Equipment OL gear has up to 3 % effects per slot (4 slots = up
    # to 12 effects total). These are captured as OLGearBonus rows
    # but never reached the damage formula until 2026-05-09. Apply
    # them now as additive contributions to the same *_buff_pct
    # fields that DSL effects feed into. NIKKE's damage formula
    # treats gear buffs as additive within type then multiplicative
    # across types (per nikke.gg).
    for snap in team:
        gear = per_name_gear_buffs.get(snap.name, {})
        for bonus_type, pct in gear.items():
            field_name = _GEAR_BONUS_TYPE_TO_SNAPSHOT_FIELD.get(bonus_type)
            if field_name is not None:
                setattr(snap, field_name, getattr(snap, field_name) + pct)
            elif bonus_type == "HP":
                # HP % buff applies multiplicatively to base_hp.
                snap.base_hp = int(snap.base_hp * (1.0 + pct / 100.0))
            # HIT_RATE / AMMUNITION_CAPACITY / MAX_AMMUNITION_CAPACITY
            # have no PvP-relevant impact (100% hit rate, mag-clip
            # mechanics ignored in our model).

    # ----- Phase 0c: Apply SSR Treasure parsed-prose effects -----
    # TreasureSkill rows hold per-(char, skill, phase) descriptions that
    # we run through ``treasure_parser.parse_treasure_description`` to
    # extract structured magnitudes. Effects from all rows up to the
    # user's treasure_phase are summed onto the snapshot.
    for snap in team:
        treas = per_name_treasure_buffs.get(snap.name, {})
        for key, val in treas.items():
            if key.endswith("_buff_pct"):
                # Direct stat-buff field — additive.
                if hasattr(snap, key):
                    setattr(snap, key, getattr(snap, key) + val)
            elif key == "shield_pct_caster_hp":
                snap.shield_value += snap.base_hp * (val / 100.0)
            elif key == "heal_pct_caster_hp_per_sec":
                rate = snap.base_hp * (val / 100.0)
                snap.heal_per_second = max(snap.heal_per_second, rate)
                snap.heal_duration = max(snap.heal_duration, 10.0)
                snap.heal_emit_per_second = max(snap.heal_emit_per_second, rate)
                snap.heal_emit_duration = max(snap.heal_emit_duration, 10.0)
            elif key == "max_hp_buff_pct":
                snap.base_hp = int(snap.base_hp * (1.0 + val / 100.0))
            elif key == "damage_taken_reduction_pct":
                if val < 100:
                    snap.base_hp = int(snap.base_hp / (1.0 - val / 100.0))

    # ----- Phase 0b: Apply Doll/Treasure phase effects -----
    # Doll skill effects from DollSkillPhase rows (12 dolls × 15
    # phases × 2 skills = up to 330 distinct phase-effects in DB).
    # Auto-loaded by ``evaluate_by_names`` from each char's equipped
    # doll + treasure_phase. "Damage Taken" effects boost effective
    # HP by reducing incoming damage (1 / (1 - reduction%)).
    for snap in team:
        doll = per_name_doll_buffs.get(snap.name, {})
        for stat, pct in doll.items():
            field_name = _DOLL_STAT_TO_SNAPSHOT_FIELD.get(stat)
            if field_name is not None:
                setattr(snap, field_name, getattr(snap, field_name) + pct)
            elif stat == "Damage Taken":
                # Damage taken reduction → boost effective HP.
                # damage_through = 1 - pct/100 → ehp_multiplier = 1/(1-pct/100)
                if pct >= 100:
                    continue  # invalid
                ehp_mult = 1.0 / (1.0 - pct / 100.0)
                snap.base_hp = int(snap.base_hp * ehp_mult)

    # ----- Phase 1: ALWAYS + ON_BATTLE_START (once per Nikke) -----
    # Persistent passives (Pierce, base buff stacks, on-battle-start
    # state machines like Red Hood's Charge-Speed conversion).
    for cs, snap in zip(sets, team):
        _walk_skill_effects(
            list(cs.skill1) + list(cs.skill2) + list(cs.burst_skill),
            caster=snap, team=team, burst_user=None,
            include_triggers={TriggerKind.ALWAYS, TriggerKind.ON_BATTLE_START},
        )

    # ----- Phase 2: ON_FULL_BURST_START (fires ONCE per team) -----
    # Full Burst is a single window per match — each Nikke's
    # skill1/2/burst-skill effects under this trigger fire exactly
    # once, on themselves as caster.
    for cs, snap in zip(sets, team):
        _walk_skill_effects(
            list(cs.skill1) + list(cs.skill2) + list(cs.burst_skill),
            caster=snap, team=team, burst_user=None,
            include_triggers={TriggerKind.ON_FULL_BURST_START},
        )

    # ----- Phase 3: Burst chain (5 burst events) -----
    # Each Nikke takes their burst slot in turn. Per burst event:
    #   * The burst user's burst-skill ON_BURST_USE effects fire once.
    #   * The burst user's skill1/2 ON_BURST_USE effects fire once.
    #   * Every ally's (including burst user) skill1/2
    #     ON_ALLY_BURST_USE effects fire once, targeting the burst user.
    # This produces 5 burst events, 5 own-burst-skill firings,
    # 5 own-skill1/2 ON_BURST_USE firings, and 25 ally-skill1/2
    # ON_ALLY_BURST_USE firings (5 allies × 5 burst events) — the
    # latter is correct because Crown's S2 stacks up to 3 across
    # successive ally bursts.
    for cs, snap in zip(sets, team):
        burst_user = snap
        # 3a. Burst user's own burst-skill effects fire.
        _walk_skill_effects(
            list(cs.burst_skill), caster=snap, team=team, burst_user=burst_user,
            include_triggers={TriggerKind.ON_BURST_USE},
        )
        # 3b. Burst user's own skill1/2 ON_BURST_USE effects.
        _walk_skill_effects(
            list(cs.skill1) + list(cs.skill2),
            caster=snap, team=team, burst_user=burst_user,
            include_triggers={TriggerKind.ON_BURST_USE},
        )
        # 3c. Every ally's skill1/2 ON_ALLY_BURST_USE effects.
        for cs_other, snap_other in zip(sets, team):
            _walk_skill_effects(
                list(cs_other.skill1) + list(cs_other.skill2),
                caster=snap_other, team=team, burst_user=burst_user,
                include_triggers={TriggerKind.ON_ALLY_BURST_USE},
            )

    # ----- Phase 4: ON_FULL_BURST_END (fires ONCE per team) -----
    # After the burst window closes, post-burst effects fire. Trina's
    # S1 (team heal 4.06%/s for 5s) and similar stall-comp staples land
    # here. Treated as fire-once per match (the snapshot doesn't model
    # multi-cycle bursts).
    for cs, snap in zip(sets, team):
        _walk_skill_effects(
            list(cs.skill1) + list(cs.skill2) + list(cs.burst_skill),
            caster=snap, team=team, burst_user=None,
            include_triggers={TriggerKind.ON_FULL_BURST_END},
        )

    return TeamEvaluation(members=team)


def evaluate_by_names(
    names: Iterable[str],
    **kwargs,
) -> Optional[TeamEvaluation]:
    """Convenience: look up each name in the registry and evaluate.

    Returns ``None`` if any name isn't encoded — the caller can then
    decide to skip that team (the optimizer's static-evaluator scoring
    component should fall back to heuristics in that case).

    Slice #68: when the DB is available, ``identities`` (element /
    weapon / role per Nikke) are auto-loaded so element/weapon/role
    filter narrowing in target resolution actually fires. Falls back
    to no-identity behavior if the DB lookup fails (tests that don't
    have a DB get the un-narrowed behavior — same as before).

    Slice #88: ``per_name_stats`` are also auto-loaded — each owned
    Nikke's ``OwnedCharacter.total_atk/total_hp/total_def`` flow into
    the damage formula so win-margin numbers reflect real investment.
    Unowned characters or missing stat columns fall through to the
    global defaults (avoids degenerate "100k ATK vaporizes 1M HP" cases
    that produced "predicted clear in 1s, +299s" verdicts pre-slice).
    """
    name_list = list(names)
    # Slice #134 — when the user has a Treasure unlocked for a
    # character, route to the ``<name> (Treasure)`` library entry if
    # one exists. The flag comes from OwnedCharacter.treasure_rarity
    # ("SSR" + phase ≥ 1 means Treasure equipped). Falls through to
    # the base form when DB lookup fails or no Treasure entry exists.
    routed_names = _route_treasure_forms(name_list)
    sets: list[CharacterSkillSet] = []
    for name in routed_names:
        cs = registry_get(name)
        if cs is None:
            return None
        sets.append(cs)
    # Auto-load identities + stats from the DB by ORIGINAL name (the
    # user's roster row keys on the base name, not the Treasure form).
    # Re-key the dicts under the ROUTED name so ``evaluate_team`` can
    # find them when assembling the team — otherwise Treasure-routed
    # members fall back to default stats and the damage formula
    # severely underestimates them.
    if "identities" not in kwargs:
        base_identities = _load_identities(name_list)
        kwargs["identities"] = {
            routed: base_identities[base]
            for base, routed in zip(name_list, routed_names)
            if base in base_identities
        }
    if "per_name_stats" not in kwargs:
        base_stats = _load_owned_stats(name_list)
        kwargs["per_name_stats"] = {
            routed: base_stats[base]
            for base, routed in zip(name_list, routed_names)
            if base in base_stats
        }
    if "per_name_gear_buffs" not in kwargs:
        base_gear = _load_owned_gear_buffs(name_list)
        kwargs["per_name_gear_buffs"] = {
            routed: base_gear[base]
            for base, routed in zip(name_list, routed_names)
            if base in base_gear
        }
    if "per_name_doll_buffs" not in kwargs:
        base_dolls = _load_owned_doll_buffs(name_list)
        kwargs["per_name_doll_buffs"] = {
            routed: base_dolls[base]
            for base, routed in zip(name_list, routed_names)
            if base in base_dolls
        }
    if "per_name_treasure_buffs" not in kwargs:
        # Treasure lookups are keyed by ROUTED name (the simulator-side
        # "(Treasure)" character row holds the TreasureSkill rows), but
        # we read treasure_phase from the BASE name's OwnedCharacter row.
        kwargs["per_name_treasure_buffs"] = _load_owned_treasure_buffs(
            base_names=name_list, routed_names=routed_names,
        )
    return evaluate_team(sets, **kwargs)


def _load_owned_treasure_buffs(
    base_names: list[str], routed_names: list[str]
) -> dict[str, dict[str, float]]:
    """Load + parse Treasure (SSR Favorite) skill effects per character.

    Returns ``{routed_name: {effect_key: magnitude, ...}}`` where keys
    match what ``parse_treasure_description`` emits (atk_buff_pct,
    shield_pct_caster_hp, etc.).

    Sums effects from all TreasureSkill rows where ``upgrade_phase <=
    user's treasure_phase`` — this models the in-game reality that
    each phase unlocks a new skill upgrade incrementally.
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.models import (
            Character, OwnedCharacter, TreasureSkill,
        )
        from .treasure_parser import parse_treasure_description
        from sqlmodel import select

        engine = make_engine(default_db_path())
        out: dict[str, dict[str, float]] = {}
        with get_session(engine) as session:
            for base_name, routed_name in zip(base_names, routed_names):
                # Treasure routing only applied for chars where user
                # has Treasure unlocked (rarity SSR + phase >= 1).
                if routed_name == base_name:
                    continue  # not a Treasure-routed char
                # Pull user's treasure_phase from base-name row.
                row = session.exec(
                    select(OwnedCharacter, Character)
                    .where(OwnedCharacter.character_id == Character.id)
                    .where(Character.name == base_name)
                ).one_or_none()
                if row is None:
                    continue
                owned, _ = row
                user_phase = owned.treasure_phase or 0
                if user_phase <= 0:
                    continue
                # TreasureSkill rows are keyed by the routed character.
                treasure_char = session.exec(
                    select(Character).where(Character.name == routed_name)
                ).one_or_none()
                if treasure_char is None:
                    continue
                ts_rows = session.exec(
                    select(TreasureSkill)
                    .where(TreasureSkill.character_id == treasure_char.id)
                    .where(TreasureSkill.upgrade_phase <= user_phase)
                ).all()
                buffs: dict[str, float] = {}
                for ts in ts_rows:
                    parsed = parse_treasure_description(
                        ts.description_treasured or ""
                    )
                    for k, v in parsed.items():
                        buffs[k] = buffs.get(k, 0.0) + v
                if buffs:
                    out[routed_name] = buffs
        return out
    except Exception:
        return {}


def _load_owned_doll_buffs(names: list[str]) -> dict[str, dict[str, float]]:
    """Look up each character's equipped Doll + phase, sum effects.

    Returns ``{character_name: {"DEF": 37.0, "Damage Taken": 12.0, ...}}``.
    Looks up Doll by ``treasure_name`` (the user's equipped doll) and
    pulls effects at ``treasure_phase`` from DollSkillPhase. Returns
    empty for characters where no doll is equipped or rarity != "SR"
    (SSR rarity = Treasure, handled separately when wired).
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.models import (
            Character, OwnedCharacter, Doll, DollSkill, DollSkillPhase,
        )
        from sqlmodel import select
        engine = make_engine(default_db_path())
        out: dict[str, dict[str, float]] = {}
        with get_session(engine) as session:
            for name in names:
                row = session.exec(
                    select(OwnedCharacter, Character)
                    .where(OwnedCharacter.character_id == Character.id)
                    .where(Character.name == name)
                ).one_or_none()
                if row is None:
                    continue
                owned, _ = row
                # Only SR Dolls handled here; SSR Treasures need their
                # own loader (skill descriptions, not structured data).
                if (owned.treasure_rarity or "").upper() != "SR":
                    continue
                if not owned.treasure_name or not owned.treasure_phase:
                    continue
                doll = session.exec(
                    select(Doll).where(Doll.name == owned.treasure_name)
                ).one_or_none()
                if doll is None:
                    continue
                buffs: dict[str, float] = {}
                skills = session.exec(
                    select(DollSkill).where(DollSkill.doll_id == doll.id)
                ).all()
                for sk in skills:
                    phase_row = session.exec(
                        select(DollSkillPhase)
                        .where(DollSkillPhase.skill_id == sk.id)
                        .where(DollSkillPhase.phase == owned.treasure_phase)
                    ).one_or_none()
                    if phase_row is None:
                        continue
                    for eff in phase_row.effects or []:
                        stat = eff.get("stat")
                        mag = eff.get("magnitude")
                        if stat and mag is not None:
                            buffs[stat] = buffs.get(stat, 0.0) + float(mag)
                if buffs:
                    out[name] = buffs
        return out
    except Exception:
        return {}


def _load_owned_gear_buffs(names: list[str]) -> dict[str, dict[str, float]]:
    """Sum each character's OL gear bonus % per OLBonusType.

    Returns ``{character_name: {"ATK": 45.14, "ELEMENT_DAMAGE": 113.84, ...}}``.
    Only ``highlighted=True`` bonuses are counted (active vs grayed).
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.models import Character, OwnedCharacter, OLGear, OLGearBonus
        from sqlmodel import select
        engine = make_engine(default_db_path())
        out: dict[str, dict[str, float]] = {}
        with get_session(engine) as session:
            for name in names:
                row = session.exec(
                    select(OwnedCharacter, Character)
                    .where(OwnedCharacter.character_id == Character.id)
                    .where(Character.name == name)
                ).one_or_none()
                if row is None:
                    continue
                owned, _ = row
                buffs: dict[str, float] = {}
                for gear in owned.ol_gear or []:
                    for bonus in gear.bonuses or []:
                        if not bonus.highlighted:
                            continue
                        if bonus.bonus_type is None or bonus.percent is None:
                            continue
                        # bonus.bonus_type is OLBonusType enum; use its
                        # name (e.g. "ATK", "ELEMENT_DAMAGE") as the key.
                        key = bonus.bonus_type.name
                        buffs[key] = buffs.get(key, 0.0) + bonus.percent
                if buffs:
                    out[name] = buffs
        return out
    except Exception:
        return {}


def _route_treasure_forms(names: list[str]) -> list[str]:
    """Substitute ``<name> (Treasure)`` for chars where the user has
    the Treasure unlocked AND the registry has a Treasure-form entry.

    Slice #134 — without this, evaluate_by_names always uses the base
    form even when the user has unlocked the Treasure (which materially
    boosts the character's stats and skill effects). Falls back to the
    original list when DB unavailable.
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.models import Character, OwnedCharacter
        from sqlmodel import select
        from .registry import all_encoded_names

        engine = make_engine(default_db_path())
        encoded = set(all_encoded_names())
        out: list[str] = []
        with get_session(engine) as session:
            for name in names:
                row = session.exec(
                    select(OwnedCharacter, Character)
                    .where(OwnedCharacter.character_id == Character.id)
                    .where(Character.name == name)
                ).one_or_none()
                if row is None:
                    out.append(name)
                    continue
                owned, _ = row
                rarity = (owned.treasure_rarity or "").upper()
                phase = owned.treasure_phase or 0
                treasure_form = f"{name} (Treasure)"
                if rarity == "SSR" and phase >= 1 and treasure_form in encoded:
                    out.append(treasure_form)
                else:
                    out.append(name)
        return out
    except Exception:
        return list(names)


def _load_identities(names: list[str]) -> dict[str, dict]:
    """Look up each character's element/weapon_class/role/burst from the DB.

    Returns a mapping ``name -> {"element", "weapon_class", "role",
    "burst_position", "burst_cooldown_sec"}`` for use by
    ``evaluate_team``'s identity threading. Empty dict on any failure
    (tests without DB still pass).

    ``burst_position`` is "1"/"2"/"3"/"flex" matching CharacterView's
    convention. ``burst_cooldown_sec`` is from the user's
    OwnedCharacter row when available, defaulting to 20s.
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.enums import BurstType
        from ..data.models import Character, OwnedCharacter
        from sqlmodel import select
        engine = make_engine(default_db_path())
        out: dict[str, dict] = {}
        burst_pos_map = {
            BurstType.I: "1", BurstType.II: "2", BurstType.III: "3",
            BurstType.FLEX: "flex",
        }
        with get_session(engine) as session:
            for name in names:
                ch = session.exec(
                    select(Character).where(Character.name == name)
                ).one_or_none()
                if ch is None:
                    continue
                role = ""
                if ch.role_tags:
                    role = ch.role_tags[0] if ch.role_tags else ""
                # Burst cooldown — prefer the per-character lookup
                # table (BitTopup-sourced 20/40/60s values) over the
                # OwnedCharacter row, since the latter is rarely
                # populated. Falls back to 40s for B3 / 20s for
                # B1/B2/flex when a Nikke isn't in the table.
                from .burst_cooldowns import get_burst_cooldown
                burst_pos_str = burst_pos_map.get(ch.burst_type, "flex") if ch.burst_type else "flex"
                cd = get_burst_cooldown(name, burst_pos_str)
                out[name] = {
                    "element": ch.element.value if ch.element else "",
                    "weapon_class": ch.weapon_class.value if ch.weapon_class else "",
                    "role": role,
                    "burst_position": burst_pos_str,
                    "burst_cooldown_sec": cd,
                }
        return out
    except Exception:
        return {}


def _load_owned_stats(names: list[str]) -> dict[str, dict]:
    """Look up each owned Nikke's total ATK/HP/DEF from ``OwnedCharacter``.

    Returns a mapping ``name -> {"base_atk": int, "base_hp": int,
    "base_def": int}`` for use by ``evaluate_team``'s stat threading.
    Skips unowned characters and any whose stat columns are still
    None/0 (e.g., never imported, partial CSV row). Empty dict on any
    DB failure — the simulator falls back to its hardcoded defaults so
    tests without a DB keep passing.
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.models import Character, OwnedCharacter
        from sqlmodel import select
        engine = make_engine(default_db_path())
        out: dict[str, dict] = {}
        with get_session(engine) as session:
            for name in names:
                row = session.exec(
                    select(OwnedCharacter, Character)
                    .where(OwnedCharacter.character_id == Character.id)
                    .where(Character.name == name)
                ).one_or_none()
                if row is None:
                    continue
                owned, _char = row
                stats: dict[str, int] = {}
                if owned.total_atk and owned.total_atk > 0:
                    stats["base_atk"] = int(owned.total_atk)
                if owned.total_hp and owned.total_hp > 0:
                    stats["base_hp"] = int(owned.total_hp)
                if owned.total_def and owned.total_def > 0:
                    stats["base_def"] = int(owned.total_def)
                if stats:
                    out[name] = stats
        return out
    except Exception:
        return {}
