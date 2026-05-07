"""Promotion Tournament ingest — relocate + persist.

Walks ``<staging_root>/promotion_tournament_<TS>/`` folders, copies (or
moves) the source PNGs into the canonical archive layout
``<archive_root>/<YYYY-MM-DD>/promotion_tournament/group_*/round_*/match_*/``,
filters out coord-picker leftovers (``__crop.png`` / ``__masked.png``),
then upserts ``PromoTournament`` / ``PromoGroup`` / ``PromoMatch`` /
``PromoMatchScreenshot`` rows.

All natural keys are normalized so the ingest is idempotent — re-running
is safe and a no-op when nothing has changed.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from sqlmodel import Session, select

from ..data.db import init_db, make_engine
from ..data.models import (
    PromoGroup,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
)

log = logging.getLogger(__name__)


_STAGING_NAME_RE = re.compile(
    r"^(promotion_tournament|champions_duel)_(\d{8})_(\d{6})$"
)
_GROUP_NAME_RE = re.compile(r"^group_(\d+)$")
# Match folders use ``match_1`` in promotion_tournament but ``match1`` in
# champions_duel — accept both.
_MATCH_NAME_RE = re.compile(r"^match_?(\d+)$")
_PLAYER_FILE_RE = re.compile(r"^round_(\d+)\.png$", re.IGNORECASE)
_DUEL_FILE_RE = re.compile(r"^duel_(\d+)\.png$", re.IGNORECASE)
_OVERVIEW_FILE_NAME = "overview.png"
_DERIVED_MARKER = "__"  # files whose stem contains "__" are coord-picker output

# Round labels used by each format. Per-format tuples drive the walker;
# all values are stored verbatim in PromoMatch.round_label so the UI can
# branch on format (derived from storage_root folder name).
_ROUND_LABELS_PROMO = ("round_64", "top_32", "top_16")
_ROUND_LABELS_DUEL = ("quarterfinals", "semifinals", "finals")
# Round labels that are a single aggregated results-only folder (no
# match_N subfolders). top_16 in promo, finals in duel.
_AGGREGATED_ROUNDS = {"top_16", "finals"}
# Round labels that DON'T have player-loadout folders (results-only).
# top_32 in promo (per inventory), finals in duel.
_RESULTS_ONLY_ROUNDS = {"top_32", "finals"}

# Format keys, mirrored in tournament_format(). Single source of truth.
FORMAT_PROMO = "promotion_tournament"
FORMAT_DUEL = "champions_duel"


def tournament_format(storage_root: str) -> str:
    """Return ``'promotion_tournament'`` or ``'champions_duel'`` for a path.

    The format is encoded in the archive folder name (e.g.
    ``<archive>/<date>/champions_duel/...``). Cheaper than a DB column
    and impossible to drift from filesystem reality.
    """
    name = Path(storage_root).name
    if name.startswith(FORMAT_DUEL):
        return FORMAT_DUEL
    return FORMAT_PROMO


@dataclass
class IngestStats:
    tournaments: int = 0
    groups: int = 0
    matches: int = 0
    screenshots: int = 0
    files_copied: int = 0
    files_skipped: int = 0
    files_moved_deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [
            f"tournaments={self.tournaments}",
            f"groups={self.groups}",
            f"matches={self.matches}",
            f"screenshots={self.screenshots}",
            f"copied={self.files_copied}",
            f"skipped={self.files_skipped}",
        ]
        if self.files_moved_deleted:
            parts.append(f"deleted={self.files_moved_deleted}")
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest_root(
    staging_root: Path,
    *,
    archive_root: Optional[Path] = None,
    move: bool = False,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> IngestStats:
    """Relocate every ``promotion_tournament_*`` folder under ``staging_root``
    into ``archive_root`` and persist DB rows.

    ``archive_root`` defaults to ``<staging_root>/../captures``. The
    intent is for ``staging_root = <repo>/champion_arena`` and
    ``archive_root = <repo>/captures``.
    """
    staging_root = Path(staging_root).resolve()
    if archive_root is None:
        archive_root = staging_root.parent / "captures"
    archive_root = Path(archive_root).resolve()
    archive_root.mkdir(parents=True, exist_ok=True)

    stats = IngestStats()
    engine = make_engine(db_path)
    init_db(engine)

    # Discover staging tournaments first.
    staged = _discover_staging(staging_root)

    # Relocate each one. Note: ingest_root also picks up tournaments
    # that already exist under archive_root with no staging counterpart,
    # so users can run after manually placing files.
    for src in staged:
        match = _STAGING_NAME_RE.match(src.name)
        if match is None:
            stats.errors.append(f"unrecognized staging folder: {src.name}")
            continue
        fmt, ymd, hms = match.group(1), match.group(2), match.group(3)
        captured_at = datetime.strptime(f"{ymd}{hms}", "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
        dest_dir = _resolve_archive_dir(
            archive_root, captured_at.date().isoformat(), fmt=fmt, force=force
        )
        try:
            file_stats = _relocate(src, dest_dir, move=move)
        except FileExistsError as exc:
            stats.errors.append(str(exc))
            continue
        stats.files_copied += file_stats.copied
        stats.files_skipped += file_stats.skipped
        stats.files_moved_deleted += file_stats.deleted

        with Session(engine) as session:
            _persist_tournament(
                session,
                stats=stats,
                storage_root=dest_dir,
                captured_at=captured_at,
                source_root=src,
            )
            session.commit()

    # Also pick up any tournaments already in the archive that don't
    # have a corresponding staging folder — keeps DB in sync if the
    # user moved files manually.
    for archived in _discover_archived(archive_root):
        with Session(engine) as session:
            already = session.exec(
                select(PromoTournament).where(
                    PromoTournament.storage_root == str(archived)
                )
            ).first()
            if already is not None:
                continue
            captured_at = _infer_captured_at_from_archive(archived)
            _persist_tournament(
                session,
                stats=stats,
                storage_root=archived,
                captured_at=captured_at,
                source_root=None,
            )
            session.commit()

    return stats


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_staging(staging_root: Path) -> list[Path]:
    if not staging_root.is_dir():
        return []
    return sorted(
        p for p in staging_root.iterdir()
        if p.is_dir() and _STAGING_NAME_RE.match(p.name)
    )


def _discover_archived(archive_root: Path) -> list[Path]:
    """Yield ``<archive>/<date>/<format>[_N]/`` folders for both formats."""
    if not archive_root.is_dir():
        return []
    out: list[Path] = []
    for date_dir in sorted(archive_root.iterdir()):
        if not date_dir.is_dir():
            continue
        for fmt_dir in sorted(date_dir.iterdir()):
            if not fmt_dir.is_dir():
                continue
            if fmt_dir.name.startswith(FORMAT_PROMO) or fmt_dir.name.startswith(
                FORMAT_DUEL
            ):
                out.append(fmt_dir)
    return out


def _resolve_archive_dir(
    archive_root: Path, date_iso: str, *, fmt: str, force: bool
) -> Path:
    """Return ``<archive>/<date>/<fmt>[_N]/``.

    ``fmt`` is the format key (``promotion_tournament`` or
    ``champions_duel``). If the base folder already exists and ``force``
    is set, a numbered suffix is appended (``_2``, ``_3``, …). Otherwise
    the base path is returned regardless — relocation handles
    same-source idempotency at the file level.
    """
    base = archive_root / date_iso / fmt
    if not base.exists() or not force:
        return base
    n = 2
    while (cand := archive_root / date_iso / f"{fmt}_{n}").exists():
        n += 1
    return cand


# ---------------------------------------------------------------------------
# Relocation
# ---------------------------------------------------------------------------


@dataclass
class _FileStats:
    copied: int = 0
    skipped: int = 0
    deleted: int = 0


def _relocate(src: Path, dest: Path, *, move: bool) -> _FileStats:
    """Copy every relevant .png from ``src`` tree into the matching path
    under ``dest``. Returns per-file stats."""
    stats = _FileStats()
    dest.mkdir(parents=True, exist_ok=True)
    for src_file in _iter_source_pngs(src):
        rel = src_file.relative_to(src)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_size == src_file.stat().st_size:
            stats.skipped += 1
        else:
            shutil.copy2(src_file, out)
            stats.copied += 1
        if move:
            try:
                src_file.unlink()
                stats.deleted += 1
            except OSError as exc:
                log.warning("failed to delete %s after copy: %s", src_file, exc)
    return stats


def _iter_source_pngs(src_root: Path) -> Iterable[Path]:
    """Yield only the *original* .png files under src_root.

    Skips ``__crop.png`` / ``__masked.png`` (coord-picker output) and
    .DS_Store. Order is deterministic.
    """
    for p in sorted(src_root.rglob("*.png")):
        if _DERIVED_MARKER in p.stem:
            continue
        if p.name.lower().startswith("."):
            continue
        yield p


# ---------------------------------------------------------------------------
# DB upserts
# ---------------------------------------------------------------------------


def _persist_tournament(
    session: Session,
    *,
    stats: IngestStats,
    storage_root: Path,
    captured_at: datetime,
    source_root: Optional[Path],
) -> None:
    storage_str = str(storage_root)
    tournament = session.exec(
        select(PromoTournament).where(PromoTournament.storage_root == storage_str)
    ).first()
    if tournament is None:
        tournament = PromoTournament(
            captured_at=captured_at,
            capture_date=captured_at.date(),
            storage_root=storage_str,
            source_root=str(source_root) if source_root is not None else None,
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)
        stats.tournaments += 1
    elif source_root is not None and tournament.source_root != str(source_root):
        # Update traceability if the user re-ingests after moving.
        tournament.source_root = str(source_root)
        session.add(tournament)
        session.commit()

    if not storage_root.is_dir():
        return  # archive folder vanished between detection + persist

    fmt = tournament_format(str(storage_root))
    if fmt == FORMAT_PROMO:
        for group_dir in sorted(p for p in storage_root.iterdir() if p.is_dir()):
            m = _GROUP_NAME_RE.match(group_dir.name)
            if m is None:
                continue
            group_no = int(m.group(1))
            group = _upsert_group(session, tournament.id, group_no, stats)
            for round_dir in sorted(p for p in group_dir.iterdir() if p.is_dir()):
                label = round_dir.name
                if label not in _ROUND_LABELS_PROMO:
                    continue
                _persist_round(
                    session, tournament.id, group.id, label, round_dir, stats
                )
    else:
        # Champions Duel — no group level. Synthesize a single
        # PromoGroup (group_no=1) so PromoMatch.group_id stays
        # non-null; the UI hides the group page for duel tournaments.
        group = _upsert_group(session, tournament.id, 1, stats)
        for round_dir in sorted(p for p in storage_root.iterdir() if p.is_dir()):
            label = round_dir.name
            if label not in _ROUND_LABELS_DUEL:
                continue
            _persist_round(
                session, tournament.id, group.id, label, round_dir, stats
            )


def _upsert_group(
    session: Session, tournament_id: int, group_no: int, stats: IngestStats
) -> PromoGroup:
    group = session.exec(
        select(PromoGroup).where(
            PromoGroup.tournament_id == tournament_id,
            PromoGroup.group_no == group_no,
        )
    ).first()
    if group is None:
        group = PromoGroup(tournament_id=tournament_id, group_no=group_no)
        session.add(group)
        session.commit()
        session.refresh(group)
        stats.groups += 1
    return group


def _persist_round(
    session: Session,
    tournament_id: int,
    group_id: int,
    round_label: str,
    round_dir: Path,
    stats: IngestStats,
) -> None:
    """Walk a round folder.

    Aggregated rounds (``top_16``, ``finals``) contain a single
    ``results/`` directly with no ``match_N`` subfolders. Other rounds
    contain ``match_K`` (or ``matchK``) subfolders with their own
    ``player_top`` / ``player_bottom`` / ``results``.
    """
    if round_label in _AGGREGATED_ROUNDS:
        # Single aggregated match.
        results_dir = round_dir / "results"
        if results_dir.is_dir():
            match = _upsert_match(
                session,
                tournament_id=tournament_id,
                group_id=group_id,
                round_label=round_label,
                match_no=None,
                has_loadouts=False,
                stats=stats,
            )
            _persist_results(session, match.id, results_dir, stats)
        return

    round_supports_loadouts = round_label not in _RESULTS_ONLY_ROUNDS

    for match_dir in sorted(p for p in round_dir.iterdir() if p.is_dir()):
        m = _MATCH_NAME_RE.match(match_dir.name)
        if m is None:
            continue
        match_no = int(m.group(1))
        loadouts_present = (match_dir / "player_top").is_dir() or (
            match_dir / "player_bottom"
        ).is_dir()
        match = _upsert_match(
            session,
            tournament_id=tournament_id,
            group_id=group_id,
            round_label=round_label,
            match_no=match_no,
            has_loadouts=loadouts_present and round_supports_loadouts,
            stats=stats,
        )
        if loadouts_present:
            _persist_loadouts(session, match.id, match_dir, stats)
        results_dir = match_dir / "results"
        if results_dir.is_dir():
            _persist_results(session, match.id, results_dir, stats)


def _upsert_match(
    session: Session,
    *,
    tournament_id: int,
    group_id: int,
    round_label: str,
    match_no: Optional[int],
    has_loadouts: bool,
    stats: IngestStats,
) -> PromoMatch:
    stmt = select(PromoMatch).where(
        PromoMatch.tournament_id == tournament_id,
        PromoMatch.group_id == group_id,
        PromoMatch.round_label == round_label,
    )
    if match_no is None:
        stmt = stmt.where(PromoMatch.match_no.is_(None))
    else:
        stmt = stmt.where(PromoMatch.match_no == match_no)
    match = session.exec(stmt).first()
    if match is None:
        match = PromoMatch(
            tournament_id=tournament_id,
            group_id=group_id,
            round_label=round_label,
            match_no=match_no,
            has_loadouts=has_loadouts,
        )
        session.add(match)
        session.commit()
        session.refresh(match)
        stats.matches += 1
    elif match.has_loadouts != has_loadouts:
        match.has_loadouts = has_loadouts
        session.add(match)
        session.commit()
    return match


def _persist_loadouts(
    session: Session, match_id: int, match_dir: Path, stats: IngestStats
) -> None:
    for side in ("top", "bottom"):
        side_dir = match_dir / f"player_{side}"
        if not side_dir.is_dir():
            continue
        for png in sorted(side_dir.glob("*.png")):
            if _DERIVED_MARKER in png.stem:
                continue
            m = _PLAYER_FILE_RE.match(png.name)
            if m is None:
                continue
            round_no = int(m.group(1))
            _upsert_screenshot(
                session,
                match_id=match_id,
                kind="player_loadout",
                side=side,
                round_no=round_no,
                file_path=png,
                stats=stats,
            )


def _persist_results(
    session: Session, match_id: int, results_dir: Path, stats: IngestStats
) -> None:
    for png in sorted(results_dir.glob("*.png")):
        if _DERIVED_MARKER in png.stem:
            continue
        if png.name == _OVERVIEW_FILE_NAME:
            _upsert_screenshot(
                session,
                match_id=match_id,
                kind="results_overview",
                side=None,
                round_no=None,
                file_path=png,
                stats=stats,
            )
            continue
        m = _DUEL_FILE_RE.match(png.name)
        if m is None:
            continue
        round_no = int(m.group(1))
        _upsert_screenshot(
            session,
            match_id=match_id,
            kind="results_duel",
            side=None,
            round_no=round_no,
            file_path=png,
            stats=stats,
        )


def _upsert_screenshot(
    session: Session,
    *,
    match_id: int,
    kind: str,
    side: Optional[str],
    round_no: Optional[int],
    file_path: Path,
    stats: IngestStats,
) -> None:
    stmt = select(PromoMatchScreenshot).where(
        PromoMatchScreenshot.match_id == match_id,
        PromoMatchScreenshot.kind == kind,
    )
    if side is None:
        stmt = stmt.where(PromoMatchScreenshot.side.is_(None))
    else:
        stmt = stmt.where(PromoMatchScreenshot.side == side)
    if round_no is None:
        stmt = stmt.where(PromoMatchScreenshot.round_no.is_(None))
    else:
        stmt = stmt.where(PromoMatchScreenshot.round_no == round_no)
    row = session.exec(stmt).first()
    file_str = str(file_path)
    if row is None:
        row = PromoMatchScreenshot(
            match_id=match_id,
            kind=kind,
            side=side,
            round_no=round_no,
            file_path=file_str,
        )
        session.add(row)
        session.commit()
        stats.screenshots += 1
    elif row.file_path != file_str:
        row.file_path = file_str
        session.add(row)
        session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_captured_at_from_archive(archived: Path) -> datetime:
    """Recover a captured_at timestamp for an archive folder discovered
    without a corresponding staging folder.

    The archive layout is ``<archive>/<YYYY-MM-DD>/promotion_tournament[_N]``.
    We use 00:00 UTC on the date as the timestamp — there's no time info
    in the archive path itself.
    """
    date_str = archived.parent.name
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return datetime.now(timezone.utc)
    return d.replace(tzinfo=timezone.utc)
