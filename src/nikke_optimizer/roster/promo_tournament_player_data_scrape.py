"""Lookup + snapshot scrape for player_data tournaments.

Slice 3 of the player_data flow:

  1. Read ``players_lookup.json`` (written by
     :mod:`promo_tournament_player_data`).
  2. Dedupe by player name; skip already-snapshotted players unless
     ``force=True``.
  3. For each remaining player, run ``search_and_verify_player`` against
     BlablaLink. For Found rows, navigate to the shiftyspad/home page,
     fetch detail payloads for the 5 characters surfaced in the popup,
     and write a ``RosterSnapshot`` for the (season, player).
  4. Persist a per-tournament ``players_lookup_status.json`` after each
     player so mid-run interruption (launchctl kickstart, network drop)
     resumes cleanly on the next invocation.

The status sidecar is the load-bearing idempotency mechanism — re-runs
are cheap because already-snapshotted players are skipped without a
search XHR.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import logging
import random
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from ..data.scrapers.blablalink_user_lookup import (
    DEFAULT_LEVEL_TOLERANCE,
    PlayerQuery,
    search_and_verify_player,
)
from ..data.scrapers.shiftyspad import (
    DEFAULT_DETAIL_DELAY_RANGE,
    SITE_BASE,
    HomePayload,
    ShiftyPadFetcher,
    fetch_character_details,
)
from .promo_tournament_player_data import (
    PlayerDataSidecar,
    PlayerRecord,
    read_sidecar,
)
from .shiftyspad_importer import NameCodeIndex, sync_to_snapshot

log = logging.getLogger(__name__)

STATUS_SIDECAR_FILENAME = "players_lookup_status.json"
STATUS_SIDECAR_VERSION = 1

# Status values written to PlayerScrapeRecord.status.
STATUS_FOUND = "found"
STATUS_NO_RESULTS = "no_results"
STATUS_NOT_ON_NA = "not_on_na"
STATUS_LEVEL_MISMATCH = "level_mismatch"
STATUS_PRIVATE_BOTH = "private_both"   # found but neither roster nor outpost public
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"             # excluded by --only or already-found-and-skipped


# ---------------------------------------------------------------------------
# Sidecar data types
# ---------------------------------------------------------------------------


@dataclass
class PlayerScrapeRecord:
    """One player's scrape outcome."""

    name: str
    level: int                          # the level we searched for
    status: str                         # one of STATUS_* constants
    snapshot_id: Optional[int] = None
    snapshotted_at: Optional[str] = None  # ISO timestamp
    actual_level: Optional[int] = None    # from BlablaLink (may differ from `level`)
    uid: Optional[str] = None
    is_roster_private: Optional[bool] = None
    is_outpost_private: Optional[bool] = None
    char_names_attempted: list[str] = field(default_factory=list)
    char_names_matched: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class StatusSidecar:
    """Per-tournament status sidecar — one entry per unique player."""

    sidecar_version: int
    tournament_id: int
    season_number: Optional[int]
    last_run_at: str                    # ISO timestamp of latest scrape pass
    players: dict[str, PlayerScrapeRecord] = field(default_factory=dict)

    @classmethod
    def load_or_init(
        cls,
        tournament_root: Path,
        *,
        tournament_id: int,
        season_number: Optional[int],
    ) -> "StatusSidecar":
        p = tournament_root / STATUS_SIDECAR_FILENAME
        if p.is_file():
            try:
                raw = json.loads(p.read_text())
                players = {
                    name: PlayerScrapeRecord(**rec)
                    for name, rec in raw.get("players", {}).items()
                }
                return cls(
                    sidecar_version=raw.get("sidecar_version", STATUS_SIDECAR_VERSION),
                    tournament_id=raw.get("tournament_id", tournament_id),
                    season_number=raw.get("season_number", season_number),
                    last_run_at=raw.get("last_run_at", ""),
                    players=players,
                )
            except (json.JSONDecodeError, TypeError) as exc:
                log.warning("malformed status sidecar %s — rebuilding (%s)", p, exc)
        return cls(
            sidecar_version=STATUS_SIDECAR_VERSION,
            tournament_id=tournament_id,
            season_number=season_number,
            last_run_at="",
        )

    def save(self, tournament_root: Path) -> Path:
        self.last_run_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        p = tournament_root / STATUS_SIDECAR_FILENAME
        p.write_text(
            json.dumps(
                {
                    "sidecar_version": self.sidecar_version,
                    "tournament_id": self.tournament_id,
                    "season_number": self.season_number,
                    "last_run_at": self.last_run_at,
                    "players": {
                        name: asdict(rec) for name, rec in self.players.items()
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return p


# ---------------------------------------------------------------------------
# Plan-building (no network)
# ---------------------------------------------------------------------------


@dataclass
class PlanEntry:
    """One player slated for lookup + snapshot."""

    name: str
    expected_level: int
    char_names: list[str]               # canonical Character.name values
    source_screenshot_id: int           # for traceability


def dedupe_by_player(records: list[PlayerRecord]) -> list[PlayerRecord]:
    """Return one record per unique ``player_name``.

    When a player appears in both top and bottom across matches, prefer
    the record with the most populated payload (team_cp + level both
    present + most char-name hits). Ties broken by higher confidence,
    then by lowest (group, match, side) for determinism.

    Rows with an empty/whitespace ``player_name`` are dropped (they
    can't be keyed). Rows with ``player_level is None`` are KEPT so
    inspectors can surface them; ``build_plan`` filters those out
    separately when constructing the scrape work list.
    """
    def _quality(r: PlayerRecord) -> tuple:
        cp = 1 if r.team_cp is not None else 0
        lv = 1 if r.player_level is not None else 0
        chars = sum(1 for c in r.chars if c.name is not None)
        conf = r.player_name_confidence or 0.0
        # Sort key: descending quality, ascending (group, match, side).
        return (-(cp + lv + chars), -conf, r.group_no, r.match_no, r.side)

    bucket: dict[str, PlayerRecord] = {}
    for r in records:
        if not r.player_name or not r.player_name.strip():
            continue
        name = r.player_name.strip()
        existing = bucket.get(name)
        if existing is None or _quality(r) < _quality(existing):
            bucket[name] = r
    return list(bucket.values())


def build_plan(
    sidecar: PlayerDataSidecar,
    status: StatusSidecar,
    *,
    force: bool = False,
    only: Optional[set[str]] = None,
    limit: Optional[int] = None,
) -> list[PlanEntry]:
    """Build the per-player work list.

    Skips players already in ``status`` with ``status_=STATUS_FOUND``
    unless ``force=True``. Applies ``only`` (case-insensitive name set)
    when provided. ``limit`` caps the plan at N entries (post-sort) —
    useful for low-blast-radius pilot runs.
    """
    only_norm = {n.strip().lower() for n in only} if only else None
    out: list[PlanEntry] = []
    for r in dedupe_by_player(sidecar.players):
        # Scrape needs an expected level for the BlablaLink verify step;
        # rows without one can't be matched and are surfaced as issues
        # by the inspector instead.
        if r.player_level is None:
            continue
        if only_norm is not None and r.player_name.lower() not in only_norm:
            continue
        if not force:
            prior = status.players.get(r.player_name)
            if prior is not None and prior.status == STATUS_FOUND:
                continue
        out.append(PlanEntry(
            name=r.player_name,
            expected_level=r.player_level,
            char_names=[c.name for c in r.chars if c.name],
            source_screenshot_id=r.screenshot_id,
        ))
    # Stable order — name is a fine key for human-debuggable output.
    out.sort(key=lambda e: e.name.lower())
    if limit is not None and limit >= 0:
        out = out[:limit]
    return out


# ---------------------------------------------------------------------------
# Scrape orchestration
# ---------------------------------------------------------------------------


@dataclass
class ScrapeProgress:
    """Per-player progress signal for CLI/daemon rendering."""

    index: int
    total: int
    name: str
    stage: str                          # "searching" | "fetching" | "snapshotting" | terminal status
    record: Optional[PlayerScrapeRecord] = None


def _uid_b64(intl_openid: str) -> str:
    return base64.b64encode(intl_openid.encode()).decode()


def scrape_tournament_players(
    tournament_root: Path,
    *,
    season_number: int,
    tournament_id: int,
    apply: bool = False,
    only: Optional[set[str]] = None,
    force: bool = False,
    limit: Optional[int] = None,
    tolerance: int = DEFAULT_LEVEL_TOLERANCE,
    max_minutes: float = 90.0,
    headless: bool = True,
    detail_delay_range: tuple[float, float] = DEFAULT_DETAIL_DELAY_RANGE,
    home_pacing_range: tuple[float, float] = DEFAULT_DETAIL_DELAY_RANGE,
    fetcher: Optional[ShiftyPadFetcher] = None,
    db_path: Optional[Path] = None,
    on_progress: Optional[Callable[[ScrapeProgress], None]] = None,
    rng: Optional[random.Random] = None,
) -> StatusSidecar:
    """Run the full lookup + snapshot loop for one player_data tournament.

    ``apply=False`` (default) is dry-run: builds the plan, prints/logs
    each entry, and returns the existing status sidecar unchanged
    (no network, no DB writes).

    ``apply=True`` opens a Playwright session, runs search + snapshot
    for each plan entry, persists ``RosterSnapshot`` rows, and updates
    the status sidecar after each player.

    ``force=True`` re-runs players whose status is already ``found``.

    ``max_minutes`` is a soft watchdog — the loop checks elapsed time
    between players and stops early when exceeded (a partial snapshot
    is still persisted; the next invocation resumes).

    ``limit`` caps the work list at N players (post-sort, post-filter)
    — pair with ``apply=True`` for a low-blast-radius pilot run that
    validates the full ingest → lookup → snapshot chain end-to-end on
    a handful of players before committing to the full ~60 of them.
    """
    rng = rng or random.Random()
    sidecar = read_sidecar(tournament_root)
    if sidecar is None:
        raise FileNotFoundError(
            f"missing players_lookup.json at {tournament_root}; "
            f"re-run ingest with OCR enabled first"
        )

    status = StatusSidecar.load_or_init(
        tournament_root,
        tournament_id=tournament_id,
        season_number=season_number,
    )

    plan = build_plan(sidecar, status, force=force, only=only, limit=limit)
    if not apply or not plan:
        return status

    name_index = NameCodeIndex.from_mirror()
    name_to_code = {v.lower(): k for k, v in name_index.name_code_to_name.items()}

    deadline = time.monotonic() + max_minutes * 60
    last_home_nav = 0.0

    with _open_fetcher(fetcher, headless=headless,
                       detail_delay_range=detail_delay_range) as f:
        # Warm the origin so the SPA's cookie scope is correct for the
        # api.blablalink.com XHRs the search calls fire.
        try:
            f._page.goto(SITE_BASE + "/", wait_until="domcontentloaded")
            f._page.wait_for_timeout(1_500)
        except Exception as exc:  # noqa: BLE001
            log.warning("origin warm-up failed (%s) — continuing", exc)

        for i, entry in enumerate(plan):
            if time.monotonic() > deadline:
                log.warning(
                    "watchdog: max_minutes=%.1f exceeded at player %d/%d",
                    max_minutes, i, len(plan),
                )
                break

            if on_progress is not None:
                on_progress(ScrapeProgress(
                    index=i, total=len(plan), name=entry.name, stage="searching",
                ))

            try:
                match = search_and_verify_player(
                    f._page, entry.name, entry.expected_level,
                    tolerance=tolerance,
                )
            except Exception as exc:  # noqa: BLE001
                record = PlayerScrapeRecord(
                    name=entry.name, level=entry.expected_level,
                    status=STATUS_ERROR, error=f"search failed: {exc!r}",
                )
                status.players[entry.name] = record
                status.save(tournament_root)
                if on_progress is not None:
                    on_progress(ScrapeProgress(
                        index=i, total=len(plan), name=entry.name,
                        stage=STATUS_ERROR, record=record,
                    ))
                continue

            if match.status != "Found":
                status_value = {
                    "No Search Results": STATUS_NO_RESULTS,
                    "Not On NA": STATUS_NOT_ON_NA,
                    "Level Mismatch": STATUS_LEVEL_MISMATCH,
                }.get(match.status, STATUS_ERROR)
                record = PlayerScrapeRecord(
                    name=entry.name, level=entry.expected_level,
                    status=status_value,
                )
                status.players[entry.name] = record
                status.save(tournament_root)
                if on_progress is not None:
                    on_progress(ScrapeProgress(
                        index=i, total=len(plan), name=entry.name,
                        stage=status_value, record=record,
                    ))
                continue

            # Found — pace home navigations like a human browsing profiles.
            if last_home_nav > 0.0:
                target = rng.uniform(*home_pacing_range)
                elapsed = time.monotonic() - last_home_nav
                if elapsed < target:
                    time.sleep(target - elapsed)

            if on_progress is not None:
                on_progress(ScrapeProgress(
                    index=i, total=len(plan), name=entry.name, stage="fetching",
                ))

            uid_b64 = _uid_b64(match.intl_openid)
            try:
                home = f.fetch_home(uid_b64)
            except Exception as exc:  # noqa: BLE001
                record = PlayerScrapeRecord(
                    name=entry.name, level=entry.expected_level,
                    status=STATUS_ERROR, uid=uid_b64,
                    actual_level=match.actual_level,
                    error=f"home fetch failed: {exc!r}",
                )
                status.players[entry.name] = record
                status.save(tournament_root)
                continue
            last_home_nav = time.monotonic()

            # Build the target name_codes from the popup's OCR'd chars
            # — kept tight so each per-player scrape is ~5 detail navs,
            # not the full ~180 (per [[blablalink-scraper-behavior]]).
            target_codes: list[int] = []
            matched_names: list[str] = []
            if home.characters and not home.is_roster_private:
                owned_codes = {
                    int(c["name_code"]) for c in home.characters
                    if c.get("name_code") is not None
                }
                for char_name in entry.char_names:
                    code = name_to_code.get(char_name.lower())
                    if code is None or code not in owned_codes:
                        continue
                    target_codes.append(code)
                    matched_names.append(char_name)

            details = []
            if target_codes:
                if on_progress is not None:
                    on_progress(ScrapeProgress(
                        index=i, total=len(plan), name=entry.name,
                        stage="snapshotting",
                    ))
                try:
                    details = fetch_character_details(
                        uid_b64, target_codes,
                        name_code_to_resource_id=name_index.name_code_to_resource_id,
                        fetcher=f,
                    )
                except Exception as exc:  # noqa: BLE001
                    record = PlayerScrapeRecord(
                        name=entry.name, level=entry.expected_level,
                        status=STATUS_ERROR, uid=uid_b64,
                        actual_level=match.actual_level,
                        is_roster_private=home.is_roster_private,
                        is_outpost_private=home.is_outpost_private,
                        char_names_attempted=entry.char_names,
                        char_names_matched=matched_names,
                        error=f"detail fetch failed: {exc!r}",
                    )
                    status.players[entry.name] = record
                    status.save(tournament_root)
                    continue

            try:
                snap_report = sync_to_snapshot(
                    home, details,
                    season_number=season_number,
                    player_username=entry.name,
                    name_index=name_index,
                    db_path=db_path,
                )
            except Exception as exc:  # noqa: BLE001
                record = PlayerScrapeRecord(
                    name=entry.name, level=entry.expected_level,
                    status=STATUS_ERROR, uid=uid_b64,
                    actual_level=match.actual_level,
                    is_roster_private=home.is_roster_private,
                    is_outpost_private=home.is_outpost_private,
                    char_names_attempted=entry.char_names,
                    char_names_matched=matched_names,
                    error=f"snapshot write failed: {exc!r}",
                )
                status.players[entry.name] = record
                status.save(tournament_root)
                continue

            # Both private → no useful snapshot content; mark distinctly
            # so dashboards can show "scraped, nothing to learn".
            terminal_status = (
                STATUS_PRIVATE_BOTH
                if (home.is_roster_private and home.is_outpost_private)
                else STATUS_FOUND
            )
            record = PlayerScrapeRecord(
                name=entry.name,
                level=entry.expected_level,
                status=terminal_status,
                snapshot_id=snap_report.snapshot_id,
                snapshotted_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                actual_level=match.actual_level,
                uid=uid_b64,
                is_roster_private=home.is_roster_private,
                is_outpost_private=home.is_outpost_private,
                char_names_attempted=entry.char_names,
                char_names_matched=matched_names,
            )
            status.players[entry.name] = record
            status.save(tournament_root)

            if on_progress is not None:
                on_progress(ScrapeProgress(
                    index=i, total=len(plan), name=entry.name,
                    stage=terminal_status, record=record,
                ))

    return status


@contextmanager
def _open_fetcher(
    fetcher: Optional[ShiftyPadFetcher],
    *,
    headless: bool,
    detail_delay_range: tuple[float, float],
) -> Iterator[ShiftyPadFetcher]:
    if fetcher is not None:
        yield fetcher
        return
    with ShiftyPadFetcher(
        headless=headless, detail_delay_range=detail_delay_range,
    ) as f:
        yield f
