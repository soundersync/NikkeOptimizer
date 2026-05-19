"""Baseline accuracy harness — predicted vs actual outcome.

Runs ``damage.resolve`` over every ``ArenaMatch`` row where we have a
snapshot for both sides (Champions: ``RosterSnapshot`` via FK; Rookie:
opponent ``RookieArenaSnapshot`` + live ``OwnedCharacter`` for the
user) and reports prediction accuracy.

Conventions:
  * Both sides are evaluated, then ``damage.resolve`` runs in both
    directions. The side with the **shorter seconds_to_clear** is the
    predicted winner.
  * Champions clamps every char to LV-400 at view construction.
    Rookie uses the snapshot's actual per-character ``sync_level``
    (Rookie has no level cap in-match).
  * For the Rookie user side we let ``evaluate_by_names`` auto-load
    from ``OwnedCharacter`` (kept fresh daily via the post-rookie
    self-refresh hook). For every other side we feed snapshot-derived
    ``per_name_stats``.
  * Known asymmetry: snapshot sides currently don't pass gear / doll
    / treasure buffs (those decode from snapshot ``ol_gear`` /
    ``favorite_item_*`` payloads but aren't wired through yet). User
    side in Rookie does pass them. This biases predictions in the
    user's favor on Rookie matches; baseline numbers should be read
    with that in mind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from ..data.models import (
    AccountState,
    ArenaMatch,
    Character,
    OwnedCharacter,
    RookieArenaSnapshot,
    RookieArenaSnapshotCharacter,
    RosterSnapshot,
    RosterSnapshotCharacter,
)
from ..optimizer.loader import _lookup_char_class, _predict_base_stats
from . import damage as damage_module
from .evaluator import evaluate_by_names

# Reuse the Champions-specific in-match level cap.
CHAMPIONS_LEVEL_CAP = 400


@dataclass
class TeamFeed:
    """Inputs ready to hand to ``evaluate_by_names``."""

    names: list[str]
    per_name_stats: Optional[dict[str, dict[str, int]]] = None  # None → auto-load

    def as_kwargs(self) -> dict:
        kw: dict = {}
        if self.per_name_stats is not None:
            kw["per_name_stats"] = self.per_name_stats
            # Don't stub gear/doll/treasure auto-loaders here.
            # `_load_owned_gear_buffs` etc. naturally return {} for any
            # name not in OwnedCharacter, so opponent-side chars (which
            # we don't own) get the right empty value. User-side chars
            # (which we do own) get their actual gear/doll/treasure
            # buffs from the live table — this is more accurate than
            # the snapshot, which currently doesn't carry decoded
            # gear data. Trade-off: if the user's gear has changed
            # between the match and now, the buffs will reflect today's
            # state, not the snapshot date's state. For day-scale
            # baselines that's fine.
        return kw


@dataclass
class PerMemberView:
    """Side-merged per-Nikke estimates for the validation page.

    One row per Nikke on the side. ``estimated_damage_dealt`` comes
    from this side's attacker-role contribution; ``estimated_heal_performed``
    + HP / shield + damage_taken + hp_remaining_pct come from this
    side's defender-role contribution.
    """
    name: str
    weapon_class: Optional[str] = None
    element: Optional[str] = None
    estimated_damage_dealt: float = 0.0
    estimated_heal_performed: float = 0.0
    estimated_damage_taken: float = 0.0
    estimated_hp_remaining_pct: float = 100.0
    base_hp: float = 0.0
    shield_value: float = 0.0


@dataclass
class MatchPrediction:
    match_id: int
    mode: str
    user_username: Optional[str]
    opponent_username: Optional[str]
    round_index: Optional[int]
    actual_outcome: Optional[str]  # "win" / "loss" / None
    predicted_winner: Optional[str]  # "user" / "opp" / None (tie)
    user_clear_sec: float           # how long user takes to clear opp
    opp_clear_sec: float            # how long opp takes to clear user
    user_team_dps: float
    opp_team_dps: float
    user_def_ehp: float
    opp_def_ehp: float
    notes: list[str] = field(default_factory=list)
    # Per-Nikke breakdown — populated 2026-05-19 so /simulator/validation
    # can render sim-vs-actual per-Nikke tables.
    user_members: list[PerMemberView] = field(default_factory=list)
    opp_members: list[PerMemberView] = field(default_factory=list)
    # Per-Nikke captured ground truth — Champion only (Rookie results
    # screen doesn't show per-Nikke stats).
    user_actuals: Optional[list["MemberActual"]] = None
    opp_actuals: Optional[list["MemberActual"]] = None

    @property
    def correct(self) -> Optional[bool]:
        """True if predicted_winner matches actual_outcome. None when
        outcome is missing or predicted_winner is a tie."""
        if self.actual_outcome not in ("win", "loss"):
            return None
        if self.predicted_winner is None:
            return None
        return (
            (self.actual_outcome == "win" and self.predicted_winner == "user")
            or (self.actual_outcome == "loss" and self.predicted_winner == "opp")
        )


# ---------------------------------------------------------------------------
# Snapshot → per_name_stats builders
# ---------------------------------------------------------------------------


def _account_state_from_snapshot(snapshot) -> AccountState:
    """Materialize a transient AccountState that carries the snapshot's
    research fields, for ``_predict_base_stats`` mode 2."""
    return AccountState(
        id=-1,
        synchro_level=getattr(snapshot, "synchro_level", 1),
        general_research_level=getattr(snapshot, "general_research_level", 0),
        class_attacker_level=getattr(snapshot, "class_attacker_level", 0),
        class_defender_level=getattr(snapshot, "class_defender_level", 0),
        class_supporter_level=getattr(snapshot, "class_supporter_level", 0),
        mfr_pilgrim_level=getattr(snapshot, "mfr_pilgrim_level", 0),
        mfr_elysion_level=getattr(snapshot, "mfr_elysion_level", 0),
        mfr_tetra_level=getattr(snapshot, "mfr_tetra_level", 0),
        mfr_missilis_level=getattr(snapshot, "mfr_missilis_level", 0),
        mfr_abnormal_level=getattr(snapshot, "mfr_abnormal_level", 0),
    )


def _per_name_stats_from_roster_snapshot(
    session: Session,
    snapshot: RosterSnapshot,
    names: list[str],
    *,
    clamp_level_to: Optional[int],
) -> dict[str, dict[str, int]]:
    """Predict base ATK/HP/DEF per named char from a Champions snapshot."""
    rows = session.exec(
        select(RosterSnapshotCharacter, Character).where(
            RosterSnapshotCharacter.snapshot_id == snapshot.id,
            RosterSnapshotCharacter.character_id == Character.id,
        )
    ).all()
    by_name = {ch.name: (snap_ch, ch) for snap_ch, ch in rows}
    account_state = _account_state_from_snapshot(snapshot)
    return _predict_for_names(by_name, names, account_state, clamp_level_to)


def _per_name_stats_from_rookie_snapshot(
    session: Session,
    snapshot: RookieArenaSnapshot,
    names: list[str],
) -> dict[str, dict[str, int]]:
    """Predict base stats from a Rookie opponent snapshot (no level cap)."""
    rows = session.exec(
        select(RookieArenaSnapshotCharacter, Character).where(
            RookieArenaSnapshotCharacter.snapshot_id == snapshot.id,
            RookieArenaSnapshotCharacter.character_id == Character.id,
        )
    ).all()
    by_name = {ch.name: (snap_ch, ch) for snap_ch, ch in rows}
    account_state = _account_state_from_snapshot(snapshot)
    return _predict_for_names(by_name, names, account_state, None)


def _predict_for_names(
    by_name: dict[str, tuple],
    names: list[str],
    account_state: AccountState,
    clamp_level_to: Optional[int],
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for name in names:
        pair = by_name.get(name)
        if pair is None:
            continue
        snap_ch, char = pair
        data = snap_ch.data or {}
        level = data.get("sync_level") or 1
        if clamp_level_to is not None:
            level = min(level, clamp_level_to)
        core = data.get("core") or 0
        grade = data.get("limit_break")
        if grade is None:
            grade = 3 if core >= 1 else 0
        p_atk, p_hp, p_def, p_power = _predict_base_stats(
            char.name,
            level=level,
            grade=grade,
            core=core,
            skill1_level=data.get("skill1_level") or 1,
            skill2_level=data.get("skill2_level") or 1,
            burst_skill_level=data.get("burst_skill_level") or 1,
            account_state=account_state,
            char_class=_lookup_char_class(char.name),
            manufacturer=char.manufacturer.value if char.manufacturer else None,
        )
        # D4 gear estimate from snapshot power. _predict_base_stats
        # returns level/grade/core-only stats (no gear/cube/treasure
        # bonuses since we lack that data for unowned chars). The
        # snapshot's ``power`` field is the in-game combat power
        # which DOES include gear. Use the ratio to scale up base
        # stats — assumes ATK/HP/DEF scale roughly together with
        # power. Falls back to no-scaling when power is missing.
        snap_power = data.get("power") or data.get("arena_combat")
        scale = 1.0
        if snap_power and p_power and p_power > 0:
            # Cap the scale at 4x as a sanity bound; tournament chars
            # are typically 2-3x level-only power.
            scale = max(1.0, min(4.0, snap_power / p_power))
        stats: dict[str, int] = {}
        if p_atk:
            stats["base_atk"] = int(p_atk * scale)
        if p_hp:
            stats["base_hp"] = int(p_hp * scale)
        if p_def:
            stats["base_def"] = int(p_def * scale)
        if stats:
            out[name] = stats
    return out


# ---------------------------------------------------------------------------
# Per-side feed builder
# ---------------------------------------------------------------------------


def _find_rookie_opponent_snapshot(
    session: Session, match: ArenaMatch
) -> Optional[RookieArenaSnapshot]:
    """Opponent snapshot for the run date, requiring ≥1 char row
    (excludes private/empty snapshots)."""
    opp = (match.opponent_username or "").strip().upper()
    if not opp or match.captured_at is None:
        return None
    return _find_rookie_snapshot_with_chars(
        session, match.captured_at.date(), opp,
    )


def _find_rookie_user_snapshot(
    session: Session, match: ArenaMatch, username: str
) -> Optional[RookieArenaSnapshot]:
    """User-side snapshot for the run date, requiring ≥1 char row."""
    if not username or match.captured_at is None:
        return None
    return _find_rookie_snapshot_with_chars(
        session, match.captured_at.date(), username.strip().upper(),
    )


def _find_rookie_snapshot_with_chars(
    session: Session, run_date, player_username_upper: str,
) -> Optional[RookieArenaSnapshot]:
    rows = session.exec(
        select(RookieArenaSnapshot).where(
            RookieArenaSnapshot.run_date == run_date
        )
    ).all()
    for r in rows:
        if (r.player_username or "").strip().upper() == player_username_upper:
            has = session.exec(
                select(RookieArenaSnapshotCharacter).where(
                    RookieArenaSnapshotCharacter.snapshot_id == r.id
                ).limit(1)
            ).first()
            if has is not None:
                return r
    return None


def _build_team_feed(
    session: Session, match: ArenaMatch, side: str
) -> Optional[TeamFeed]:
    """Return (names, per_name_stats) ready for ``evaluate_by_names``.

    ``side`` is ``"user"`` or ``"opp"``. None when the snapshot is
    missing or has no character data for any of the names.
    """
    names = list(match.user_team if side == "user" else match.opponent_team)
    if not names:
        return None

    if match.mode == "rookie":
        if side == "user":
            from ..data.config import get_self_username
            username = get_self_username()
            snap = _find_rookie_user_snapshot(session, match, username or "")
            if snap is None:
                # No user snapshot for this run — fall back to live
                # OwnedCharacter (today's roster). Caller can detect
                # the snapshot-less state via the iter_snapshot_both
                # filter if they only want truly anchored data.
                return TeamFeed(names=names, per_name_stats=None)
            stats = _per_name_stats_from_rookie_snapshot(session, snap, names)
            if not stats:
                return TeamFeed(names=names, per_name_stats=None)
            return TeamFeed(names=names, per_name_stats=stats)
        snap = _find_rookie_opponent_snapshot(session, match)
        if snap is None:
            return None
        stats = _per_name_stats_from_rookie_snapshot(session, snap, names)
        if not stats:
            return None
        return TeamFeed(names=names, per_name_stats=stats)

    if match.mode == "champion":
        snap_id = (
            match.user_snapshot_id if side == "user" else match.opponent_snapshot_id
        )
        if snap_id is None:
            return None
        snapshot = session.get(RosterSnapshot, snap_id)
        if snapshot is None:
            return None
        stats = _per_name_stats_from_roster_snapshot(
            session, snapshot, names, clamp_level_to=CHAMPIONS_LEVEL_CAP
        )
        if not stats:
            return None
        return TeamFeed(names=names, per_name_stats=stats)

    return None


# ---------------------------------------------------------------------------
# Per-match prediction
# ---------------------------------------------------------------------------


def predict_match(
    session: Session, match: ArenaMatch
) -> Optional[MatchPrediction]:
    user_feed = _build_team_feed(session, match, "user")
    opp_feed = _build_team_feed(session, match, "opp")
    if user_feed is None or opp_feed is None:
        return None

    user_eval = evaluate_by_names(user_feed.names, **user_feed.as_kwargs())
    opp_eval = evaluate_by_names(opp_feed.names, **opp_feed.as_kwargs())
    if user_eval is None or opp_eval is None:
        return None

    # T6 — compute per-team first_burst_sec from weapon mix + skill
    # gauge bonuses instead of using the legacy 10s default. SG/RL-heavy
    # comps (Drake / RL-fast) burst earlier than SMG-heavy comps.
    from .timeline import compute_burst_chain_offsets, _load_weapons

    user_weapons = _load_weapons(user_feed.names)
    opp_weapons = _load_weapons(opp_feed.names)
    user_first_burst = (
        compute_burst_chain_offsets(user_weapons, member_names=user_feed.names)[2]
        if any(user_weapons) else damage_module.DEFAULT_FIRST_BURST_SEC
    )
    opp_first_burst = (
        compute_burst_chain_offsets(opp_weapons, member_names=opp_feed.names)[2]
        if any(opp_weapons) else damage_module.DEFAULT_FIRST_BURST_SEC
    )

    res_u = damage_module.resolve(
        user_eval, opp_eval, first_burst_sec=user_first_burst,
    )
    res_o = damage_module.resolve(
        opp_eval, user_eval, first_burst_sec=opp_first_burst,
    )

    if res_u.seconds_to_clear_defender < res_o.seconds_to_clear_defender:
        predicted = "user"
    elif res_o.seconds_to_clear_defender < res_u.seconds_to_clear_defender:
        predicted = "opp"
    else:
        predicted = None

    # Merge per-member views per side. The merge layer treats the match
    # as ending at min(both clear times) — both sides stop fighting when
    # one team is wiped. Without this, each resolve's per-Nikke numbers
    # use ITS OWN side's clear time as match length, which double-counts
    # damage on the losing side.
    actual_match_end = min(
        res_u.seconds_to_clear_defender,
        res_o.seconds_to_clear_defender,
        damage_module.MATCH_LENGTH_SEC,
    )
    user_members = _merge_member_views(res_u, res_o, actual_match_end)
    opp_members = _merge_member_views(res_o, res_u, actual_match_end)

    # Per-Nikke ground truth from the duel result screen — works
    # for both Champion and Rookie (same screen schema). Rookie just
    # omits the HP% field.
    actuals = actuals_for_match(session, match)

    return MatchPrediction(
        match_id=match.id,
        mode=match.mode,
        user_username=match.user_username,
        opponent_username=match.opponent_username,
        round_index=match.round_index,
        actual_outcome=match.outcome,
        predicted_winner=predicted,
        user_clear_sec=res_u.seconds_to_clear_defender,
        opp_clear_sec=res_o.seconds_to_clear_defender,
        user_team_dps=res_u.attacker_team_dps,
        opp_team_dps=res_o.attacker_team_dps,
        user_def_ehp=res_o.defender_effective_hp,
        opp_def_ehp=res_u.defender_effective_hp,
        notes=list(res_u.notes) + [f"opp→user: {n}" for n in res_o.notes],
        user_members=user_members,
        opp_members=opp_members,
        user_actuals=actuals.user if actuals else None,
        opp_actuals=actuals.opp if actuals else None,
    )


def _merge_member_views(
    attack_res, defense_res, actual_match_end: float,
) -> list[PerMemberView]:
    """Combine a side's attacker-role + defender-role contributions
    into one row per Nikke for the validation UI.

    ``attack_res`` is the DamageResolution where THIS side attacked
    (so ``attack_res.attacker_per_member`` has this side's damage
    output and ``attack_res.match_active_sec`` etc.). ``defense_res``
    is the DamageResolution where the OPPOSITE side attacked (so
    ``defense_res.defender_per_member`` has this side's heal/HP/
    time-alive info).

    ``actual_match_end`` is the real match length —
    ``min(both sides' seconds_to_clear)``. Each Nikke's contributions
    are recomputed against this cap so we don't double-count damage
    on the losing side (whose own clear time may be much longer than
    the actual match end).

    T4: damps each Nikke's damage contribution by their
    ``estimated_time_alive_sec`` from the defense_res — a Nikke
    who's wiped at t=8s shouldn't get credit for an 8237% burst
    that fires at t=10s.
    """
    rows: dict[str, PerMemberView] = {}
    defense_by_name = {c.name: c for c in defense_res.defender_per_member}
    first_burst = attack_res.first_burst_sec
    cycle_period = attack_res.cycle_period_sec

    for c in attack_res.attacker_per_member:
        sustained = (
            c.atk_damage_per_sec + c.true_damage_per_sec + c.other_damage_per_sec
        )
        # Damping: each attacker stops at min(actual_match_end, their_death).
        # Use the sequential-focus-fire death time stored on the defender
        # contribution (T4 + D2). The per-defender estimated_time_alive_sec
        # is derived from cumulative focused damage; slot 1 dies first,
        # slot 5 last.
        d_info = defense_by_name.get(c.name)
        time_alive = actual_match_end
        if d_info is not None:
            # Scale the death time by actual_match_end / defense_res match
            # length to handle the case where defense_res's match_active
            # was longer than actual_match_end.
            ratio = actual_match_end / max(0.1, defense_res.match_active_sec)
            time_alive = min(actual_match_end, d_info.estimated_time_alive_sec * ratio)
        if cycle_period > 0 and first_burst <= time_alive:
            bursts_fired = max(
                1,
                int((time_alive - first_burst) / cycle_period) + 1,
            )
        elif first_burst <= time_alive:
            bursts_fired = 1
        else:
            bursts_fired = 0  # Nikke died before her first burst window
        damped_damage = (
            sustained * time_alive
            + c.burst_payload_per_cycle * bursts_fired
        )
        rows[c.name] = PerMemberView(
            name=c.name,
            weapon_class=c.weapon_class,
            element=c.element,
            estimated_damage_dealt=damped_damage,
        )
    for c in defense_res.defender_per_member:
        # Recompute HP% / damage_taken / heal_performed against the
        # actual match end, not the defense_res's match_active (which
        # is the LOSING side's clear time and over-counts when the
        # losing side actually wins faster in real time).
        max_hp = c.base_hp + c.flat_hp_bonus
        damage_taken_at_end = c.damage_in_per_sec * actual_match_end
        net = max(0.0, damage_taken_at_end - c.shield_value - c.heal_share_per_match)
        hp_pct = (
            max(0.0, min(100.0, (max_hp - net) / max_hp * 100.0))
            if max_hp > 0 else 0.0
        )
        heal_perf = (
            c.heal_per_second
            * min(actual_match_end, c.heal_duration * defense_res.bursts_in_match)
        )
        row = rows.get(c.name) or PerMemberView(
            name=c.name,
            weapon_class=c.weapon_class,
            element=c.element,
        )
        row.estimated_heal_performed = heal_perf
        row.estimated_damage_taken = damage_taken_at_end
        row.estimated_hp_remaining_pct = hp_pct
        row.base_hp = max_hp
        row.shield_value = c.shield_value
        rows[c.name] = row
    return list(rows.values())


# ---------------------------------------------------------------------------
# Corpus walker
# ---------------------------------------------------------------------------


def iter_snapshot_both_matches(session: Session) -> list[ArenaMatch]:
    """Return every ArenaMatch row where both sides have snapshot data
    we can feed the simulator with."""
    matches = list(
        session.exec(
            select(ArenaMatch).where(ArenaMatch.mode.in_(("rookie", "champion")))
        ).all()
    )
    out: list[ArenaMatch] = []
    for m in matches:
        if m.mode == "champion":
            if m.user_snapshot_id is None or m.opponent_snapshot_id is None:
                continue
            u_has = session.exec(
                select(RosterSnapshotCharacter).where(
                    RosterSnapshotCharacter.snapshot_id == m.user_snapshot_id
                ).limit(1)
            ).first()
            o_has = session.exec(
                select(RosterSnapshotCharacter).where(
                    RosterSnapshotCharacter.snapshot_id == m.opponent_snapshot_id
                ).limit(1)
            ).first()
            if u_has is None or o_has is None:
                continue
            out.append(m)
        elif m.mode == "rookie":
            # Strict snapshot=both: require BOTH user-side and opp-side
            # RookieArenaSnapshot rows (each with ≥1 char). This is the
            # scope the /simulator/validation page consumes — only matches
            # where we have an anchored roster for both players.
            from ..data.config import get_self_username
            username = get_self_username() or ""
            if _find_rookie_opponent_snapshot(session, m) is None:
                continue
            if _find_rookie_user_snapshot(session, m, username) is None:
                continue
            out.append(m)
    return out


@dataclass
class BaselineReport:
    predictions: list[MatchPrediction]

    @property
    def n_total(self) -> int:
        return sum(1 for p in self.predictions if p.correct is not None)

    @property
    def n_correct(self) -> int:
        return sum(1 for p in self.predictions if p.correct is True)

    @property
    def accuracy(self) -> float:
        return self.n_correct / self.n_total if self.n_total else 0.0

    def by_mode(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {}
        for p in self.predictions:
            if p.correct is None:
                continue
            stats = out.setdefault(p.mode, [0, 0])
            stats[1] += 1
            if p.correct:
                stats[0] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}


def run_baseline(session: Session) -> BaselineReport:
    matches = iter_snapshot_both_matches(session)
    preds: list[MatchPrediction] = []
    for m in matches:
        p = predict_match(session, m)
        if p is not None:
            preds.append(p)
    return BaselineReport(predictions=preds)


# ---------------------------------------------------------------------------
# Snapshot lookup + freshness helpers — used by the /simulator/validation
# page to render a per-side freshness badge alongside each prediction.
# ---------------------------------------------------------------------------


@dataclass
class SnapshotFreshness:
    captured_at: Optional[datetime]
    """When the snapshot itself was written (UTC, naive)."""
    lag_days: Optional[int]
    """Local-TZ-normalized days between snapshot.captured_at and
    match.captured_at. ``None`` when one of those is missing."""

    @property
    def is_fresh(self) -> bool:
        """True when the snapshot was captured the same local day as
        the match (lag_days ≤ 0). ``False`` for a stale backfill."""
        return self.lag_days is not None and self.lag_days <= 0

    @property
    def label(self) -> str:
        """'fresh' or '+Nd stale' — for use in the UI badge text."""
        if self.lag_days is None:
            return "—"
        if self.lag_days <= 0:
            return "fresh"
        return f"+{self.lag_days}d stale"


def _as_local_date(dt: Optional[datetime]):
    """Treat a naive UTC datetime as UTC, convert to local TZ, return
    the date. ``None`` passthrough."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


def freshness_for(
    snapshot_captured_at: Optional[datetime],
    match_captured_at: Optional[datetime],
) -> SnapshotFreshness:
    """Compute the staleness of a snapshot vs a match (local TZ days)."""
    s_date = _as_local_date(snapshot_captured_at)
    m_date = _as_local_date(match_captured_at)
    if s_date is None or m_date is None:
        return SnapshotFreshness(captured_at=snapshot_captured_at, lag_days=None)
    return SnapshotFreshness(
        captured_at=snapshot_captured_at,
        lag_days=(s_date - m_date).days,
    )


@dataclass
class MemberActual:
    """One row of captured per-Nikke ground truth from a Champion duel
    results screen (``PromoExtractedField`` with region slugs like
    ``left.char1.atk`` etc.).

    Field meanings — these are post-match outcome stats shown to the
    player, NOT the Nikke's static stat:
      * damage_dealt  → total damage this Nikke dealt during the match
      * damage_taken  → total damage this Nikke absorbed (the ``def`` cell)
      * heal_performed → total healing this Nikke gave allies
      * hp_remaining_pct → HP % at the end of the match (0..100)
      * disconnected → True when the Nikke was wiped before timeout
    """
    name: str
    slot: int
    damage_dealt: Optional[int] = None
    damage_taken: Optional[int] = None
    heal_performed: Optional[int] = None
    hp_remaining_pct: Optional[float] = None
    disconnected: bool = False


@dataclass
class ChampionMatchActuals:
    """Per-side captured per-Nikke results for one Champion duel.

    Sides keyed as 'user' / 'opp' to match ``MatchPrediction``.
    Returns ``None`` when no duel screenshot exists for the match
    (results-only matches without per-Nikke extractions, or
    extraction not yet run).
    """
    user: list[MemberActual]
    opp: list[MemberActual]
    screenshot_id: Optional[int] = None


def actuals_for_match(
    session: Session, match: ArenaMatch,
) -> Optional[ChampionMatchActuals]:
    """Fetch captured per-Nikke results for an ArenaMatch.

    Handles both modes — the results-duel screenshot format is
    pixel-identical between Champion and Rookie Arena (see
    rookie_arena_regions.py docstring), so the same extraction
    schema applies. Differences:

      * Champion: session_id = ``"champion-pm{promo_match_id}"`` →
        PromoMatch.id directly, with round_no = match.round_index
      * Rookie: session_id = ``"rookie-run-{tournament_id}"`` →
        PromoMatch via (tournament_id, match_no=round_index),
        with results_duel.round_no = None (single screenshot per
        rookie battle)
      * Rookie ``hp`` field is empty (results screen omits HP%);
        all other fields populated identically

    Returns ``None`` if no duel screenshot was extracted for this
    match.
    """
    if match.mode not in ("champion", "rookie") or not match.session_id:
        return None

    from ..data.models import (
        Character,
        PromoExtractedField,
        PromoMatch,
        PromoMatchScreenshot,
    )

    duel: Optional[PromoMatchScreenshot] = None
    if match.session_id.startswith("champion-pm"):
        try:
            promo_match_id = int(match.session_id[len("champion-pm"):])
        except ValueError:
            return None
        duel = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.match_id == promo_match_id,
                PromoMatchScreenshot.kind == "results_duel",
                PromoMatchScreenshot.round_no == match.round_index,
            )
        ).first()
    elif match.session_id.startswith("rookie-run-"):
        try:
            tournament_id = int(match.session_id[len("rookie-run-"):])
        except ValueError:
            return None
        if match.round_index is None:
            return None
        pm = session.exec(
            select(PromoMatch).where(
                PromoMatch.tournament_id == tournament_id,
                PromoMatch.match_no == match.round_index,
            )
        ).first()
        if pm is None:
            return None
        duel = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.match_id == pm.id,
                PromoMatchScreenshot.kind == "results_duel",
            )
        ).first()
    if duel is None:
        return None

    fields = session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.screenshot_id == duel.id,
        )
    ).all()
    char_ids = {f.character_id for f in fields if f.character_id is not None}
    char_names: dict[int, str] = {}
    if char_ids:
        rows = session.exec(
            select(Character.id, Character.name).where(
                Character.id.in_(char_ids)
            )
        ).all()
        char_names = {int(cid): str(name) for cid, name in rows}

    by_slug: dict[str, PromoExtractedField] = {f.region_slug: f for f in fields}

    def _try_int(s: Optional[str]) -> Optional[int]:
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None

    def _try_pct(s: Optional[str]) -> Optional[float]:
        if not s:
            return None
        try:
            return float(s.rstrip("%"))
        except ValueError:
            return None

    def _side(prefix: str) -> list[MemberActual]:
        out: list[MemberActual] = []
        for slot in range(1, 6):
            name_f = by_slug.get(f"{prefix}.char{slot}.name")
            atk_f = by_slug.get(f"{prefix}.char{slot}.atk")
            def_f = by_slug.get(f"{prefix}.char{slot}.def")
            heal_f = by_slug.get(f"{prefix}.char{slot}.heal")
            hp_f = by_slug.get(f"{prefix}.char{slot}.hp")
            dc_f = by_slug.get(f"{prefix}.char{slot}.disconnect")
            name = None
            if name_f:
                name = (
                    char_names.get(name_f.character_id)
                    if name_f.character_id else (name_f.text or "")
                )
            out.append(MemberActual(
                name=name or f"(slot {slot})",
                slot=slot,
                damage_dealt=_try_int(atk_f.normalized) if atk_f else None,
                damage_taken=_try_int(def_f.normalized) if def_f else None,
                heal_performed=_try_int(heal_f.normalized) if heal_f else None,
                hp_remaining_pct=_try_pct(hp_f.normalized) if hp_f else None,
                disconnected=bool(dc_f and (dc_f.text or "").strip()),
            ))
        return out

    left = _side("left")
    right = _side("right")
    # Which side is the user? Match by team composition — ArenaMatch's
    # user_team is the canonical source, captured from the loadout
    # screens. The duel-result extractions don't carry their own side
    # label, so we ask: which of (left, right) overlaps more with
    # match.user_team? ``is_user_lineup`` is NOT the right signal here
    # — it refers to which LOADOUT screen is the user's, which can be
    # the opposite of which duel-result-side has the user's team.
    user_names = {(n or "").lower() for n in (match.user_team or [])}
    left_overlap = sum(1 for m in left if (m.name or "").lower() in user_names)
    right_overlap = sum(1 for m in right if (m.name or "").lower() in user_names)
    if left_overlap >= right_overlap:
        user_side, opp_side = left, right
    else:
        user_side, opp_side = right, left

    return ChampionMatchActuals(
        user=user_side, opp=opp_side, screenshot_id=duel.id,
    )


def snapshot_pair_for_match(
    session: Session, match: ArenaMatch,
) -> tuple[Optional[RookieArenaSnapshot | RosterSnapshot],
           Optional[RookieArenaSnapshot | RosterSnapshot]]:
    """Return ``(user_snapshot, opp_snapshot)`` for a match, picking
    the right snapshot system per mode.

    Returns ``(None, None)`` for unsupported modes or missing
    snapshots — caller uses this to render freshness badges next to
    each prediction. Same lookup logic as
    ``iter_snapshot_both_matches``.
    """
    if match.mode == "champion":
        user_snap = (
            session.get(RosterSnapshot, match.user_snapshot_id)
            if match.user_snapshot_id else None
        )
        opp_snap = (
            session.get(RosterSnapshot, match.opponent_snapshot_id)
            if match.opponent_snapshot_id else None
        )
        return user_snap, opp_snap
    if match.mode == "rookie":
        from ..data.config import get_self_username
        username = get_self_username() or ""
        user_snap = _find_rookie_user_snapshot(session, match, username)
        opp_snap = _find_rookie_opponent_snapshot(session, match)
        return user_snap, opp_snap
    return None, None
