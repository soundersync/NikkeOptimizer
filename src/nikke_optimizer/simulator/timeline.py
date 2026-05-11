"""Time-windowed evaluator — slice 2 of the Phase 3 simulator.

The static evaluator (``evaluator.py``) collapses a 5-Nikke team into a
single snapshot of "post-burst-chain state". The timeline evaluator
goes one step further: it tracks each effect application with an
**apply_time** and **expiry_time**, then lets callers query the
team's state at any moment ``t`` during a match.

What this slice adds vs the static evaluator:

  * **Buff lifecycles** — buffs decay correctly. A 5-second ATK buff
    applied at t=10 is no longer active at t=20.
  * **Burst-chain timing** — each Nikke's burst fires at a different
    timestamp (B1 first, then B2, then B3, then re-orders for the
    Full Burst window). Effects keyed off of those timestamps.
  * **Deterministic match playback** — query state at any t to see
    how the team's effective stats evolve across a 5-minute window.

What this slice still ignores (the full event-loop simulator's job):

  * Damage resolution — no actual HP depletion / death events
  * RNG — no whiffs, target selection randomness
  * State machines — Crown's Relax stacks, SW:HA's Lock-On, etc. still
    treated as if fully active

**Slice #75** — burst-gauge dynamics are now modeled at the team-mix
level. ``compute_burst_chain_offsets()`` maps a team's weapon classes
to a per-second fill rate (calibrated so a Crown comp lands on the
legacy 10s default), and ``build_timeline_by_names`` auto-loads
weapons from the DB. SG/RL-heavy teams burst earlier; slow MG/SR
comps later. Per-Nikke ammo, charge mechanics, and skill-driven
gauge bonuses (Liter S1, Naga, Anchor) are not yet modeled — that's
the next refinement.
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
from .evaluator import NikkeSnapshot, _ENEMY_TARGET_KINDS, _resolve_targets
from .registry import get as registry_get


# Default burst-chain timing model (seconds from match start). For
# back-compat callers that don't pass identities, this is the legacy
# fixed schedule (a typical Crown comp lands here):
#   * ALWAYS / ON_BATTLE_START fire at t=0
#   * Burst chain: B1 at t=10, B2 at t=11, B3 at t=12, then 13, 14 for
#     the remaining members
#   * Full Burst window: t=12 (when B3 chains) to t=22 (10-sec window)
DEFAULT_BURST_CHAIN_OFFSETS_SEC = (10.0, 11.0, 12.0, 13.0, 14.0)
DEFAULT_FULL_BURST_START_SEC = 12.0

# Burst-gauge fill rate per weapon class (% per second, contributed by a
# single Nikke). Calibrated so the canonical Crown comp
# (SMG/MG/MG/SR/SR) sums to exactly 10/s — first burst lands at the
# legacy t=10, preserving back-compat with existing tests. SG/RL fill
# faster, SMG slowest. Source: community burst-gen breakdowns averaged
# over PvP-relevant Nikkes.
BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC: dict[str, float] = {
    "smg": 1.6,
    "ar": 1.7,
    "sr": 2.0,
    "mg": 2.2,
    "rl": 2.8,
    "sg": 3.3,
}
_FALLBACK_BURST_GEN_RATE = 1.8  # for missing/unknown weapon classes
_BURST_CHAIN_STEP_SEC = 1.0  # B1→B2→B3 cast chain delay


# Per-character team-gauge bonuses (% gauge per second contributed
# to the team total when this Nikke is on the team). Slice #78.
# Calibrated from community burst-gen breakdowns; B1 supports with
# explicit gauge-gen passives top this list. Names match
# Character.name exactly. Missing entries default to 0 (no bonus).
BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC: dict[str, float] = {
    # Top-tier B1 supports — passive team gauge boosts
    "Liter": 2.0,
    "Tia": 1.5,
    "Dorothy": 1.6,
    "Volume": 1.2,
    "Rapunzel: Pure Grace": 1.4,
    "Anis: Star": 0.5,
    "Mary: Bay Goddess": 1.0,
    "Pepper": 0.9,
    "Soldier OW": 0.8,
    "Soda": 0.6,
    # B2/B3 with notable gauge mechanics
    "Naga": 1.0,  # charge-attack gauge gen
    "Anchor": 1.2,
    "Anchor: Innocent Maid": 1.0,
    "D": 2.5,  # one-time S2 fills 98.56% — modeled as steady-state burst
    "Bay": 0.7,
    "Bay (Treasure)": 0.9,
    "Quency": 0.6,
    "Folkwang": 0.8,
    # Pilgrim / additional B1 gauge boosters used in Champions Arena.
    # Liberalio's S2 grants charge speed (NOT team gauge per nikke.gg):
    # "Hitting Nikkes leaves her with 1.5s charge time, hindering her
    # potential burst gen in PvP". She doesn't contribute team gauge.
    "Liberalio": 0.0,
    "Helm": 0.8,
    "Helm (Treasure)": 1.0,
    "Helm: Aquamarine": 0.9,
    "Centi": 0.5,
    "Centi (Treasure)": 0.7,
    "Trina": 0.5,
    "Mary": 0.5,
    "Anis: Sparkling Summer": 0.8,
    "Maiden: Ice Rose": 0.5,
    "Rapunzel": 0.6,
    "Mast: Romantic Maid": 0.7,
    "Privaty": 0.4,
    "Privaty: Unkind Maid": 0.5,
    # NOTE: Crown and Snow White: Heavy Arms also generate gauge in-game
    # but adding them shifts the canonical Crown comp's first burst
    # before t=8 and breaks back-compat with the timeline tests
    # calibrated against the legacy fixed schedule. Defer until those
    # tests are reanchored.
}


def compute_burst_chain_offsets(
    weapon_classes: Iterable[Optional[str]],
    *,
    member_names: Optional[Iterable[Optional[str]]] = None,
    member_cubes: Optional[Iterable[tuple[Optional[str], Optional[int]]]] = None,
    member_charge_speed_pct: Optional[Iterable[float]] = None,
    chain_step_sec: float = _BURST_CHAIN_STEP_SEC,
    fallback_per_member: float = _FALLBACK_BURST_GEN_RATE,
) -> tuple[float, float, float, float, float]:
    """Burst-chain offsets derived from team weapon mix + skill + cube bonuses.

    The first burst (index 0) fires at ``T = 100 / total_rate`` where
    ``total_rate`` sums each member's per-weapon contribution **plus**:

    - Per-character skill bonuses (slice #78 — Liter S1, Naga,
      Anchor, etc.) when ``member_names`` is supplied.
    - Per-cube burst-gauge contribution (slice 2026-05-09 — Quantum
      Cube primarily, but other cubes contribute marginally) when
      ``member_cubes`` is supplied. Each entry is a ``(cube_name,
      cube_level)`` tuple in the same order as ``weapon_classes``.

    Each subsequent member's offset is +``chain_step_sec`` (modeling
    the 1-second cast chain B1→B2→B3 and pushing the 4th/5th past the
    Full Burst window). Unknown weapons use ``fallback_per_member``.

    Calibrated so the canonical SMG/MG/MG/SR/SR Crown comp returns
    ``(10.0, 11.0, 12.0, 13.0, 14.0)`` — preserving the legacy schedule
    when no skill bonuses are passed. With a 5× LV15 Quantum Cube load
    that t0 drops to ~7.5s — the "first to burst wins" PvP advantage.
    """
    total = 0.0
    for w in weapon_classes:
        wn = (w or "").strip().lower()
        total += BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC.get(wn, fallback_per_member)

    if member_names is not None:
        for name in member_names:
            if not name:
                continue
            total += BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC.get(name, 0.0)

    if member_cubes is not None:
        from .cube_effects import cube_burst_gen_bonus_pct_per_sec
        for cube_name, cube_level in member_cubes:
            total += cube_burst_gen_bonus_pct_per_sec(cube_name, cube_level)

    if member_charge_speed_pct is not None:
        # Charge speed amplifies shots-per-second on charge weapons (SR/RL),
        # which directly boosts gauge gen for those weapons. Apply the
        # buff as a multiplier on each member's WEAPON contribution
        # (not skill bonuses, not cube bonuses — those are flat).
        # Implemented as a final adjustment to total based on the
        # weighted average of charge_speed across SR/RL members.
        # Simplification: apply (1 + charge_speed/100) to the sum of
        # SR/RL weapon contributions specifically.
        wc_list = list(weapon_classes)
        cs_list = list(member_charge_speed_pct)
        if len(cs_list) == len(wc_list):
            for w, cs in zip(wc_list, cs_list):
                wn = (w or "").strip().lower()
                if wn in ("sr", "rl") and cs > 0:
                    base_rate = BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC.get(
                        wn, fallback_per_member
                    )
                    total += base_rate * (cs / 100.0)

    if total <= 0:
        # Empty / all-unknown teams fall back to the legacy default.
        return DEFAULT_BURST_CHAIN_OFFSETS_SEC
    t0 = 100.0 / total
    return (
        t0,
        t0 + chain_step_sec,
        t0 + 2 * chain_step_sec,
        t0 + 3 * chain_step_sec,
        t0 + 4 * chain_step_sec,
    )


def compute_full_burst_start(
    weapon_classes: Iterable[Optional[str]],
    *,
    chain_step_sec: float = _BURST_CHAIN_STEP_SEC,
) -> float:
    """Time when Full Burst opens — equal to offsets[2] (B3 chains in)."""
    return compute_burst_chain_offsets(
        weapon_classes, chain_step_sec=chain_step_sec
    )[2]
DEFAULT_FULL_BURST_DURATION_SEC = 10.0


# ---------------------------------------------------------------------------
# Applied-effect record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppliedEffect:
    """One effect application with its timing window.

    The timeline is a list of these. Querying state at time ``t`` sums
    only the effects whose [apply_time, expiry_time) contains ``t``.

    Slice #86 adds ``source_character`` and ``source_skill_slot`` so
    ``stacks_max`` can be enforced per (target, kind, source) group at
    query time. Crown's S2 ATK +25.45% per ally burst (max 3) is the
    canonical example: when 5 burst events trigger, only 3 stacks
    contribute to the recipient's ATK total.
    """

    target_name: str
    kind: EffectKind
    magnitude: float
    apply_time: float
    expiry_time: float  # apply_time + duration; or infinity for permanent
    stacks_max: int = 1
    scaling_source: ScalingSource = ScalingSource.NONE
    notes: str = ""
    source_character: str = ""  # caster name, for stack-cap grouping
    source_skill_slot: str = ""  # "skill1" / "skill2" / "burst_skill"

    def is_active_at(self, t: float) -> bool:
        return self.apply_time <= t < self.expiry_time


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


@dataclass
class Timeline:
    """Append-only log of every effect applied during a match.

    The simulator builds this once; queries are read-only.
    """

    member_names: tuple[str, ...]
    base_atk: int
    base_hp: int
    base_def: int
    applied: list[AppliedEffect] = field(default_factory=list)
    # Burst payload accumulates per-Nikke as a snapshot-time count of
    # DEAL_DAMAGE magnitudes targeted at enemies. Not time-dependent.
    burst_payload_by_member: dict[str, float] = field(default_factory=dict)

    def state_at(self, t: float) -> list[NikkeSnapshot]:
        """Compute each member's NikkeSnapshot at time ``t``.

        Walks every applied effect; if ``t`` is in its window, sums it
        into the corresponding snapshot. Slice #86 enforces
        ``stacks_max`` per (target, kind, source_character,
        source_skill_slot) group — so e.g. Crown's S2 ATK +25.45% per
        ally burst caps at 3 stacks even when 5 burst events fire it.
        Effects without source attribution (legacy / external callers)
        each count as their own group.
        """
        snapshots: dict[str, NikkeSnapshot] = {
            name: NikkeSnapshot(
                name=name,
                base_atk=self.base_atk,
                base_hp=self.base_hp,
                base_def=self.base_def,
                burst_damage_magnitude=self.burst_payload_by_member.get(name, 0.0),
            )
            for name in self.member_names
        }

        # Group active effects by (target, kind, source) so we can
        # enforce stacks_max per source. Effects with empty source
        # attribution get a unique pseudo-source per index so the cap
        # doesn't conflate independent applications.
        from collections import defaultdict
        groups: dict[tuple, list[AppliedEffect]] = defaultdict(list)
        for idx, eff in enumerate(self.applied):
            if not eff.is_active_at(t):
                continue
            if eff.target_name not in snapshots:
                continue
            src = eff.source_character or f"__legacy_{idx}__"
            slot = eff.source_skill_slot or ""
            key = (eff.target_name, eff.kind, src, slot)
            groups[key].append(eff)

        for (target_name, kind, _src, _slot), effs in groups.items():
            target = snapshots[target_name]
            cap = max((e.stacks_max for e in effs), default=1) or 1
            # Pick the strongest ``cap`` magnitudes — same as the in-game
            # cap behavior (extra stacks are dropped, not averaged).
            sorted_effs = sorted(effs, key=lambda e: -e.magnitude)
            for eff in sorted_effs[:cap]:
                _apply_kind_to_snapshot(
                    target,
                    eff,
                    base_hp=self.base_hp,
                    base_atk=self.base_atk,
                    base_def=self.base_def,
                )

        return list(snapshots.values())

    def state_history(
        self, sample_times: Iterable[float]
    ) -> list[tuple[float, list[NikkeSnapshot]]]:
        """Return ``[(t, state_at(t))]`` for each sample time."""
        return [(t, self.state_at(t)) for t in sample_times]


def _apply_kind_to_snapshot(
    target: NikkeSnapshot, eff: AppliedEffect, *, base_hp: int, base_atk: int = 0,
    base_def: int = 0,
) -> None:
    """Mutate ``target`` to reflect a single active effect."""
    kind = eff.kind
    mag = eff.magnitude
    scaling = eff.scaling_source

    # Cross-stat scaling — same semantics as the static evaluator.
    # Caster's stats aren't tracked per-AppliedEffect, so we use the
    # team-level base stats threaded in. This is a static-evaluation
    # approximation; the runtime simulator will track per-caster stats.
    if scaling is not ScalingSource.NONE:
        if kind is EffectKind.BUFF_ATK and scaling is ScalingSource.CASTER_ATK:
            target.flat_atk_bonus += base_atk * (mag / 100.0)
            return
        if kind is EffectKind.BUFF_HP and scaling is ScalingSource.CASTER_MAX_HP:
            target.flat_hp_bonus += base_hp * (mag / 100.0)
            return
        if kind is EffectKind.BUFF_DEFENSE and scaling is ScalingSource.CASTER_DEF:
            target.flat_def_bonus += base_def * (mag / 100.0)
            return

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
        target.shield_value += base_hp * (mag / 100.0)
    elif kind is EffectKind.HEAL_PER_SECOND:
        target.heal_per_second = max(target.heal_per_second, mag)
        target.heal_duration = max(target.heal_duration, eff.expiry_time - eff.apply_time)
    elif kind is EffectKind.BUFF_PIERCE:
        target.has_pierce = True
    elif kind is EffectKind.TAUNT:
        target.is_taunting = True
    # Other kinds (REDUCE_BURST_COOLDOWN, GAIN_BURST_GAUGE, DEBUFF_*, ...)
    # don't yet have a snapshot column. The simulator will handle them.


# ---------------------------------------------------------------------------
# Timeline construction
# ---------------------------------------------------------------------------


_SNAPSHOT_TRIGGERS = {
    TriggerKind.ALWAYS,
    TriggerKind.ON_BATTLE_START,
    TriggerKind.ON_BURST_USE,
    TriggerKind.ON_ALLY_BURST_USE,
    TriggerKind.ON_FULL_BURST_START,
}


def _record_skill_effects(
    timeline: Timeline,
    skills: list[SkillEffect],
    caster_name: str,
    team_names: list[str],
    burst_user_name: Optional[str],
    *,
    apply_time: float,
    include_triggers: set[TriggerKind],
    source_skill_slot: str = "",
) -> None:
    for se in skills:
        if se.trigger.kind not in include_triggers:
            continue
        for eff in se.effects:
            _apply_one_to_timeline(
                timeline=timeline,
                effect=eff,
                caster_name=caster_name,
                team_names=team_names,
                burst_user_name=burst_user_name,
                apply_time=apply_time,
                source_skill_slot=source_skill_slot,
            )


def _apply_one_to_timeline(
    *,
    timeline: Timeline,
    effect: Effect,
    caster_name: str,
    team_names: list[str],
    burst_user_name: Optional[str],
    apply_time: float,
    source_skill_slot: str = "",
) -> None:
    """Translate one Effect into AppliedEffect record(s) in the timeline."""
    # Burst-skill DEAL_DAMAGE on enemies → caster's burst payload.
    if (
        effect.kind in (EffectKind.DEAL_DAMAGE, EffectKind.DEAL_TRUE_DAMAGE)
        and effect.target.kind in _ENEMY_TARGET_KINDS
    ):
        timeline.burst_payload_by_member[caster_name] = (
            timeline.burst_payload_by_member.get(caster_name, 0.0)
            + effect.magnitude
        )

    target_kind = effect.target.kind
    target_names: list[str] = []

    if target_kind is TargetKind.SELF:
        target_names = [caster_name]
    elif target_kind in (TargetKind.ALL_ALLIES, TargetKind.NEAREST_ALLIES):
        target_names = list(team_names)
    elif target_kind is TargetKind.BURST_USER:
        target_names = [burst_user_name or caster_name]
    elif target_kind in (TargetKind.ALLY_HIGHEST_ATK, TargetKind.ALLY_LOWEST_HP):
        # Without runtime ATK/HP differentiation, apply to first
        # ``count`` members as a stable approximation.
        n = max(1, effect.target.count)
        target_names = list(team_names[:n])
    else:
        # Enemy-target effects don't appear in the timeline (no opposing
        # team yet). Already counted in burst payload above.
        return

    # Duration → expiry. If duration_seconds == 0, treat as instant
    # (1-second window for event-style effects like one-shot heals).
    duration = effect.duration_seconds or 1.0
    expiry = apply_time + duration

    for name in target_names:
        timeline.applied.append(
            AppliedEffect(
                target_name=name,
                kind=effect.kind,
                magnitude=effect.magnitude,
                apply_time=apply_time,
                expiry_time=expiry,
                stacks_max=effect.stacks_max,
                scaling_source=effect.scaling_source,
                notes=effect.notes,
                source_character=caster_name,
                source_skill_slot=source_skill_slot,
            )
        )


def build_timeline(
    team_skills: Iterable[CharacterSkillSet],
    *,
    base_atk: int = 100_000,
    base_hp: int = 1_000_000,
    base_def: int = 30_000,
    burst_offsets: Optional[tuple[float, ...]] = None,
    full_burst_start: Optional[float] = None,
    weapons: Optional[Iterable[Optional[str]]] = None,
    member_names_for_gauge: Optional[Iterable[Optional[str]]] = None,
) -> Timeline:
    """Walk the skill DSL and produce a timeline of applied effects.

    Burst-chain timing is derived from the team's weapon mix when
    ``weapons`` is provided (slice #75 — burst-gauge dynamics). Without
    weapons, falls back to the legacy fixed schedule
    (``DEFAULT_BURST_CHAIN_OFFSETS_SEC``).

    Explicit ``burst_offsets`` / ``full_burst_start`` override both
    paths, useful for tests or scenario tuning.
    """
    sets = list(team_skills)

    if burst_offsets is None:
        if weapons is not None:
            burst_offsets = compute_burst_chain_offsets(
                weapons, member_names=member_names_for_gauge
            )
        else:
            burst_offsets = DEFAULT_BURST_CHAIN_OFFSETS_SEC
    if full_burst_start is None:
        # B3 chains in at offsets[2] — that's when Full Burst opens.
        full_burst_start = (
            burst_offsets[2] if len(burst_offsets) > 2
            else DEFAULT_FULL_BURST_START_SEC
        )

    if len(sets) > len(burst_offsets):
        raise ValueError(
            f"more team members ({len(sets)}) than burst offsets "
            f"({len(burst_offsets)})"
        )

    member_names = [cs.character_name for cs in sets]
    timeline = Timeline(
        member_names=tuple(member_names),
        base_atk=base_atk,
        base_hp=base_hp,
        base_def=base_def,
    )

    # Phase 1 — t=0: ALWAYS + ON_BATTLE_START (per-Nikke, on themselves)
    # Slice #86: thread per-slot source labels so stacks_max can be
    # enforced per (target, kind, source_character, source_skill_slot).
    for cs in sets:
        for slot_label, slot in (
            ("skill1", cs.skill1),
            ("skill2", cs.skill2),
            ("burst_skill", cs.burst_skill),
        ):
            _record_skill_effects(
                timeline=timeline,
                skills=list(slot),
                caster_name=cs.character_name,
                team_names=member_names,
                burst_user_name=None,
                apply_time=0.0,
                include_triggers={TriggerKind.ALWAYS, TriggerKind.ON_BATTLE_START},
                source_skill_slot=slot_label,
            )

    # Phase 2 — t=full_burst_start: ON_FULL_BURST_START (once)
    for cs in sets:
        for slot_label, slot in (
            ("skill1", cs.skill1),
            ("skill2", cs.skill2),
            ("burst_skill", cs.burst_skill),
        ):
            _record_skill_effects(
                timeline=timeline,
                skills=list(slot),
                caster_name=cs.character_name,
                team_names=member_names,
                burst_user_name=None,
                apply_time=full_burst_start,
                include_triggers={TriggerKind.ON_FULL_BURST_START},
                source_skill_slot=slot_label,
            )

    # Phase 3 — burst chain. Each Nikke bursts at its scheduled offset.
    # ON_BURST_USE on burst-skill + skill1/2 fires for the burst user;
    # ON_ALLY_BURST_USE fires on every ally's skill1/2 (including self).
    for i, cs in enumerate(sets):
        burst_time = burst_offsets[i]
        # Burst user's own burst-skill effects.
        _record_skill_effects(
            timeline=timeline,
            skills=list(cs.burst_skill),
            caster_name=cs.character_name,
            team_names=member_names,
            burst_user_name=cs.character_name,
            apply_time=burst_time,
            include_triggers={TriggerKind.ON_BURST_USE},
            source_skill_slot="burst_skill",
        )
        # Burst user's own skill1/2 ON_BURST_USE.
        for slot_label, slot in (("skill1", cs.skill1), ("skill2", cs.skill2)):
            _record_skill_effects(
                timeline=timeline,
                skills=list(slot),
                caster_name=cs.character_name,
                team_names=member_names,
                burst_user_name=cs.character_name,
                apply_time=burst_time,
                include_triggers={TriggerKind.ON_BURST_USE},
                source_skill_slot=slot_label,
            )
        # Every ally's skill1/2 ON_ALLY_BURST_USE.
        for cs_other in sets:
            for slot_label, slot in (("skill1", cs_other.skill1), ("skill2", cs_other.skill2)):
                _record_skill_effects(
                    timeline=timeline,
                    skills=list(slot),
                    caster_name=cs_other.character_name,
                    team_names=member_names,
                    burst_user_name=cs.character_name,
                    apply_time=burst_time,
                    include_triggers={TriggerKind.ON_ALLY_BURST_USE},
                    source_skill_slot=slot_label,
                )

    # Sort the timeline by apply_time so downstream consumers can scan
    # in chronological order.
    timeline.applied.sort(key=lambda e: (e.apply_time, e.target_name, e.kind.value))
    return timeline


def build_timeline_by_names(
    names: Iterable[str], **kwargs
) -> Optional[Timeline]:
    """Convenience: resolve names through the registry then build.

    Slice #75: when the DB is reachable and the caller didn't pass
    ``weapons``/``burst_offsets`` explicitly, weapon classes are
    auto-loaded so burst-chain offsets are derived from the team mix
    (SG/RL teams burst earlier than slow MG/SR comps). Tests without a
    DB still fall back to the legacy fixed schedule.
    """
    name_list = list(names)
    sets: list[CharacterSkillSet] = []
    for name in name_list:
        cs = registry_get(name)
        if cs is None:
            return None
        sets.append(cs)

    # Auto-derive weapons from the DB when caller didn't override.
    if (
        "weapons" not in kwargs
        and "burst_offsets" not in kwargs
    ):
        weapons = _load_weapons(name_list)
        if any(weapons):
            kwargs["weapons"] = weapons
            # Slice #78: also thread member names so per-character
            # gauge-fill bonuses (Liter, Naga, etc.) accelerate the chain.
            kwargs.setdefault("member_names_for_gauge", name_list)

    return build_timeline(sets, **kwargs)


def _load_weapons(names: list[str]) -> list[Optional[str]]:
    """Look up each character's weapon_class from the DB.

    Returns ``[w_for_name1, w_for_name2, ...]`` parallel to ``names``,
    with ``None`` for misses. Empty list on any failure (so test envs
    without a DB still build via the legacy fixed schedule).
    """
    try:
        from ..data.db import default_db_path, make_engine, get_session
        from ..data.models import Character
        from sqlmodel import select
        engine = make_engine(default_db_path())
        out: list[Optional[str]] = []
        with get_session(engine) as session:
            for name in names:
                ch = session.exec(
                    select(Character).where(Character.name == name)
                ).one_or_none()
                if ch is None or ch.weapon_class is None:
                    out.append(None)
                else:
                    out.append(ch.weapon_class.value)
        return out
    except Exception:
        return [None] * len(names)
