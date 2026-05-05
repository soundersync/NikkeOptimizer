"""Per-capture completeness warnings.

Highlights data the extractor couldn't read or that's expected by the
mode but missing. Used by the captures list + detail templates so the
user can spot-check every capture without opening it.

Three layers:

1. **Per-row warnings** — derived from a single ``ArenaMatch``. Flags
   missing usernames, blank cells, missing per-team totals, and
   round-index gaps when the mode requires one.

2. **Set-completeness warnings** — grouped across rows by
   ``(mode, opponent_username)``. Flags when an SP set is missing
   rounds 1–3 or a Champions opponent is missing rounds 1–5.

3. **Session completeness** — for Champions sessions specifically,
   produces a 5-round × 3-screen-type matrix (P1 loadout / P2 loadout /
   round result) plus the overall Duel Result indicator. Drives the
   pre-save preview matrix and the "Add results" workflow on the
   captures list.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..data.models import ArenaMatch


_EXPECTED_ROUNDS = {
    "special": (1, 2, 3),
    "champion": (1, 2, 3, 4, 5),
}


def per_row_warnings(cap: ArenaMatch) -> list[str]:
    """Warnings derived from a single ArenaMatch row.

    Returned strings are short, user-readable, and intended to be
    displayed inline (e.g. as a comma-joined annotation).
    """
    out: list[str] = []

    if not cap.user_username:
        out.append("user username not detected")
    if cap.mode != "champion":
        # Champions Arena Info popups don't show an opponent.
        if not cap.opponent_username:
            out.append("opponent username not detected")
        if cap.opponent_power is None:
            out.append("opponent total power not detected")
        if not cap.opponent_team or all(not c for c in cap.opponent_team):
            out.append("opponent team not detected")

    if cap.user_power is None:
        out.append("user total power not detected")

    user_blanks = sum(1 for c in (cap.user_team or []) if not c)
    if user_blanks:
        out.append(f"user team: {user_blanks}/5 cells unmatched")

    if cap.mode != "champion":
        opp_blanks = sum(1 for c in (cap.opponent_team or []) if not c)
        if opp_blanks:
            out.append(f"opponent team: {opp_blanks}/5 cells unmatched")

    if cap.mode in _EXPECTED_ROUNDS and cap.round_index is None:
        out.append(f"{cap.mode} requires round_index but none was detected")

    return out


def set_completeness_warnings(captures: Iterable[ArenaMatch]) -> dict[int, list[str]]:
    """Cross-row "incomplete set" warnings.

    Groups captures by ``(mode, opponent_username)`` for SP/Champion
    modes and flags any group that's missing rounds. Rookie matches
    don't have rounds so they're skipped.

    Returns ``{capture_id: [warning, ...]}`` — one entry per capture
    that belongs to an incomplete set. Each capture in the same group
    gets the same warning text so the user sees consistent flags
    regardless of which row they're looking at.
    """
    groups: dict[tuple[str, str], list[ArenaMatch]] = defaultdict(list)
    for cap in captures:
        if cap.mode not in _EXPECTED_ROUNDS:
            continue
        # For champion mode, opponent_username may be missing — group
        # by user_username instead so multi-round captures of the
        # *same player's* lineup still cluster correctly.
        key_user = cap.opponent_username or cap.user_username or "?"
        groups[(cap.mode, key_user)].append(cap)

    out: dict[int, list[str]] = defaultdict(list)
    for (mode, opponent), rows in groups.items():
        expected = set(_EXPECTED_ROUNDS[mode])
        captured_rounds = {r.round_index for r in rows if r.round_index is not None}
        missing = sorted(expected - captured_rounds)
        if not missing:
            continue
        if mode == "special":
            label = "SP set"
        elif mode == "champion":
            label = f"Champions opponent {opponent}"
        else:
            label = mode
        warning = (
            f"{label} incomplete: have rounds "
            f"{sorted(captured_rounds) or '(none)'}, missing {missing}"
        )
        for r in rows:
            if r.id is not None:
                out[r.id].append(warning)
    return out


# ---------------------------------------------------------------------------
# Session completeness (Champions Duel pre-save preview matrix)
# ---------------------------------------------------------------------------


@dataclass
class SessionRoundCell:
    """One cell in the 5-round × 3-screen-type session matrix."""

    captured: bool = False
    capture_id: Optional[int] = None
    needs_review: bool = False
    blank_cells: int = 0  # how many of the 5 portrait slots failed to match


@dataclass
class SessionRound:
    round_index: int
    p1_loadout: SessionRoundCell = field(default_factory=SessionRoundCell)
    p2_loadout: SessionRoundCell = field(default_factory=SessionRoundCell)
    round_result: SessionRoundCell = field(default_factory=SessionRoundCell)


@dataclass
class SessionCompleteness:
    """Pre-save preview / dashboard view of one Champions session."""

    session_id: str
    session_label: Optional[str]
    session_kind: Optional[str]  # 'predictions' | 'partial' | 'complete' | None
    rounds: list[SessionRound]
    duel_result: SessionRoundCell  # whole-Duel summary screen
    warnings: list[str] = field(default_factory=list)

    @property
    def has_orphaned_results(self) -> bool:
        return any(
            r.round_result.captured
            and not (r.p1_loadout.captured or r.p2_loadout.captured)
            for r in self.rounds
        )

    @property
    def loadouts_only(self) -> bool:
        any_loadout = any(
            r.p1_loadout.captured or r.p2_loadout.captured for r in self.rounds
        )
        any_result = any(r.round_result.captured for r in self.rounds)
        return any_loadout and not any_result and not self.duel_result.captured


def _build_player_bucketing(
    rows: list[ArenaMatch],
    user_username: Optional[str],
) -> dict[Optional[str], str]:
    """Return ``{player_username: 'p1' | 'p2'}`` for one Champions session.

    Designed to handle three cases gracefully:

    * **User-vs-opponent**: the user uploaded their own Champions Duel.
      The user's username (or ``is_user_lineup=True`` rows) → 'p1';
      the other player → 'p2'.
    * **Cheering / observed**: the user uploaded a Duel between TWO OTHER
      players (neither is them). The two distinct usernames are bucketed
      arbitrarily but consistently — leftmost-by-first-appearance becomes
      'p1', the other 'p2'.
    * **Mixed signal**: any rows the heuristic can't place fall back to
      'p2' so they're at least visible somewhere in the matrix.
    """
    bucketing: dict[Optional[str], str] = {}
    user_norm = (user_username or "").strip().upper()
    distinct: list[Optional[str]] = []
    user_seen: Optional[str] = None
    for r in rows:
        if r.mode != "champion":
            continue
        # Honor explicit is_user_lineup when set — it's the
        # CP-cross-validated truth from import time.
        if r.is_user_lineup is True and r.user_username:
            user_seen = r.user_username
        u = r.user_username
        if u and u not in distinct:
            distinct.append(u)
        elif u is None and None not in distinct:
            distinct.append(None)
    # Prefer the configured self-username when it appears; otherwise any
    # username with is_user_lineup=True.
    p1_user: Optional[str] = None
    if user_norm:
        for u in distinct:
            if u and u.strip().upper() == user_norm:
                p1_user = u
                break
    if p1_user is None and user_seen:
        p1_user = user_seen
    if p1_user is None and distinct:
        # Fall back to first-seen username.
        p1_user = distinct[0]
    for u in distinct:
        if u == p1_user:
            bucketing[u] = "p1"
        else:
            bucketing[u] = "p2"
    return bucketing


def _is_user_loadout(cap: ArenaMatch, user_username: Optional[str]) -> bool:
    """Legacy single-row helper, kept for direct callers/tests.

    For session-level bucketing prefer ``_build_player_bucketing`` —
    this fallback is conservative and assumes a binary self/opponent
    distinction, which breaks down for cheered duels between two
    third parties.
    """
    if cap.is_user_lineup is not None:
        return cap.is_user_lineup
    if not cap.user_username:
        return False
    if user_username:
        return cap.user_username.strip().upper() == user_username.strip().upper()
    return True


def session_completeness(
    captures: Iterable[ArenaMatch],
    *,
    user_username: Optional[str] = None,
) -> Optional[SessionCompleteness]:
    """Build the per-round 5×3 matrix for ONE Champions session.

    All input ``captures`` must share the same ``session_id`` (caller's
    job to filter — this function does not validate). Returns None when
    the input has no Champions rows.
    """
    rows = [c for c in captures if c.mode and c.mode.startswith("champion")]
    if not rows:
        return None
    sid = rows[0].session_id or ""
    label = next((r.session_label for r in rows if r.session_label), None)
    # Recompute kind here too so the matrix view doesn't lag a stale DB.
    from ..roster.arena_importer import compute_session_kind
    kind = compute_session_kind(rows)

    # Pre-compute the player→column map for the whole session so the
    # cheering case (neither player is the user) buckets correctly.
    bucketing = _build_player_bucketing(rows, user_username)

    rounds = [SessionRound(round_index=i) for i in range(1, 6)]
    duel = SessionRoundCell()
    for cap in rows:
        if cap.mode == "champion_duel_result":
            duel = SessionRoundCell(
                captured=True,
                capture_id=cap.id,
                needs_review=cap.needs_review,
            )
            continue
        if cap.round_index is None or not (1 <= cap.round_index <= 5):
            continue
        rd = rounds[cap.round_index - 1]
        cell_data = SessionRoundCell(
            captured=True,
            capture_id=cap.id,
            needs_review=cap.needs_review,
            blank_cells=sum(1 for c in (cap.user_team or []) if not c),
        )
        if cap.mode == "champion":
            column = bucketing.get(cap.user_username, "p2")
            if column == "p1":
                rd.p1_loadout = cell_data
            else:
                rd.p2_loadout = cell_data
        elif cap.mode == "champion_battle_record":
            rd.round_result = cell_data

    warnings: list[str] = []
    for r in rounds:
        missing_loadouts = []
        if not r.p1_loadout.captured:
            missing_loadouts.append("P1")
        if not r.p2_loadout.captured:
            missing_loadouts.append("P2")
        if missing_loadouts and r.round_result.captured:
            warnings.append(
                f"Round {r.round_index}: result captured but loadout(s) missing "
                f"({', '.join(missing_loadouts)})"
            )
    if duel.captured and not any(r.round_result.captured for r in rounds):
        warnings.append("Duel Result captured but no per-round Battle Records")

    return SessionCompleteness(
        session_id=sid,
        session_label=label,
        session_kind=kind,
        rounds=rounds,
        duel_result=duel,
        warnings=warnings,
    )


def session_completeness_warnings(
    captures: Iterable[ArenaMatch],
    *,
    user_username: Optional[str] = None,
) -> dict[str, SessionCompleteness]:
    """Build the matrix for every Champions session present in ``captures``.

    Keyed by ``session_id``. Sessions without an ID (legacy data from
    before slice #135) get bucketed under the empty string so they still
    surface — operators can backfill IDs via a maintenance script later.
    """
    by_session: dict[str, list[ArenaMatch]] = defaultdict(list)
    for cap in captures:
        if not cap.mode or not cap.mode.startswith("champion"):
            continue
        by_session[cap.session_id or ""].append(cap)
    out: dict[str, SessionCompleteness] = {}
    for sid, rows in by_session.items():
        sc = session_completeness(rows, user_username=user_username)
        if sc is not None:
            out[sid] = sc
    return out
