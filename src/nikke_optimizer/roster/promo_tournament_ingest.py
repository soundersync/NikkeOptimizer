"""Promotion Tournament ingest — relocate + persist.

Walks ``<staging_root>/promotion_tournament_<TS>/`` folders, copies (or
moves) the source PNGs into the canonical archive layout
``<archive_root>/beta_season_<N>/promotion_tournament/group_*/round_*/match_*/``,
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
from ..data.seasons import (
    is_season_folder,
    parse_season_number,
    season_id,
    season_start,
)

log = logging.getLogger(__name__)

# Source-capture reference dimensions. Every PNG dropped under
# ``incoming-captures/champion_arena/`` must match this. Mismatches mean
# the iPhone capture pipeline drifted (different device, screen-recording
# setting, post-processing); ingest skips them rather than feeding
# garbage to OCR. See [[capture_resolution_normalize_at_source]].
REFERENCE_PNG_SIZE: tuple[int, int] = (1510, 2013)


# NOTE: alternation order matters — ``promotion_tournament_player_data``
# must come BEFORE the shorter ``promotion_tournament`` so the longer
# prefix wins. The dispatch in ``tournament_format()`` makes the same
# ordering choice for the format detection.
_STAGING_NAME_RE = re.compile(
    r"^(promotion_tournament_player_data|promotion_tournament|champions_duel|league)_(\d{8})_(\d{6})$"
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

# League uses a single round label and per-player match folders
# (player_1..player_4). Each player has a single ``loadout/`` (no
# top/bottom split) plus a ``results/`` folder mirroring the promo
# results format (overview.png + duel_*.png).
_ROUND_LABEL_LEAGUE = "league"
_PLAYER_DIR_RE = re.compile(r"^player_(\d+)$")

# Format keys, mirrored in tournament_format(). Single source of truth.
FORMAT_PROMO = "promotion_tournament"
FORMAT_PROMO_PLAYER_DATA = "promotion_tournament_player_data"
FORMAT_DUEL = "champions_duel"
FORMAT_LEAGUE = "league"
FORMAT_ROOKIE_ARENA = "rookie_arena"


def tournament_format(storage_root: str) -> str:
    """Return the format key for a path.

    Champion-family formats are encoded in the archive folder's own
    name (e.g. ``<archive>/beta_season_29/champions_duel/``); the
    Rookie Arena format uses a PARENT-directory convention
    (``<archive>/rookie_arena/<date_TS>/``) since rookie isn't season-
    locked. ``promotion_tournament_player_data`` must be checked
    BEFORE the bare ``promotion_tournament`` prefix or it gets
    misclassified.
    """
    p = Path(storage_root)
    name = p.name
    if name.startswith(FORMAT_PROMO_PLAYER_DATA):
        return FORMAT_PROMO_PLAYER_DATA
    if name.startswith(FORMAT_DUEL):
        return FORMAT_DUEL
    if name.startswith(FORMAT_LEAGUE):
        return FORMAT_LEAGUE
    if p.parent.name == FORMAT_ROOKIE_ARENA:
        return FORMAT_ROOKIE_ARENA
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
    files_wrong_size: list[tuple[Path, tuple[int, int]]] = field(default_factory=list)
    ocr_screenshots: int = 0
    ocr_fields: int = 0
    ocr_skipped: int = 0
    player_data_sidecars: int = 0
    # Scrape pass — populated only when ingest_root(scrape_player_data=True).
    scrape_attempted: int = 0          # tournaments where the scrape loop ran
    scrape_snapshots_written: int = 0  # new RosterSnapshot rows landed
    scrape_status_counts: dict[str, int] = field(default_factory=dict)
    scrape_skipped_reason: Optional[str] = None  # set when scrape opted-out
    # Self-refresh pass — populated only by the rookie-arena ingest's
    # post-scrape self-refresh hook (sparse fetch-shiftyspad for the
    # user's own roster restricted to the chars they used in the run).
    self_refresh_attempted: int = 0     # tournaments where the hook ran
    self_refresh_chars_updated: int = 0  # OwnedCharacter rows that changed
    self_refresh_skipped_reason: Optional[str] = None
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
        if self.files_wrong_size:
            parts.append(f"wrong_size={len(self.files_wrong_size)}")
        if self.ocr_screenshots or self.ocr_skipped:
            parts.append(
                f"ocr=(processed={self.ocr_screenshots} fields={self.ocr_fields} cached={self.ocr_skipped})"
            )
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
    ocr: bool = True,
    force_ocr: bool = False,
    scrape_player_data: bool = False,
    max_scrape_minutes: float = 90.0,
) -> IngestStats:
    """Relocate every ``promotion_tournament_*`` / ``champions_duel_*``
    folder under ``staging_root`` into ``archive_root``, persist DB rows,
    and (by default) run an OCR pass over every screenshot.

    ``archive_root`` defaults to ``<staging_root>/../captures``.

    ``ocr=False`` skips the OCR pass entirely (useful for tests).
    ``force_ocr=True`` re-OCRs screenshots that already have extracted
    fields; otherwise the OCR pass is idempotent and only touches
    screenshots without prior extractions.

    ``scrape_player_data=True`` runs the BlablaLink lookup + snapshot
    scrape for every ingested player_data tournament after the OCR
    sidecar lands. Default off — CLI ``ingest-tournaments`` should not
    block on a 30-min Playwright session. The auto-import daemon opts
    in (gated on a cookie-presence probe). ``max_scrape_minutes`` is a
    soft watchdog per tournament.
    """
    staging_root = Path(staging_root).resolve()
    if archive_root is None:
        # Match the web app's static mount: <repo>/captures/. Avoids
        # the failure mode where dropping a staging folder under
        # ~/Downloads/ would otherwise scatter the archive there.
        archive_root = Path(__file__).resolve().parents[3] / "captures"
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
        # Prefer the season identified by the parent staging folder
        # (e.g. ``beta_season_29_2026-05-07``) when present; fall back
        # to deriving from captured_at via the cadence table.
        explicit_season = parse_season_number(src.parent.name)
        season_slug = (
            f"beta_season_{explicit_season}"
            if explicit_season is not None
            else season_id(captured_at.date())
        )
        dest_dir = _resolve_archive_dir(
            archive_root, season_slug, fmt=fmt, force=force
        )
        try:
            file_stats = _relocate(src, dest_dir, move=move)
        except FileExistsError as exc:
            stats.errors.append(str(exc))
            continue
        stats.files_copied += file_stats.copied
        stats.files_skipped += file_stats.skipped
        stats.files_moved_deleted += file_stats.deleted
        stats.files_wrong_size.extend(file_stats.wrong_size)

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

    # OCR pass — runs over every PromoMatchScreenshot row. Idempotent
    # by default (skips screenshots that already have extracted fields);
    # ``force_ocr=True`` re-runs.
    if ocr:
        _run_ocr_pass(engine, stats=stats, force=force_ocr)
        _run_league_leaderboard_pass(engine, stats=stats, force=force_ocr)
        # Sidecar must run AFTER the OCR pass — it groups the freshly
        # extracted fields into players_lookup.json.
        _run_player_data_sidecar_pass(engine, stats=stats, force=force_ocr)

    # Optional scrape pass — opt-in. Runs the BlablaLink lookup + writes
    # RosterSnapshot rows. Long-running (~20-45 min/tournament) and
    # network/cookie-dependent, so kept off by default; the auto-import
    # daemon opts in when the user has logged in via shiftyspad-login.
    if scrape_player_data:
        _run_player_data_scrape_pass(
            engine, stats=stats, max_scrape_minutes=max_scrape_minutes,
        )

    return stats


def _run_league_leaderboard_pass(engine, *, stats: IngestStats, force: bool) -> None:
    """Walk every league tournament's archive folder and write a
    ``leaderboard.json`` sidecar by OCR'ing the 12 pre-cropped per-rank
    fields. Idempotent; ``force=True`` re-runs even when the sidecar
    already exists.
    """
    from .league_leaderboard import process_league_archive

    with Session(engine) as session:
        league_tournaments = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_LEAGUE
        ]
    for t in league_tournaments:
        league_root = Path(t.storage_root)
        if not league_root.is_dir():
            continue
        try:
            out = process_league_archive(league_root, force=force)
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(
                f"league leaderboard OCR failed for {league_root}: {exc}"
            )
            continue
        if out is not None:
            log.info("league leaderboard sidecar: %s", out)


def _run_player_data_sidecar_pass(
    engine, *, stats: IngestStats, force: bool
) -> None:
    """Walk every player_data tournament and write its
    ``players_lookup.json`` sidecar.

    Reads from ``PromoExtractedField`` rows populated by the prior OCR
    pass; emits one sidecar per tournament root. Idempotent — existing
    sidecars are left alone unless ``force=True``.
    """
    from ..data.seasons import parse_season_number
    from .promo_tournament_player_data import process_player_data_tournament

    with Session(engine) as session:
        tournaments = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_PROMO_PLAYER_DATA
        ]
        for t in tournaments:
            season_n = parse_season_number(Path(t.storage_root).parent.name)
            try:
                out = process_player_data_tournament(
                    session, t, season_number=season_n, force=force,
                )
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(
                    f"player_data sidecar failed for {t.storage_root}: {exc}"
                )
                continue
            if out is not None:
                stats.player_data_sidecars += 1
                log.info("player_data sidecar: %s", out)


def _run_player_data_scrape_pass(
    engine, *, stats: IngestStats, max_scrape_minutes: float,
) -> None:
    """Run the BlablaLink lookup + snapshot scrape for every
    player_data tournament with a sidecar present.

    Tournaments without a ``players_lookup.json`` are silently skipped
    — the sidecar pass that precedes us writes one whenever there's
    OCR data to surface.
    """
    from ..data.seasons import parse_season_number
    from .promo_tournament_player_data import sidecar_path as _pd_sidecar_path
    from .promo_tournament_player_data_scrape import (
        STATUS_FOUND,
        STATUS_PRIVATE_BOTH,
        scrape_tournament_players,
    )

    with Session(engine) as session:
        tournaments = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_PROMO_PLAYER_DATA
        ]

    for t in tournaments:
        root = Path(t.storage_root)
        if not _pd_sidecar_path(root).is_file():
            continue
        season_n = parse_season_number(root.parent.name)
        if season_n is None:
            stats.errors.append(
                f"scrape skipped (no season number derivable): {root}"
            )
            continue
        stats.scrape_attempted += 1
        try:
            status = scrape_tournament_players(
                root,
                season_number=season_n,
                tournament_id=t.id,
                apply=True,
                max_minutes=max_scrape_minutes,
            )
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(
                f"player_data scrape failed for {root}: {exc}"
            )
            continue
        # Fold per-player status counts into the cumulative dict.
        new_snapshots = 0
        for rec in status.players.values():
            stats.scrape_status_counts[rec.status] = (
                stats.scrape_status_counts.get(rec.status, 0) + 1
            )
            if rec.status in (STATUS_FOUND, STATUS_PRIVATE_BOTH):
                if rec.snapshot_id is not None:
                    new_snapshots += 1
        stats.scrape_snapshots_written += new_snapshots


def _run_ocr_pass(engine, *, stats: IngestStats, force: bool) -> None:
    """Walk every screenshot row and populate PromoExtractedField rows.

    Lazily initializes PaddleOCR (~5–10s) only when there's actual work
    to do. Uses ``rich.progress`` for an interactive progress bar since
    a full pass over the user's archive is ~15–25 minutes.
    """
    from PIL import Image
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeRemainingColumn,
    )

    from ..data.models import PromoMatchScreenshot
    from .promo_tournament_ocr import (
        CharIndex,
        extract_screenshot,
        has_extractions,
        persist_extractions,
    )

    with Session(engine) as session:
        all_shots = session.exec(select(PromoMatchScreenshot)).all()

    # Pre-filter to the screenshots we actually need to process so the
    # progress bar's total reflects real work + we can short-circuit
    # entirely when there's nothing to do.
    pending: list[int] = []
    cached: int = 0
    with Session(engine) as session:
        for shot in all_shots:
            if not force and has_extractions(session, shot.id):
                cached += 1
            else:
                pending.append(shot.id)
    stats.ocr_skipped = cached
    if not pending:
        return

    with Session(engine) as session:
        char_index = CharIndex.from_session(session)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        transient=False,
    ) as progress:
        task = progress.add_task("OCR'ing screenshots", total=len(pending))
        for shot_id in pending:
            with Session(engine) as session:
                shot = session.get(PromoMatchScreenshot, shot_id)
                if shot is None:
                    progress.advance(task)
                    continue
                try:
                    image = Image.open(shot.file_path).convert("RGB")
                except OSError as exc:
                    stats.errors.append(
                        f"OCR open failed for screenshot {shot_id}: {exc}"
                    )
                    progress.advance(task)
                    continue
                try:
                    extractions = extract_screenshot(
                        image, shot.kind, char_index=char_index
                    )
                except Exception as exc:  # noqa: BLE001
                    stats.errors.append(
                        f"OCR extract failed for screenshot {shot_id}: {exc}"
                    )
                    progress.advance(task)
                    continue
                stats.ocr_fields += persist_extractions(
                    session, shot_id, extractions
                )
                stats.ocr_screenshots += 1
            progress.advance(task)


def run_backfill_pass(engine) -> IngestStats:
    """Extract only the region slugs missing from already-ingested screenshots.

    Walks every ``PromoMatchScreenshot``, computes the set of canonical
    region slugs not yet present in ``PromoExtractedField``, and runs
    extraction filtered to that set only. Cheap when the schema delta
    is small (e.g. a Phase 2.x addition like ``char{N}.lb_core``) —
    skips screenshots that already have full coverage and skips
    PaddleOCR entirely when no slugs are missing for a screenshot.
    """
    from PIL import Image
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeRemainingColumn,
    )

    from ..data.models import PromoMatchScreenshot
    from .promo_tournament_ocr import (
        CharIndex,
        extract_screenshot,
        missing_slugs,
        persist_extractions,
    )

    stats = IngestStats()
    with Session(engine) as session:
        all_shots = session.exec(select(PromoMatchScreenshot)).all()

    # Pre-compute the missing-slug set per screenshot so the progress
    # bar reflects only screenshots with real work + so we never open
    # an image we won't actually extract from.
    pending: list[tuple[int, frozenset[str]]] = []
    cached: int = 0
    with Session(engine) as session:
        for shot in all_shots:
            missing = missing_slugs(session, shot.id, shot.kind)
            if missing:
                pending.append((shot.id, missing))
            else:
                cached += 1
    stats.ocr_skipped = cached
    if not pending:
        return stats

    with Session(engine) as session:
        char_index = CharIndex.from_session(session)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        transient=False,
    ) as progress:
        task = progress.add_task("Backfilling extractions", total=len(pending))
        for shot_id, only in pending:
            with Session(engine) as session:
                shot = session.get(PromoMatchScreenshot, shot_id)
                if shot is None:
                    progress.advance(task)
                    continue
                try:
                    image = Image.open(shot.file_path).convert("RGB")
                except OSError as exc:
                    stats.errors.append(
                        f"Backfill open failed for screenshot {shot_id}: {exc}"
                    )
                    progress.advance(task)
                    continue
                try:
                    extractions = extract_screenshot(
                        image, shot.kind, char_index=char_index, only_slugs=only
                    )
                except Exception as exc:  # noqa: BLE001
                    stats.errors.append(
                        f"Backfill extract failed for screenshot {shot_id}: {exc}"
                    )
                    progress.advance(task)
                    continue
                stats.ocr_fields += persist_extractions(
                    session, shot_id, extractions
                )
                stats.ocr_screenshots += 1
            progress.advance(task)
    return stats


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_staging(staging_root: Path) -> list[Path]:
    """Find tournament staging folders under ``staging_root``.

    Looks at ``staging_root``'s direct children, plus one level deeper
    into any ``beta_season_<N>[_…]`` subdir. This lets callers point at
    either a tournament-specific dir (``beta_season_29_2026-05-07/``)
    OR the season-parent dir (``champion_arena/``) and pick up every
    tournament across every season under it.
    """
    if not staging_root.is_dir():
        return []
    found: list[Path] = []
    for top in staging_root.iterdir():
        if not top.is_dir():
            continue
        if _STAGING_NAME_RE.match(top.name):
            found.append(top)
        elif parse_season_number(top.name) is not None:
            for child in top.iterdir():
                if child.is_dir() and _STAGING_NAME_RE.match(child.name):
                    found.append(child)
    return sorted(found)


def _discover_archived(archive_root: Path) -> list[Path]:
    """Yield ``<archive>/beta_season_<N>/<format>[_N]/`` folders for
    every supported format.
    """
    if not archive_root.is_dir():
        return []
    out: list[Path] = []
    for season_dir in sorted(archive_root.iterdir()):
        if not season_dir.is_dir() or not is_season_folder(season_dir.name):
            continue
        for fmt_dir in sorted(season_dir.iterdir()):
            if not fmt_dir.is_dir():
                continue
            if (
                # NB: FORMAT_PROMO_PLAYER_DATA starts with FORMAT_PROMO,
                # so the bare ``startswith(FORMAT_PROMO)`` check covers
                # both. ``tournament_format()`` disambiguates the two.
                fmt_dir.name.startswith(FORMAT_PROMO)
                or fmt_dir.name.startswith(FORMAT_DUEL)
                or fmt_dir.name.startswith(FORMAT_LEAGUE)
            ):
                out.append(fmt_dir)
    return out


def _resolve_archive_dir(
    archive_root: Path, season_slug: str, *, fmt: str, force: bool
) -> Path:
    """Return ``<archive>/<season_slug>/<fmt>[_N]/``.

    ``season_slug`` is the canonical season folder name (e.g.
    ``beta_season_29``). ``fmt`` is the format key (``promotion_tournament``,
    ``champions_duel``, or ``league``). If the base folder already
    exists and ``force`` is set, a numbered suffix is appended (``_2``,
    ``_3``, …). Otherwise the base path is returned regardless —
    relocation handles same-source idempotency at the file level.
    """
    base = archive_root / season_slug / fmt
    if not base.exists() or not force:
        return base
    n = 2
    while (cand := archive_root / season_slug / f"{fmt}_{n}").exists():
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
    wrong_size: list[tuple[Path, tuple[int, int]]] = field(default_factory=list)


def _png_size(path: Path) -> Optional[tuple[int, int]]:
    """Return (width, height) or None if the PNG can't be opened."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            return im.size
    except (OSError, ValueError):
        return None


