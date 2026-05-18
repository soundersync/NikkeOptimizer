"""Rookie Arena ingest.

Reads daily-run staging folders from
``incoming-captures/rookie_arena/<YYYY-MM-DD>_<HHMMSS>/battle_N/``,
relocates the PNGs into
``captures/rookie_arena/<YYYY-MM-DD>_<HHMMSS>/battle_N/``, and persists:

* one ``PromoTournament`` per daily run (storage_root carries the
  parent ``rookie_arena/`` directory so ``tournament_format()`` returns
  ``FORMAT_ROOKIE_ARENA``)
* one synthetic ``PromoGroup`` per tournament (group_no=1; rookie has
  no group concept but PromoMatch.group_id is non-null)
* one ``PromoMatch`` per battle (round_label="rookie", match_no=N)
* one ``PromoMatchScreenshot`` per file per battle:
    - ``opponent.png`` → kind="rookie_opponent"  (may be absent)
    - ``loadout.png``  → kind="rookie_loadout"
    - ``results.png``  → kind="results_duel" (shared with Champion duels)

Idempotent. ``--only-run`` / ``--only-battle`` filters let us focus the
Phase 1 validation pass on a single battle without touching the rest.
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
from .promo_tournament_ingest import (
    FORMAT_ROOKIE_ARENA,
    IngestStats,
    REFERENCE_PNG_SIZE,
    _upsert_group,
    _upsert_match,
    _upsert_screenshot,
    _png_size,
)

log = logging.getLogger(__name__)

# Per-run staging-folder name: YYYY-MM-DD_HHMMSS.
_RUN_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})$")
_BATTLE_NAME_RE = re.compile(r"^battle_(\d+)$")

# File-name → screenshot kind. ``results.png`` reuses the existing
# ``results_duel`` kind because the Rookie Arena "Battle Records"
# screen is structurally identical to the post-match Battle Records
# from Champions Duel / Promotion Tournament — same blue title bar,
# same 5-row × 2-column layout, same per-row content. The existing
# 50-region schema in promo_tournament_regions.DUEL lands pixel-
# for-pixel on rookie results.png. Char names from this screen are
# much larger + cleaner than the loadout's tiny popup text, and
# ArenaMatchBuilder prefers them when available.
_FILE_KIND: dict[str, str] = {
    "opponent.png": "rookie_opponent",
    "loadout.png": "rookie_loadout",
    "results.png": "results_duel",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest_rookie_root(
    staging_root: Path,
    *,
    archive_root: Optional[Path] = None,
    move: bool = False,
    db_path: Optional[Path] = None,
    ocr: bool = True,
    force_ocr: bool = False,
    only_run: Optional[str] = None,
    only_battle: Optional[int] = None,
    scrape_rookie_opponents: bool = False,
    refresh_self_from_loadouts: bool = False,
    max_scrape_minutes: float = 90.0,
) -> IngestStats:
    """Ingest every ``<date_TS>/`` run found under ``staging_root``.

    ``only_run`` filters to one staging-folder name (e.g.
    ``"2026-05-17_052345"``). ``only_battle`` filters to battle_N
    within each run. Both are intended for the Phase 1 validation
    pass — point at a single battle without touching the rest.
    """
    staging_root = Path(staging_root).resolve()
    if archive_root is None:
        # captures/ at the repo root, matching the web app's static
        # mount + the Champion-family archive convention.
        archive_root = Path(__file__).resolve().parents[3] / "captures"
    archive_root = Path(archive_root).resolve()

    stats = IngestStats()
    engine = make_engine(db_path)
    init_db(engine)

    run_dirs = _discover_runs(staging_root, only_run=only_run)
    for src_run in run_dirs:
        m = _RUN_NAME_RE.match(src_run.name)
        if m is None:
            stats.errors.append(f"bad run folder name: {src_run.name}")
            continue
        ymd, hms = m.group(1), m.group(2)
        captured_at = datetime.strptime(
            f"{ymd}_{hms}", "%Y-%m-%d_%H%M%S"
        ).replace(tzinfo=timezone.utc)

        # Archive lays out at: <archive>/rookie_arena/<date_TS>/
        dest_run = archive_root / FORMAT_ROOKIE_ARENA / src_run.name
        dest_run.mkdir(parents=True, exist_ok=True)

        file_stats = _relocate_run(
            src_run, dest_run, move=move, only_battle=only_battle,
        )
        stats.files_copied += file_stats.copied
        stats.files_skipped += file_stats.skipped
        stats.files_moved_deleted += file_stats.deleted
        stats.files_wrong_size.extend(file_stats.wrong_size)

        with Session(engine) as session:
            _persist_run(
                session,
                stats=stats,
                storage_root=dest_run,
                captured_at=captured_at,
                source_root=src_run,
                only_battle=only_battle,
            )
            session.commit()

    # OCR pass — reuses the existing infra. Only OCRs new screenshots
    # unless force_ocr is set. Lazily imported to keep PaddleOCR cost
    # off the import path of this module.
    if ocr:
        from .promo_tournament_ingest import _run_ocr_pass
        _run_ocr_pass(engine, stats=stats, force=force_ocr)
        # ArenaMatch population — runs AFTER OCR so the builder has the
        # fields it needs. Idempotent via the (session_id, round_index)
        # natural key. Also writes per-run players_lookup.json sidecars.
        _build_arena_matches_for_all_rookie_runs(engine)

    # Optional scrape pass — opt-in, gated on the daemon's cookie
    # probe. The scrape uses the freshly-built sidecars + cross-run
    # level cache, writes RookieArenaSnapshot rows for Found opponents.
    if scrape_rookie_opponents:
        _run_rookie_scrape_pass(
            engine, stats=stats, max_scrape_minutes=max_scrape_minutes,
        )

    # Self-refresh pass — sparse fetch-shiftyspad for the user's own
    # roster restricted to the chars they used in the just-ingested
    # run(s). Gated on cookies AND a configured intl_openid. Skipped
    # per-tournament via a state file so a daemon restart doesn't
    # re-fetch the same run.
    if refresh_self_from_loadouts:
        _run_self_refresh_pass(engine, stats=stats, db_path=db_path)

    return stats


def _run_self_refresh_pass(
    engine, *, stats: IngestStats, db_path: Optional[Path],
) -> None:
    """Sparse OwnedCharacter refresh from rookie loadouts.

    Walks every rookie tournament that hasn't yet been self-refreshed
    (tracked via the per-tournament state file in
    ``rookie_self_refresh``). For each, harvests the user's loadout
    Nikkes and runs a targeted ShiftyPad fetch+sync against the
    configured ``intl_openid``.
    """
    from ..data.config import get_self_intl_openid
    from .promo_tournament_ingest import (
        FORMAT_ROOKIE_ARENA, tournament_format,
    )
    from .rookie_self_refresh import (
        already_refreshed,
        refresh_self_from_rookie_tournament,
    )

    uid = get_self_intl_openid()
    if not uid:
        stats.self_refresh_skipped_reason = (
            "no intl_openid configured — run "
            "`nikkeoptimizer set-uid <base64-uid>`"
        )
        return

    with Session(engine) as session:
        tournaments = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_ROOKIE_ARENA
            and not already_refreshed(t.id)
        ]
        for t in tournaments:
            stats.self_refresh_attempted += 1
            try:
                report = refresh_self_from_rookie_tournament(
                    session, t, intl_openid=uid, db_path=db_path,
                )
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(
                    f"self-refresh failed for {t.storage_root}: {exc}"
                )
                continue
            if report.error:
                stats.errors.append(
                    f"self-refresh error for {t.storage_root}: {report.error}"
                )
            stats.self_refresh_chars_updated += report.chars_updated
            log.info(
                "self-refresh %s: targeted=%d unmapped=%d updated=%d skipped=%s",
                t.storage_root,
                len(report.chars_targeted),
                len(report.chars_unmapped),
                report.chars_updated,
                report.skipped_reason,
            )


def _run_rookie_scrape_pass(
    engine, *, stats: IngestStats, max_scrape_minutes: float,
) -> None:
    """Run the BlablaLink scrape for every rookie run with a sidecar.

    Reuses the same per-tournament watchdog + status-sidecar resume
    pattern as the player_data scrape. Cookie probe happens at the
    daemon level — by the time we get here we assume cookies exist.
    """
    from .promo_tournament_ingest import (
        FORMAT_ROOKIE_ARENA,
        tournament_format,
    )
    from .rookie_arena_scrape import (
        STATUS_FOUND,
        STATUS_PRIVATE_BOTH,
        scrape_rookie_run,
    )
    from .rookie_arena_sidecar import sidecar_path

    with Session(engine) as session:
        tournaments = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_ROOKIE_ARENA
        ]

    for t in tournaments:
        root = Path(t.storage_root)
        if not sidecar_path(root).is_file():
            continue
        stats.scrape_attempted += 1
        try:
            status = scrape_rookie_run(
                root,
                tournament=t,
                apply=True,
                max_minutes=max_scrape_minutes,
            )
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(
                f"rookie scrape failed for {root}: {exc}"
            )
            continue
        new_snapshots = 0
        for rec in status.players.values():
            stats.scrape_status_counts[rec.status] = (
                stats.scrape_status_counts.get(rec.status, 0) + 1
            )
            if rec.status in (STATUS_FOUND, STATUS_PRIVATE_BOTH):
                if rec.snapshot_id is not None:
                    new_snapshots += 1
        stats.scrape_snapshots_written += new_snapshots


def _build_arena_matches_for_all_rookie_runs(engine) -> None:
    """Walk every rookie-arena tournament and refresh its ArenaMatch
    rows. Idempotent; cheap to re-run because the builder reads from
    already-populated PromoExtractedField rows.

    Also writes the per-run ``players_lookup.json`` sidecar — derived
    from the freshly-built ArenaMatch rows — so the scrape driver
    has its input ready immediately.
    """
    from .promo_tournament_ingest import tournament_format
    from .rookie_arena_arena_match import build_arena_matches_for_run
    from .rookie_arena_sidecar import process_rookie_run

    with Session(engine) as session:
        tournaments = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_ROOKIE_ARENA
        ]
        for t in tournaments:
            n = build_arena_matches_for_run(session, t)
            log.info("rookie ArenaMatch builder: %s → %d rows", t.storage_root, n)
            # Always regenerate the sidecar — ArenaMatch rows may have
            # changed even when no new screenshots arrived.
            out = process_rookie_run(session, t, force=True)
            if out is not None:
                log.info("rookie sidecar: %s", out)


# ---------------------------------------------------------------------------
# Discovery + walking
# ---------------------------------------------------------------------------


def _discover_runs(
    staging_root: Path, *, only_run: Optional[str] = None,
) -> list[Path]:
    if not staging_root.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(staging_root.iterdir()):
        if not child.is_dir():
            continue
        if _RUN_NAME_RE.match(child.name) is None:
            continue
        if only_run is not None and child.name != only_run:
            continue
        out.append(child)
    return out


@dataclass
class _FileStats:
    copied: int = 0
    skipped: int = 0
    deleted: int = 0
    wrong_size: list[tuple[Path, tuple[int, int]]] = field(default_factory=list)


def _relocate_run(
    src_run: Path,
    dest_run: Path,
    *,
    move: bool,
    only_battle: Optional[int] = None,
) -> _FileStats:
    """Copy every battle_N/{opponent,loadout,results}.png from src to dest.

    Dim-checks against REFERENCE_PNG_SIZE — mismatches are recorded
    and skipped (same convention as the Champion-family ingest).
    """
    stats = _FileStats()
    for battle_dir in sorted(src_run.iterdir()):
        if not battle_dir.is_dir():
            continue
        m = _BATTLE_NAME_RE.match(battle_dir.name)
        if m is None:
            continue
        battle_no = int(m.group(1))
        if only_battle is not None and battle_no != only_battle:
            continue
        dest_battle = dest_run / battle_dir.name
        dest_battle.mkdir(parents=True, exist_ok=True)
        for src_file in sorted(battle_dir.iterdir()):
            if not src_file.is_file() or src_file.suffix.lower() != ".png":
                continue
            if src_file.name not in _FILE_KIND:
                continue  # ignore stray pngs (crop-tool leftovers, etc.)
            size = _png_size(src_file)
            if size is not None and size != REFERENCE_PNG_SIZE:
                log.warning(
                    "skipping wrong-dim PNG %s (%s, expected %s)",
                    src_file, size, REFERENCE_PNG_SIZE,
                )
                stats.wrong_size.append((src_file, size))
                continue
            out = dest_battle / src_file.name
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


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_run(
    session: Session,
    *,
    stats: IngestStats,
    storage_root: Path,
    captured_at: datetime,
    source_root: Optional[Path],
    only_battle: Optional[int] = None,
) -> None:
    """Upsert one PromoTournament per run + a PromoGroup + PromoMatch
    per battle + one PromoMatchScreenshot per PNG."""
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
        tournament.source_root = str(source_root)
        session.add(tournament)
        session.commit()

    if not storage_root.is_dir():
        return

    # Single synthetic PromoGroup — PromoMatch.group_id is non-null.
    # group_no=1 mirrors the Champions-Duel / League convention.
    group = _upsert_group(session, tournament.id, 1, stats)

    for battle_dir in sorted(storage_root.iterdir()):
        if not battle_dir.is_dir():
            continue
        m = _BATTLE_NAME_RE.match(battle_dir.name)
        if m is None:
            continue
        battle_no = int(m.group(1))
        if only_battle is not None and battle_no != only_battle:
            continue
        # has_loadouts is the conventional "this battle has team data"
        # flag — true whenever loadout.png is present.
        has_loadouts = (battle_dir / "loadout.png").is_file()
        match = _upsert_match(
            session,
            tournament_id=tournament.id,
            group_id=group.id,
            round_label="rookie",
            match_no=battle_no,
            has_loadouts=has_loadouts,
            stats=stats,
        )
        for fname, kind in _FILE_KIND.items():
            f = battle_dir / fname
            if not f.is_file():
                continue
            _upsert_screenshot(
                session,
                match_id=match.id,
                kind=kind,
                side=None,
                round_no=None,
                file_path=f,
                stats=stats,
            )
