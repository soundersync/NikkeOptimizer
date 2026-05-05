"""Import arena screenshots into the local DB.

Walks a directory of arena screenshots, runs ``detect_title`` to figure out
which mode each is in, then dispatches to the appropriate extractor and
upserts ``ArenaMatch`` rows. Captures with low-confidence portrait matches
get ``needs_review=True`` so the manual-correction UI can surface them.

Champion 'Arena Info' captures store ONLY the user_team (opponent_team is
left empty). Pre-battle captures (rookie/special) populate both teams.
Champions Battle Records screens persist as their own rows tagged with
``mode='champion_battle_record'`` and the per-matchup payload stashed in
``raw_battle_record``. Champions Duel Result is a single aggregate row per
session.

Session grouping (slice #135): every importer call accepts ``session_id``
and ``session_label`` so all rows from one upload batch share the same
session, enabling completeness validation across the 16-screenshot
Champions Duel and the "predictions awaiting results" workflow.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image
from sqlmodel import select

from ..data.config import get_self_username
from ..data.db import get_session, init_db, make_engine
from ..data.models import ArenaMatch, Character, OwnedCharacter
from .arena import (
    ArenaInfoTeam,
    ArenaPreBattle,
    ChampionsDuelResult,
    TeamLineup,
    detect_title,
    extract_champion_arena_info,
    extract_champions_duel_result,
    extract_pre_battle,
)
from .battle_records import BattleRecordsRound, extract_battle_records
from .portrait_matcher import PortraitMatcher

log = logging.getLogger(__name__)


@dataclass
class ArenaImportReport:
    files_seen: int = 0
    rookie: int = 0
    special: int = 0
    champion: int = 0
    champion_battle_record: int = 0
    champion_duel_result: int = 0
    skipped: int = 0
    needs_review: int = 0
    session_id: Optional[str] = None
    session_kind: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        log.warning(msg)
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return {
            "files_seen": self.files_seen,
            "rookie": self.rookie,
            "special": self.special,
            "champion": self.champion,
            "champion_battle_record": self.champion_battle_record,
            "champion_duel_result": self.champion_duel_result,
            "skipped": self.skipped,
            "needs_review": self.needs_review,
            "session_id": self.session_id,
            "session_kind": self.session_kind,
            "warnings": self.warnings,
        }


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _team_quality(lineup: TeamLineup) -> dict:
    """Serialize per-cell extraction metadata for the capture_quality field."""
    return {
        "characters": list(lineup.characters),
        "best_matches": list(lineup.best_matches),
        "distances": [
            None if d is None else float(d) for d in lineup.portrait_distances
        ],
    }


def _team_needs_review(lineup: TeamLineup) -> bool:
    return any(c is None for c in lineup.characters)


# CP auto-confirm tolerance — owned power is reasonably stable but small
# fluctuations from sync changes etc. happen. ±5% is loose enough to handle
# typical drift without falsely promoting wrong matches.
_CP_MATCH_TOLERANCE = 0.05
# Minimum number of user-team cells with CP-matching their best-portrait
# match before we accept the team as the user's own (when user_username
# doesn't match the configured self).
_SELF_TEAM_CP_MATCHES_REQUIRED = 3


def _owned_power_index(session) -> dict[str, int]:
    """Map character_name -> owned power, for CP cross-validation."""
    chars_by_id = {c.id: c.name for c in session.exec(select(Character)).all()}
    out: dict[str, int] = {}
    for o in session.exec(select(OwnedCharacter)).all():
        name = chars_by_id.get(o.character_id)
        if name and o.power is not None:
            out[name] = o.power
    return out


def _is_user_team(
    lineup: TeamLineup,
    captured_username: Optional[str],
    owned_power: dict[str, int],
) -> bool:
    """Decide whether ``lineup`` is the user's own team.

    Two paths:
      1. If the configured self-username (env var or
         ``<user_data_dir>/config.json``) matches the captured username
         (case-insensitive), the team is ours.
      2. Fallback heuristic: if ≥3 of 5 cells have a captured CP that
         matches our owned CP for the rank-1 portrait match, the team
         is most likely ours regardless of username detection.
    """
    configured = get_self_username()
    if (
        configured
        and captured_username
        and captured_username.strip().upper() == configured.strip().upper()
    ):
        return True
    # Heuristic fallback: count CP matches against our roster.
    matches = 0
    for cap_name, cap_power in zip(lineup.best_matches, lineup.cell_powers):
        if cap_name and cap_power is not None:
            owned = owned_power.get(cap_name)
            if owned is None or owned == 0:
                continue
            if abs(owned - cap_power) / owned <= _CP_MATCH_TOLERANCE:
                matches += 1
    return matches >= _SELF_TEAM_CP_MATCHES_REQUIRED


def _cp_auto_confirm(
    lineup: TeamLineup,
    owned_power: dict[str, int],
    *,
    report: Optional[ArenaImportReport] = None,
) -> int:
    """Promote borderline matches to confirmed when CP cross-validates.

    For each user-team cell that the matcher couldn't confidently identify,
    check whether the captured per-cell CP matches the owned CP for the
    *rank-1 portrait candidate* (best_match) within ``_CP_MATCH_TOLERANCE``.
    When it does, promote the rank-1 candidate to ``characters[i]`` so the
    cell is treated as confirmed downstream.

    Returns the number of cells promoted. Mutates ``lineup`` in place.
    """
    promoted = 0
    for i, current in enumerate(lineup.characters):
        if current is not None:
            continue  # already confident — leave it alone
        best = lineup.best_matches[i]
        if not best:
            continue
        cap_power = lineup.cell_powers[i]
        owned = owned_power.get(best)
        if cap_power is None or owned is None or owned == 0:
            continue
        if abs(owned - cap_power) / owned <= _CP_MATCH_TOLERANCE:
            lineup.characters[i] = best
            promoted += 1
            if report is not None:
                report.warn(
                    f"CP auto-confirm slot {i+1}: '{best}' "
                    f"(captured CP {cap_power:,} ≈ owned CP {owned:,})"
                )
    return promoted


def _team_to_list(lineup: TeamLineup) -> list[str]:
    """Serialize a 5-cell lineup as a positional list.

    Each entry is the confident match when present, else the best-match
    candidate, else an empty string. Empty strings preserve slot positions so
    downstream code can map cell-N to a specific character in the screenshot
    even when one cell failed to match.
    """
    out: list[str] = []
    for confident, best in zip(lineup.characters, lineup.best_matches):
        out.append(confident or best or "")
    return out


def _persist_pre_battle(
    session, capture: ArenaPreBattle, image_path: Path,
    *, report: Optional[ArenaImportReport] = None,
) -> ArenaMatch:
    # CP cross-validation auto-confirm — only on the user-side team.
    # Promotes borderline matches when captured CP matches owned CP.
    owned_power = _owned_power_index(session)
    if _is_user_team(
        capture.user_team, capture.user_team.player_username, owned_power
    ):
        _cp_auto_confirm(capture.user_team, owned_power, report=report)
    review = _team_needs_review(capture.user_team) or _team_needs_review(
        capture.opponent_team
    )
    row = ArenaMatch(
        mode=capture.mode,
        user_username=capture.user_team.player_username,
        opponent_username=capture.opponent_team.player_username,
        user_team=_team_to_list(capture.user_team),
        opponent_team=_team_to_list(capture.opponent_team),
        user_power=capture.user_team.power,
        opponent_power=capture.opponent_team.power,
        user_team_powers=list(capture.user_team.cell_powers),
        opponent_team_powers=list(capture.opponent_team.cell_powers),
        pre_battle_screenshot=str(image_path),
        capture_quality={
            "user": _team_quality(capture.user_team),
            "opponent": _team_quality(capture.opponent_team),
            "title_ocr": capture.raw_title_ocr,
        },
        needs_review=review,
    )
    session.add(row)
    return row


def _persist_champion(
    session, capture: ArenaInfoTeam, image_path: Path,
    *, report: Optional[ArenaImportReport] = None,
) -> ArenaMatch:
    # Champions captures are always single-team — could be either the
    # user's own lineup or an opponent's. CP cross-validation will
    # confirm which by counting matches against the owned roster.
    owned_power = _owned_power_index(session)
    is_user = _is_user_team(capture.team, capture.player_username, owned_power)
    if is_user:
        _cp_auto_confirm(capture.team, owned_power, report=report)
    # Persist is_user_lineup as a tristate when there's literally no info
    # to decide on (no username AND no overlap with owned roster) — that
    # leaves the matrix to render the cell as "unknown" instead of
    # forcing it into the wrong column.
    has_signal = bool(
        capture.player_username
        or any(p for p in capture.team.cell_powers if p)
    )
    review = _team_needs_review(capture.team)
    row = ArenaMatch(
        mode=capture.mode,
        user_username=capture.player_username,
        user_team=_team_to_list(capture.team),
        user_power=capture.total_power,
        user_team_powers=list(capture.team.cell_powers),
        round_index=capture.round_index,
        pre_battle_screenshot=str(image_path),
        capture_quality={
            "user": _team_quality(capture.team),
        },
        needs_review=review,
        is_user_lineup=is_user if has_signal else None,
    )
    session.add(row)
    return row


def _persist_battle_records(
    session, capture: BattleRecordsRound, image_path: Path,
) -> ArenaMatch:
    """Persist a Battle Records (Champions per-round result) screen.

    Stored as its own ``ArenaMatch`` row tagged ``mode='champion_battle_record'``.
    The full per-matchup payload lives in ``raw_battle_record`` so the
    schema doesn't grow new columns. Per-Nikke names land in user_team /
    opponent_team for cross-referencing with the matching loadout rows.
    """
    my_team = [m.my_nikke or "" for m in capture.matchups]
    opp_team = [m.opponent_nikke or "" for m in capture.matchups]
    # Pad to 5 in case extraction returned fewer rows.
    while len(my_team) < 5:
        my_team.append("")
    while len(opp_team) < 5:
        opp_team.append("")
    needs_review = any(not n for n in my_team) or any(not n for n in opp_team)
    row = ArenaMatch(
        mode=capture.mode,
        round_index=capture.round_index,
        user_team=my_team[:5],
        opponent_team=opp_team[:5],
        battle_record_screenshot=str(image_path),
        raw_battle_record={
            "matchups": [m.to_dict() for m in capture.matchups],
        },
        needs_review=needs_review,
    )
    session.add(row)
    return row


def _persist_duel_result(
    session, capture: ChampionsDuelResult, image_path: Path,
) -> ArenaMatch:
    """Persist a Champions Duel Result aggregate screen.

    One row per session — the overall winner badge + reference to the
    screenshot. Per-round mini-summaries are deferred (they're shown on
    the Battle Records screens already).
    """
    row = ArenaMatch(
        mode=capture.mode,
        battle_record_screenshot=str(image_path),
        outcome=(
            "win" if capture.user_won_overall is True
            else "loss" if capture.user_won_overall is False
            else None
        ),
        needs_review=False,  # nothing here for the user to manually fix
    )
    session.add(row)
    return row


# Session-kind values.
SESSION_KIND_PREDICTIONS = "predictions"
SESSION_KIND_PARTIAL = "partial"
SESSION_KIND_COMPLETE = "complete"


def compute_session_kind(rows: list[ArenaMatch]) -> Optional[str]:
    """Decide the ``session_kind`` for a Champions session given its rows.

    A "complete" Duel has 10 loadouts (P1 + P2 × rounds 1-5) AND 5 round
    Battle Records AND 1 Duel Result. "Predictions" means loadouts only
    (any number of them, no result screens). "Partial" is anything in
    between (some results present but not all). Non-Champions sessions
    return None.
    """
    if not rows or not any(r.mode and r.mode.startswith("champion") for r in rows):
        return None
    loadouts = [r for r in rows if r.mode == "champion"]
    results = [r for r in rows if r.mode == "champion_battle_record"]
    duel = [r for r in rows if r.mode == "champion_duel_result"]
    if not results and not duel:
        return SESSION_KIND_PREDICTIONS if loadouts else None
    if len(results) >= 5 and len(duel) >= 1 and len(loadouts) >= 10:
        return SESSION_KIND_COMPLETE
    return SESSION_KIND_PARTIAL


def _refresh_session_kind(session, session_id: str) -> Optional[str]:
    """Recompute and persist session_kind for every row in a session.

    Also fills in missing round_index on Battle Records rows by trying
    two strategies, in order:
      1. Match BR's user_team to a champion-loadout row's user_team
         within the same session (same teams = same round). Uses
         Jaccard similarity ≥ 0.6 as the confidence bar.
      2. Sequential assignment: any remaining BR rows without a round
         take the next free slot from {1..5}, ordered by row.id (which
         tracks upload order since IDs auto-increment).
    """
    rows = list(
        session.exec(
            select(ArenaMatch).where(ArenaMatch.session_id == session_id)
        ).all()
    )
    _backfill_battle_records_rounds(session, rows)
    kind = compute_session_kind(rows)
    for r in rows:
        if r.session_kind != kind:
            r.session_kind = kind
            session.add(r)
    return kind


def _backfill_battle_records_rounds(session, rows: list[ArenaMatch]) -> None:
    """Assign round_index to Battle Records rows that lack one.

    The Battle Records screen doesn't print a round number anywhere
    extractable, so we fall back to (a) team-membership matching with
    the champion-loadout rows we already have, then (b) sequential
    assignment over any remaining 1..5 slots.
    """
    br_rows = [r for r in rows if r.mode == "champion_battle_record"]
    if not br_rows:
        return
    loadouts = [
        r for r in rows
        if r.mode == "champion" and r.round_index in (1, 2, 3, 4, 5)
    ]
    # Group loadouts by round so we can build a round → set-of-team-names
    # signature.
    round_signatures: dict[int, set[str]] = {}
    for ld in loadouts:
        sig = round_signatures.setdefault(ld.round_index, set())
        for name in ld.user_team or []:
            if name:
                sig.add(name)
    used_rounds: set[int] = {r.round_index for r in br_rows if r.round_index}

    # Pass 1 — content-based matching.
    for br in br_rows:
        if br.round_index is not None:
            continue
        # Build a combined team signature from BOTH sides of the BR row
        # (user_team + opponent_team) so we can match against either
        # player's loadout.
        br_sig = {n for n in (br.user_team or []) if n}
        br_sig |= {n for n in (br.opponent_team or []) if n}
        if not br_sig:
            continue
        best_round, best_score = None, 0.0
        for round_idx, sig in round_signatures.items():
            if not sig:
                continue
            inter = len(br_sig & sig)
            union = len(br_sig | sig)
            score = inter / union if union else 0.0
            if score > best_score:
                best_round, best_score = round_idx, score
        if best_round is not None and best_score >= 0.6 and best_round not in used_rounds:
            br.round_index = best_round
            used_rounds.add(best_round)
            session.add(br)

    # Pass 2 — sequential fallback over remaining 1..5 slots.
    remaining = [n for n in (1, 2, 3, 4, 5) if n not in used_rounds]
    leftover_brs = [r for r in br_rows if r.round_index is None]
    leftover_brs.sort(key=lambda r: r.id or 0)
    for br, slot in zip(leftover_brs, remaining):
        br.round_index = slot
        session.add(br)


def import_arena_screenshots(
    paths: Iterable[Path],
    matcher: PortraitMatcher,
    *,
    db_path: Optional[Path] = None,
    user_username: str = "NIKA",
    mode_hint: Optional[str] = None,
    session_id: Optional[str] = None,
    session_label: Optional[str] = None,
) -> ArenaImportReport:
    """Run the appropriate extractor on each screenshot and persist the result.

    ``mode_hint`` (one of ``"rookie"``/``"sp"``/``"champions"``) lets the
    caller bypass auto-detection when the upload form already says what
    PvP mode this batch belongs to. The detector still runs for accuracy,
    but its result is overridden when out of family.

    ``session_id`` groups all created rows under one session — when not
    supplied a UUID is generated. The session kind (predictions / partial
    / complete) is computed across the full session after every row is
    inserted so an "Add results" upload promotes a predictions session
    to complete automatically.
    """
    engine = make_engine(db_path)
    init_db(engine)
    report = ArenaImportReport()

    paths = list(paths)
    report.files_seen = len(paths)

    # Generate a session id if the caller didn't provide one. Even for
    # non-Champions modes this lets the dashboard surface "this batch"
    # later — sessions are cheap and orthogonal to capture mode.
    if session_id is None:
        session_id = uuid.uuid4().hex
    report.session_id = session_id

    with get_session(session_engine := engine) as session:
        # Cache the Character.name list once per import run — used by the
        # Battle Records extractor's OCR-name lookup. Far cheaper than
        # round-tripping for every cell.
        known_names = [c.name for c in session.exec(select(Character)).all()]
        for path in paths:
            try:
                image = Image.open(path).convert("RGB")
                mode, _ = detect_title(image)
            except Exception as exc:  # noqa: BLE001
                report.skipped += 1
                report.warn(f"{path.name}: open/detect failed: {exc}")
                continue

            # Honor mode_hint when the title detector returned 'unknown' or
            # picked a class outside the hint's family. We never override
            # an unrelated specific detection (e.g. if title says rookie
            # but hint says champions, trust the title — see screenshot_router
            # for the same policy).
            mode = _apply_mode_hint(mode, mode_hint)

            try:
                row: Optional[ArenaMatch] = None
                if mode in ("rookie", "special"):
                    capture = extract_pre_battle(
                        path, matcher, user_username=user_username
                    )
                    if capture is None:
                        report.skipped += 1
                        report.warn(f"{path.name}: pre-battle extractor returned None")
                        continue
                    row = _persist_pre_battle(session, capture, path, report=report)
                    if mode == "rookie":
                        report.rookie += 1
                    else:
                        report.special += 1
                elif mode == "champion":
                    capture = extract_champion_arena_info(path, matcher)
                    if capture is None:
                        report.skipped += 1
                        report.warn(f"{path.name}: champion extractor returned None")
                        continue
                    row = _persist_champion(session, capture, path, report=report)
                    report.champion += 1
                elif mode == "champion_battle_record":
                    br = extract_battle_records(
                        path, matcher,
                        known_character_names=known_names,
                    )
                    if br is None:
                        report.skipped += 1
                        report.warn(
                            f"{path.name}: battle-records extractor returned None"
                        )
                        continue
                    row = _persist_battle_records(session, br, path)
                    report.champion_battle_record += 1
                elif mode == "champion_duel_result":
                    dr = extract_champions_duel_result(path)
                    if dr is None:
                        report.skipped += 1
                        report.warn(
                            f"{path.name}: duel-result extractor returned None"
                        )
                        continue
                    row = _persist_duel_result(session, dr, path)
                    report.champion_duel_result += 1
                else:
                    report.skipped += 1
                    report.warn(f"{path.name}: unrecognized mode {mode!r}")
                    continue
            except Exception as exc:  # noqa: BLE001
                report.skipped += 1
                report.warn(f"{path.name}: extractor crashed: {exc}")
                continue

            if row is not None:
                row.session_id = session_id
                if session_label:
                    row.session_label = session_label
                session.add(row)
                if row.needs_review:
                    report.needs_review += 1

        # Flush so the session-kind recompute sees the freshly inserted
        # rows alongside any pre-existing rows that share the session_id.
        session.flush()
        report.session_kind = _refresh_session_kind(session, session_id)
        session.commit()

    return report


_HINT_FAMILIES = {
    "rookie": {"rookie"},
    "sp": {"special"},
    "special": {"special"},
    "champions": {
        "champion",
        "champion_battle_record",
        "champion_duel_result",
    },
}


def _apply_mode_hint(detected: str, hint: Optional[str]) -> str:
    """Optionally promote a detector miss to a hint-family default mode."""
    if not hint:
        return detected
    family = _HINT_FAMILIES.get(hint.lower())
    if family is None:
        return detected
    if detected in family:
        return detected
    if detected == "unknown":
        # Hint says this is Champions but title OCR couldn't classify —
        # default to the loadout extractor; it returns None on mismatch
        # so a misrouted file is harmless.
        if hint.lower() == "champions":
            return "champion"
        if hint.lower() == "rookie":
            return "rookie"
        if hint.lower() in ("sp", "special"):
            return "special"
    return detected


def import_arena_directory(
    directory: Path,
    matcher: PortraitMatcher,
    *,
    db_path: Optional[Path] = None,
    user_username: str = "NIKA",
    mode_hint: Optional[str] = None,
    session_id: Optional[str] = None,
    session_label: Optional[str] = None,
) -> ArenaImportReport:
    """Glob a directory tree for arena screenshots and import them all.

    All discovered files are bundled into a single session — useful for
    importing one Champions Duel folder in one shot from the CLI.
    """
    paths: list[Path] = []
    for p in directory.rglob("*"):
        if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES:
            paths.append(p)
    return import_arena_screenshots(
        sorted(paths),
        matcher,
        db_path=db_path,
        user_username=user_username,
        mode_hint=mode_hint,
        session_id=session_id,
        session_label=session_label,
    )