def _relocate(src: Path, dest: Path, *, move: bool) -> _FileStats:
    """Copy every relevant .png from ``src`` tree into the matching path
    under ``dest``. Returns per-file stats.

    PNGs whose dimensions don't match ``REFERENCE_PNG_SIZE`` are skipped
    (not copied, not deleted from staging) and recorded in
    ``stats.wrong_size`` so the caller can surface them.
    """
    stats = _FileStats()
    dest.mkdir(parents=True, exist_ok=True)
    for src_file in _iter_source_pngs(src):
        size = _png_size(src_file)
        if size is not None and size != REFERENCE_PNG_SIZE:
            log.warning(
                "skipping wrong-dim PNG %s (%s, expected %s)",
                src_file, size, REFERENCE_PNG_SIZE,
            )
            stats.wrong_size.append((src_file, size))
            continue
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

    Skips coord-picker output (``__crop.png`` / ``__masked.png``) — the
    project convention is that crop coordinates live as ``Region``
    constants in code (see ``promo_tournament_regions.py``,
    ``league_leaderboard_regions.py``, etc.), so coord-picker artifacts
    in staging are reference material only and never enter the archive.
    Order is deterministic.
    """
    for p in sorted(src_root.rglob("*.png")):
        if p.name.lower().startswith("."):
            continue
        stem = p.stem
        if "__masked" in stem or "__crop" in stem:
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
    elif fmt == FORMAT_PROMO_PLAYER_DATA:
        # Pre-bracket Arena Info popups. Structurally identical to a
        # regular promo bracket (group_N/round_64/match_N/{player_top,
        # player_bottom}/round_K.png) but with NO results/ subdirs ever
        # present. Reuses the same loadout walker so OCR + UI tooling
        # don't need to distinguish at the screenshot level — the
        # "no results, pre-bracket" provenance lives in the tournament's
        # storage_root and is exposed via tournament_format().
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
    elif fmt == FORMAT_LEAGUE:
        # League — no groups, no head-to-head matches. 1..4 player
        # folders each with their own loadout + results. Synthesize a
        # single PromoGroup (group_no=1) so PromoMatch.group_id stays
        # non-null; the leaderboard.png lives at ``storage_root`` and
        # the 12 canonical crops are cut from it via the constants in
        # ``league_leaderboard_regions``.
        from .league_leaderboard import cut_leaderboard_crops

        try:
            cut_leaderboard_crops(storage_root)
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(
                f"leaderboard crop cut failed for {storage_root}: {exc}"
            )

        group = _upsert_group(session, tournament.id, 1, stats)
        for player_dir in sorted(p for p in storage_root.iterdir() if p.is_dir()):
            m = _PLAYER_DIR_RE.match(player_dir.name)
            if m is None:
                continue
            _persist_league_player(
                session,
                tournament_id=tournament.id,
                group_id=group.id,
                player_no=int(m.group(1)),
                player_dir=player_dir,
                stats=stats,
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


def _persist_league_player(
    session: Session,
    *,
    tournament_id: int,
    group_id: int,
    player_no: int,
    player_dir: Path,
    stats: IngestStats,
) -> None:
    """Walk a league player folder.

    Layout: ``player_<N>/loadout/round_<1..5>.png`` plus the standard
    promo-style ``player_<N>/results/{overview.png, duel_<N>.png}``.

    The match row uses ``round_label="league"`` and ``match_no=<player_no>``
    so the natural-key uniqueness constraint in PromoMatch holds across
    all 4 players.
    """
    loadout_dir = player_dir / "loadout"
    results_dir = player_dir / "results"
    has_loadouts = loadout_dir.is_dir()
    match = _upsert_match(
        session,
        tournament_id=tournament_id,
        group_id=group_id,
        round_label=_ROUND_LABEL_LEAGUE,
        match_no=player_no,
        has_loadouts=has_loadouts,
        stats=stats,
    )
    if has_loadouts:
        for png in sorted(loadout_dir.glob("*.png")):
            if _DERIVED_MARKER in png.stem:
                continue
            m = _PLAYER_FILE_RE.match(png.name)
            if m is None:
                continue
            round_no = int(m.group(1))
            _upsert_screenshot(
                session,
                match_id=match.id,
                kind="player_loadout",
                # League has no head-to-head sides; leave NULL.
                side=None,
                round_no=round_no,
                file_path=png,
                stats=stats,
            )
    if results_dir.is_dir():
        _persist_results(session, match.id, results_dir, stats)


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

    The archive layout is
    ``<archive>/beta_season_<N>/<format>[_N]``. We use the season's
    start date at 00:00 UTC as the timestamp — there's no per-day time
    info in the archive path itself.
    """
    season_n = parse_season_number(archived.parent.name)
    if season_n is None:
        return datetime.now(timezone.utc)
    return datetime.combine(season_start(season_n), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
