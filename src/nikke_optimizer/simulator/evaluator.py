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

    burst_damage_magnitude: float = 0.0  # sum of burst-skill DEAL_DAMAGE × ATK
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
    if (
        effect.kind in (EffectKind.DEAL_DAMAGE, EffectKind.DEAL_TRUE_DAMAGE)
        and effect.target.kind in _ENEMY_TARGET_KINDS
    ):
        caster.burst_damage_magnitude += effect.magnitude

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
        # Unhandled scaling+kind combo — fall through to literal % below
        # so the value isn't silently dropped.

    if kind is EffectKind.BUFF_ATK:
        target.atk_buff_pct += mag
    elif kind is EffectKind.BUFF_DEFENSE:
        target.def_buff_pct += mag
    elif kind is EffectKind.BUFF_HP:
        target.base_hp = int(target.base_hp * (1.0 + mag / 100.0))
    elif kind is EffectKind.BUFF_CRIT_RATE:
        target.crit_rate_buff_pct += mag
    elif kind is EffectKind.BUFF_CRIT_DAMAGE:
        target.crit_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_CHARGE_DAMAGE:
        target.charge_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_CHARGE_SPEED:
        target.charge_speed_buff_pct += mag
    elif kind is EffectKind.BUFF_ELEMENT_DAMAGE:
        target.element_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_ATTACK_DAMAGE:
        target.attack_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_TRUE_DAMAGE:
        target.true_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_PIERCE_DAMAGE:
        target.pierce_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_SHIELD_DAMAGE:
        target.shield_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_CORE_DAMAGE:
        target.core_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_DAMAGE_TO_PARTS:
        target.parts_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_SUSTAINED_DAMAGE:
        target.sustained_damage_buff_pct += mag
    elif kind is EffectKind.BUFF_BURST_SKILL_DAMAGE:
        target.burst_skill_damage_buff_pct += mag
    elif kind is EffectKind.GRANT_SHIELD:
        # Magnitude is % of caster's max HP — caster's HP, not target's.
        target.shield_value += caster.base_hp * (mag / 100.0)
    elif kind is EffectKind.HEAL_PER_SECOND:
        target.heal_per_second = max(target.heal_per_second, mag)
        target.heal_duration = max(target.heal_duration, effect.duration_seconds or 0.0)
    elif kind is EffectKind.HEAL_HP_FLAT:
        # One-time heal — modeled as a heal-per-second pulse with 1s
        # duration so it shows in the sustain index.
        target.heal_per_second = max(target.heal_per_second, mag)
        target.heal_duration = max(target.heal_duration, 1.0)
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


def evaluate_team(
    team_skills: Iterable[CharacterSkillSet],
    *,
    base_atk: int = 100_000,
    base_hp: int = 1_000_000,
    base_def: int = 30_000,
    identities: Optional[dict[str, dict]] = None,
    per_name_stats: Optional[dict[str, dict]] = None,
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

    def _stat(name: str, key: str, fallback: int) -> int:
        value = per_name_stats.get(name, {}).get(key)
        if value is None or value <= 0:
            return fallback
        return int(value)

    team = [
        NikkeSnapshot(
            name=cs.character_name,
            base_atk=_stat(cs.character_name, "base_atk", base_atk),
            base_hp=_stat(cs.character_name, "base_hp", base_hp),
            base_def=_stat(cs.character_name, "base_def", base_def),
            element=(identities.get(cs.character_name, {}).get("element") or "").lower() or None,
            weapon_class=(identities.get(cs.character_name, {}).get("weapon_class") or "").lower() or None,
            role=(identities.get(cs.character_name, {}).get("role") or "").lower() or None,
        )
        for cs in sets
    ]

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
    return evaluate_team(sets, **kwargs)


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
    """Look up each character's element/weapon_class/role from the DB.

    Returns a mapping ``name -> {"element": str, "weapon_class": str,
    "role": str}`` for use by ``evaluate_team``'s identity threading.
    Empty dict on any failure (tests without DB still pass).
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.models import Character
        from sqlmodel import select
        engine = make_engine(default_db_path())
        out: dict[str, dict] = {}
        with get_session(engine) as session:
            for name in names:
                ch = session.exec(
                    select(Character).where(Character.name == name)
                ).one_or_none()
                if ch is None:
                    continue
                role = ""
                if ch.role_tags:
                    # role_tags[0] is the primary class per the scraper
                    role = ch.role_tags[0] if ch.role_tags else ""
                out[name] = {
                    "element": ch.element.value if ch.element else "",
                    "weapon_class": ch.weapon_class.value if ch.weapon_class else "",
                    "role": role,
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
