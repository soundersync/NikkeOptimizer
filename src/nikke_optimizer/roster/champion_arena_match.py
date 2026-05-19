"""Bridge Champions Arena ingest data into ``ArenaMatch`` rows.

Each Champions duel has 5 rounds (each round = 5v5 between two
season-locked teams the players pre-selected). This builder produces
one ``ArenaMatch`` row per round, so the per-match score is a
``GROUP BY session_id`` query and per-round outcome detection reuses
the same disconnect logic shipped for rookie (both share the
``results_duel`` screenshot kind, pixel-identical).

Natural key for upsert: ``(session_id, round_index)`` where
``session_id`` = ``"champion-pm{promo_match_id}"`` (anchored to the
globally-unique ``PromoMatch.id``) and ``round_index`` = duel round
(1..5). The PromoMatch id is the only collision-free identifier
across all tournaments — using ``(tournament_id, round_label,
match_no)`` collides when ``match_no`` is NULL (top_16, finals) or
when multiple groups share the same labels. The session_label
spells out the human-readable coordinates so the audit viewer
still tells you "Champions round_64 group_3 match_2 round_4".

Source data per Champions match (one ``PromoMatch``):
  - 10 ``player_loadout`` screenshots — 5 per side (``player_top/`` +
    ``player_bottom/``, named ``round_1.png`` .. ``round_5.png``)
  - 5 ``results_duel`` screenshots — one per round (``duel_N.png``)
  - 1 ``results_overview`` screenshot

User-side identification: compare each side's ``player_name`` (OCR'd
from any of the 5 loadouts) against the configured self-username
(``config.get_self_username()``). When neither side matches, leaves
``is_user_lineup = None`` (third-party captures — still valuable as
labeled training data).

Snapshot linkage: looks up ``RosterSnapshot`` rows by
``(season=season_for_date(captured_at), player_username=...)``. The
FK columns on ArenaMatch (``user_snapshot_id`` / ``opponent_snapshot_id``)
were added in migration 0001 and stay NULL when no snapshot exists
yet — re-running the builder backfills them as new snapshots land.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..data.config import get_self_username
from ..data.models import (
    ArenaMatch,
    Character,
    PromoExtractedField,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
    RosterSnapshot,
)
from ..data.seasons import season_for_date
from .rookie_arena_arena_match import (
    _disconnect_flags_from_results,
    _fields_by_slug,
    _outcome_from_disconnects,
)

log = logging.getLogger(__name__)


CHAMPION_MODE = "champion"
CHAMPION_SESSION_KIND = "champion_duel"


def session_id_for_duel(promo_match_id: int) -> str:
    """Stable session_id grouping the 5 rounds of one Champion duel.

    Anchored to ``PromoMatch.id`` because ``(tournament_id, round_label,
    match_no)`` collides for NULL ``match_no`` (top_16, finals) and
    for repeated labels across groups in the same tournament.
    """
    return f"champion-pm{promo_match_id}"


# ---------------------------------------------------------------------------
# Disk-layout helpers
# ---------------------------------------------------------------------------


def _position_from_path(file_path: str) -> Optional[str]:
    """Return ``"top"`` / ``"bottom"`` based on the screenshot's
    parent directory. Returns None for paths that don't fit the
    ``.../match_N/player_(top|bottom)/round_N.png`` layout (defensive
    against future capture-format changes)."""
    parts = Path(file_path).parts
    for part in reversed(parts):
        if part == "player_top":
            return "top"
        if part == "player_bottom":
            return "bottom"
    return None


def _duel_round_from_path(file_path: str) -> Optional[int]:
    """Extract round index N from ``.../results/duel_N.png``."""
    stem = Path(file_path).stem  # e.g. "duel_1"
    if stem.startswith("duel_") and stem[5:].isdigit():
        return int(stem[5:])
    return None


def _loadout_round_from_path(file_path: str) -> Optional[int]:
    """Extract round index N from ``.../player_(top|bottom)/round_N.png``."""
    stem = Path(file_path).stem
    if stem.startswith("round_") and stem[6:].isdigit():
        return int(stem[6:])
    return None


# ---------------------------------------------------------------------------
# Field readers
# ---------------------------------------------------------------------------


def _player_name_from_loadouts(
    session: Session, loadout_shots: list[PromoMatchScreenshot],
) -> Optional[str]:
    """Read the OCR'd ``player_name`` from any loadout shot for this
    side. Picks the first non-empty value across the 5 rounds — they
    all show the same player.
    """
    for shot in loadout_shots:
        f = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id == shot.id,
                PromoExtractedField.region_slug == "player_name",
            )
        ).first()
        if f is not None and f.text:
            return f.text.strip()
    return None


def _loadout_team(
    session: Session,
    loadout_shot: PromoMatchScreenshot,
    char_name_by_id: dict[int, str],
) -> list[Optional[str]]:
    """Read 5 canonical character names from one loadout shot's
    ``char{N}.name`` rows (the small per-card name slugs)."""
    by_slug = _fields_by_slug(session, loadout_shot.id)
    out: list[Optional[str]] = []
    for slot in range(1, 6):
        nrow = by_slug.get(f"char{slot}.name")
        if nrow is not None and nrow.character_id is not None:
            out.append(char_name_by_id.get(nrow.character_id))
        else:
            out.append(None)
    return out


def _duel_side_names(
    by_slug: dict[str, PromoExtractedField],
    side: str,
    char_name_by_id: dict[int, str],
) -> list[Optional[str]]:
    """Read 5 character names from a ``results_duel`` screenshot for
    one side (``"left"`` or ``"right"``)."""
    out: list[Optional[str]] = []
    for slot in range(1, 6):
        nrow = by_slug.get(f"{side}.char{slot}.name")
        if nrow is not None and nrow.character_id is not None:
            out.append(char_name_by_id.get(nrow.character_id))
        else:
            out.append(None)
    return out


def _team_overlap(a: list[Optional[str]], b: list[Optional[str]]) -> int:
    """Count how many entries in ``a`` are present in ``b`` (set
    semantics — order doesn't matter). Used to pair duel sides
    (left/right) to loadout positions (top/bottom)."""
    a_set = {x for x in a if x}
    b_set = {x for x in b if x}
    return len(a_set & b_set)


# ---------------------------------------------------------------------------
# Per-round payload
# ---------------------------------------------------------------------------


@dataclass
class _RoundPayload:
    """Everything we need to upsert one ArenaMatch row for one round
    of one Champion duel."""

    round_no: int
    user_username: Optional[str]
    opponent_username: Optional[str]
    user_team: list[str]           # padded to 5 with "" for None
    opponent_team: list[str]
    user_loadout_screenshot: Optional[str]
    opponent_loadout_screenshot: Optional[str]
    duel_screenshot: Optional[str]
    outcome: Optional[str]
    is_user_lineup: Optional[bool]
    capture_quality: dict


def _read_overview(
    session: Session, shots: list[PromoMatchScreenshot],
) -> dict:
    """Read the per-match aggregate fields off a results_overview
    screenshot. Returns a dict with optional ``left_name``,
    ``right_name``, ``winner_name``, and per-round
    ``round_N_winner`` ("left"/"right"). Empty dict when no overview
    was captured / no OCR.
    """
    overview = next(
        (s for s in shots if s.kind == "results_overview"), None,
    )
    if overview is None:
        return {}
    out: dict = {}
    for f in session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.screenshot_id == overview.id,
        )
    ).all():
        if f.region_slug in ("left_name", "right_name", "winner_name"):
            if f.text and f.text.strip():
                out[f.region_slug] = f.text.strip()
        elif f.region_slug.endswith("_winner") and f.region_slug.startswith("round"):
            if f.normalized in ("left", "right"):
                out[f.region_slug] = f.normalized
    return out


def _build_round_payloads(
    session: Session, match: PromoMatch, char_name_by_id: dict[int, str],
) -> list[_RoundPayload]:
    """Read everything off one Champion PromoMatch and produce 0..5
    per-round payloads (one per duel round that we have OCR'd data for).
    """
    shots = session.exec(
        select(PromoMatchScreenshot).where(
            PromoMatchScreenshot.match_id == match.id,
        )
    ).all()

    loadouts_by_pos: dict[str, dict[int, PromoMatchScreenshot]] = {
        "top": {}, "bottom": {},
    }
    duel_by_round: dict[int, PromoMatchScreenshot] = {}
    for shot in shots:
        if shot.kind == "player_loadout":
            pos = _position_from_path(shot.file_path)
            rno = _loadout_round_from_path(shot.file_path)
            if pos is None or rno is None:
                continue
            loadouts_by_pos[pos][rno] = shot
        elif shot.kind == "results_duel":
            rno = _duel_round_from_path(shot.file_path)
            if rno is not None:
                duel_by_round[rno] = shot

    if not duel_by_round:
        return []

    # Overview screen — fallback source for player names (works for
    # results-only matches where no loadouts were captured) AND
    # cross-check signal for per-round outcomes.
    overview = _read_overview(session, list(shots))

    # Identify players from any available loadout per side, falling
    # back to the overview's left_name/right_name when loadouts didn't
    # populate them.
    top_name = _player_name_from_loadouts(
        session, sorted(loadouts_by_pos["top"].values(), key=lambda s: s.id),
    )
    bottom_name = _player_name_from_loadouts(
        session, sorted(loadouts_by_pos["bottom"].values(), key=lambda s: s.id),
    )
    # When loadout-side names are missing, derive from overview's
    # left_name/right_name. Mapping (top↔left vs top↔right) gets
    # resolved below from team-name overlap; for the no-loadout case
    # there's no team to compare against, so we default top=left
    # (matches the disk convention `player_top` = left-side player).
    if top_name is None and overview.get("left_name"):
        top_name = overview["left_name"]
    if bottom_name is None and overview.get("right_name"):
        bottom_name = overview["right_name"]

    self_name = (get_self_username() or "").strip()
    self_upper = self_name.upper() if self_name else ""

    # Which position is the user? Compare against config self-username
    # (case-insensitive, exact match). When neither matches, mark
    # is_user_lineup=None and pick a deterministic mapping (top=user)
    # so the row schema stays populated.
    user_pos: Optional[str] = None
    if self_upper:
        if top_name and top_name.upper() == self_upper:
            user_pos = "top"
        elif bottom_name and bottom_name.upper() == self_upper:
            user_pos = "bottom"
    is_user_lineup: Optional[bool] = (user_pos is not None) or None

    # For third-party captures: default to top=user so the row is
    # still populated. The is_user_lineup=None signals "we don't know."
    if user_pos is None:
        user_pos = "top"
    opp_pos = "bottom" if user_pos == "top" else "top"
    user_player_name = top_name if user_pos == "top" else bottom_name
    opp_player_name = bottom_name if user_pos == "top" else top_name

    # Resolve left/right (duel) → top/bottom (loadout) mapping by
    # comparing round-1 loadout teams to the round-1 duel teams.
    # NIKKE's Champions UI doesn't fix this mapping by player_id; it
    # depends on the screenshot perspective, so we derive empirically
    # from name overlap.
    top_lo_1 = loadouts_by_pos["top"].get(1)
    bottom_lo_1 = loadouts_by_pos["bottom"].get(1)
    duel_1 = duel_by_round.get(1)
    duel_side_for_top = "left"  # default; flipped below if evidence says so
    if top_lo_1 is not None and duel_1 is not None:
        by_slug = _fields_by_slug(session, duel_1.id)
        top_team_1 = _loadout_team(session, top_lo_1, char_name_by_id)
        left_team_1 = _duel_side_names(by_slug, "left", char_name_by_id)
        right_team_1 = _duel_side_names(by_slug, "right", char_name_by_id)
        if _team_overlap(top_team_1, right_team_1) > _team_overlap(top_team_1, left_team_1):
            duel_side_for_top = "right"
    user_duel_side = duel_side_for_top if user_pos == "top" else (
        "right" if duel_side_for_top == "left" else "left"
    )
    opp_duel_side = "right" if user_duel_side == "left" else "left"

    payloads: list[_RoundPayload] = []
    for round_no in sorted(duel_by_round.keys()):
        duel_shot = duel_by_round[round_no]
        by_slug = _fields_by_slug(session, duel_shot.id)

        # Names per side, sourced from the LARGER battle-records text
        # on duel_N (more reliable than the tiny loadout name crops).
        user_names_duel = _duel_side_names(
            by_slug, user_duel_side, char_name_by_id,
        )
        opp_names_duel = _duel_side_names(
            by_slug, opp_duel_side, char_name_by_id,
        )

        # Fall back to loadout names per-slot if duel-side name missed.
        user_lo = loadouts_by_pos[user_pos].get(round_no)
        opp_lo = loadouts_by_pos[opp_pos].get(round_no)
        user_names_lo = (
            _loadout_team(session, user_lo, char_name_by_id) if user_lo else [None] * 5
        )
        opp_names_lo = (
            _loadout_team(session, opp_lo, char_name_by_id) if opp_lo else [None] * 5
        )
        user_team = [
            (d or lo) for d, lo in zip(user_names_duel, user_names_lo)
        ]
        opp_team = [
            (d or lo) for d, lo in zip(opp_names_duel, opp_names_lo)
        ]

        # Outcome — prefer the overview's round_N_winner signal when
        # available (it's the in-game UI's own classification), fall
        # back to disconnect detection on the duel screen.
        user_dc = _disconnect_flags_from_results(by_slug, user_duel_side)
        opp_dc = _disconnect_flags_from_results(by_slug, opp_duel_side)
        outcome = _outcome_from_disconnects(user_dc, opp_dc)
        overview_winner = overview.get(f"round{round_no}_winner")
        if overview_winner in ("left", "right") and outcome is None:
            outcome = "win" if overview_winner == user_duel_side else "loss"

        capture_quality = {
            "user_team_disconnect": user_dc,
            "opponent_team_disconnect": opp_dc,
            "user_position": user_pos,         # "top"/"bottom" on disk
            "user_duel_side": user_duel_side,  # "left"/"right" in duel
            "overview_round_winner": overview_winner,
            "overview_match_winner": overview.get("winner_name"),
        }

        payloads.append(_RoundPayload(
            round_no=round_no,
            user_username=user_player_name,
            opponent_username=opp_player_name,
            user_team=[n or "" for n in user_team],
            opponent_team=[n or "" for n in opp_team],
            user_loadout_screenshot=user_lo.file_path if user_lo else None,
            opponent_loadout_screenshot=opp_lo.file_path if opp_lo else None,
            duel_screenshot=duel_shot.file_path,
            outcome=outcome,
            is_user_lineup=is_user_lineup,
            capture_quality=capture_quality,
        ))

    return payloads


# ---------------------------------------------------------------------------
# Snapshot FK linkage
# ---------------------------------------------------------------------------


def _find_snapshot_id(
    session: Session, *, season_number: int, player_username: Optional[str],
) -> Optional[int]:
    """Find the RosterSnapshot.id for a given (season, player) pair.

    Case-insensitive username match. **Requires the snapshot to have
    actual character data** (≥1 RosterSnapshotCharacter row) — empty
    profile-only stubs from privacy-blocked scrapes don't count, since
    they don't give us the roster context that's the whole point of
    linking. Returns None when no qualifying snapshot exists; the FK
    column stays NULL and the next builder run backfills it after a
    `fetch-shiftyspad --snapshot` lands real roster data.

    Reason: when a player's "My Nikkes" is private on BlablaLink, the
    scrape still creates a RosterSnapshot row (capturing the public
    profile + outpost research) but no RosterSnapshotCharacter rows.
    Linking those FKs would put the row in the "fully snapshotted"
    bucket without us actually knowing the player's team — misleading
    when filtering for training-quality data.
    """
    if not player_username:
        return None
    from ..data.models import RosterSnapshotCharacter
    target = player_username.strip().upper()
    rows = session.exec(
        select(RosterSnapshot).where(
            RosterSnapshot.season_number == season_number,
        )
    ).all()
    for r in rows:
        if (r.player_username or "").strip().upper() != target:
            continue
        has_chars = session.exec(
            select(RosterSnapshotCharacter).where(
                RosterSnapshotCharacter.snapshot_id == r.id
            ).limit(1)
        ).first() is not None
        if has_chars:
            return r.id
    return None


# ---------------------------------------------------------------------------
# Upsert + driver
# ---------------------------------------------------------------------------


def upsert_arena_matches_for_match(
    session: Session,
    *,
    tournament: PromoTournament,
    match: PromoMatch,
    char_name_by_id: dict[int, str],
) -> int:
    """Build/refresh ArenaMatch rows for every round of one Champion
    duel. Returns count of rows touched (new + updated). Idempotent
    via the (session_id, round_index) natural key.
    """
    payloads = _build_round_payloads(session, match, char_name_by_id)
    if not payloads:
        return 0

    sid = session_id_for_duel(match.id)
    season = season_for_date(tournament.capture_date) if tournament.capture_date else None
    # Pull group_no for the human-readable label (one extra fetch per
    # match — cheap relative to OCR work already amortized).
    from ..data.models import PromoGroup
    group_no = None
    if match.group_id is not None:
        grp = session.exec(
            select(PromoGroup).where(PromoGroup.id == match.group_id)
        ).first()
        if grp is not None:
            group_no = grp.group_no

    n = 0
    for p in payloads:
        existing = session.exec(
            select(ArenaMatch).where(
                ArenaMatch.session_id == sid,
                ArenaMatch.round_index == p.round_no,
                ArenaMatch.mode == CHAMPION_MODE,
            )
        ).first()
        user_snap = (
            _find_snapshot_id(
                session, season_number=season, player_username=p.user_username,
            ) if season is not None else None
        )
        opp_snap = (
            _find_snapshot_id(
                session, season_number=season, player_username=p.opponent_username,
            ) if season is not None else None
        )

        m_no = match.match_no if match.match_no is not None else "?"
        g_no = f"g{group_no}-" if group_no is not None else ""
        date_str = f" {tournament.capture_date}" if tournament.capture_date else ""
        label = (
            f"Champions {g_no}{match.round_label} M{m_no} R{p.round_no}{date_str}"
        )
        fields = {
            "mode": CHAMPION_MODE,
            "user_username": p.user_username,
            "opponent_username": p.opponent_username,
            "user_team": p.user_team,
            "opponent_team": p.opponent_team,
            "pre_battle_screenshot": p.user_loadout_screenshot,
            "battle_record_screenshot": p.duel_screenshot,
            "capture_quality": p.capture_quality,
            "outcome": p.outcome,
            "session_id": sid,
            "session_label": label,
            "session_kind": CHAMPION_SESSION_KIND,
            "round_index": p.round_no,
            "captured_at": tournament.captured_at,
            "is_user_lineup": p.is_user_lineup,
            "user_snapshot_id": user_snap,
            "opponent_snapshot_id": opp_snap,
        }

        if existing is None:
            row = ArenaMatch(**fields)
            session.add(row)
        else:
            for k, v in fields.items():
                setattr(existing, k, v)
            session.add(existing)
        n += 1
    session.commit()
    return n


@dataclass
class ChampionBuildStats:
    matches_processed: int = 0      # Champion PromoMatches walked
    rows_touched: int = 0           # ArenaMatch rows new+updated
    rows_with_outcome: int = 0
    rows_fully_snapshotted: int = 0  # both user_snapshot_id + opp_snapshot_id set
    rows_user_snapshot_only: int = 0
    rows_opp_snapshot_only: int = 0


def build_arena_matches_for_tournament(
    session: Session, tournament: PromoTournament,
) -> int:
    """Walk every Champion PromoMatch in a tournament + build/refresh
    its ArenaMatch rows. Returns total rows touched."""
    matches = session.exec(
        select(PromoMatch).where(
            PromoMatch.tournament_id == tournament.id,
        ).order_by(PromoMatch.id)
    ).all()
    char_name_by_id = {
        c.id: c.name for c in session.exec(select(Character)).all()
    }
    n = 0
    for m in matches:
        if m.round_label == "rookie":
            continue  # rookie has its own builder
        n += upsert_arena_matches_for_match(
            session,
            tournament=tournament,
            match=m,
            char_name_by_id=char_name_by_id,
        )
    return n


def build_arena_matches_for_all_champion_tournaments(
    engine, *, only_tournament_id: Optional[int] = None,
) -> ChampionBuildStats:
    """Walk every non-rookie PromoTournament and build its ArenaMatch
    rows. Returns a summary stats object.
    """
    from .promo_tournament_ingest import FORMAT_ROOKIE_ARENA, tournament_format

    stats = ChampionBuildStats()
    with Session(engine) as session:
        tournaments = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) != FORMAT_ROOKIE_ARENA
            and (only_tournament_id is None or t.id == only_tournament_id)
        ]
        for t in tournaments:
            n = build_arena_matches_for_tournament(session, t)
            stats.matches_processed += n  # rows touched per tournament
            log.info(
                "champion ArenaMatch builder: tid=%s → %d rows", t.id, n,
            )
        stats.rows_touched = stats.matches_processed

        # Post-build audit — count outcome and snapshot fill rates so
        # the user (and CLI) can see what's "fully labeled" vs "partial."
        for am in session.exec(
            select(ArenaMatch).where(ArenaMatch.mode == CHAMPION_MODE)
        ).all():
            if am.outcome:
                stats.rows_with_outcome += 1
            us = am.user_snapshot_id is not None
            os_ = am.opponent_snapshot_id is not None
            if us and os_:
                stats.rows_fully_snapshotted += 1
            elif us:
                stats.rows_user_snapshot_only += 1
            elif os_:
                stats.rows_opp_snapshot_only += 1

    return stats
