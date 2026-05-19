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
            # Suppress auto-loads that would otherwise hit OwnedCharacter
            # for an opponent we don't own. Identities still auto-load
            # from the Character table (good — element/weapon/role come
            # from there).
            kw["per_name_gear_buffs"] = {}
            kw["per_name_doll_buffs"] = {}
            kw["per_name_treasure_buffs"] = {}
        return kw


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
        p_atk, p_hp, p_def, _power = _predict_base_stats(
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
        stats: dict[str, int] = {}
        if p_atk:
            stats["base_atk"] = int(p_atk)
        if p_hp:
            stats["base_hp"] = int(p_hp)
        if p_def:
            stats["base_def"] = int(p_def)
        if stats:
            out[name] = stats
    return out


# ---------------------------------------------------------------------------
# Per-side feed builder
# ---------------------------------------------------------------------------


def _find_rookie_opponent_snapshot(
    session: Session, match: ArenaMatch
) -> Optional[RookieArenaSnapshot]:
    opp = (match.opponent_username or "").strip().upper()
    if not opp or match.captured_at is None:
        return None
    rows = session.exec(
        select(RookieArenaSnapshot).where(
            RookieArenaSnapshot.run_date == match.captured_at.date()
        )
    ).all()
    for r in rows:
        if (r.player_username or "").strip().upper() == opp:
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
            # Live OwnedCharacter — auto-loaded by evaluate_by_names.
            return TeamFeed(names=names, per_name_stats=None)
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

    res_u = damage_module.resolve(user_eval, opp_eval)
    res_o = damage_module.resolve(opp_eval, user_eval)

    if res_u.seconds_to_clear_defender < res_o.seconds_to_clear_defender:
        predicted = "user"
    elif res_o.seconds_to_clear_defender < res_u.seconds_to_clear_defender:
        predicted = "opp"
    else:
        predicted = None

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
    )


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
            if _find_rookie_opponent_snapshot(session, m) is not None:
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
