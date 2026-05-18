"""Rookie Arena — BlablaLink lookup + RookieArenaSnapshot writer.

Per daily rookie run:

  1. Read ``players_lookup.json`` (built by ``rookie_arena_sidecar``).
  2. For each unique opponent: search → verify level → fetch home →
     fetch detail XHRs for the 5 Nikkes from their loadout → write
     ``RookieArenaSnapshot`` + per-char rows.
  3. Persist ``players_lookup_status.json`` after each opponent so
     mid-run interruption resumes cleanly on the next invocation.

Tolerance is **adaptive**: precise (±5) when the opponent's level
came from opponent.png, wide (±20) when estimated from my-level.

Reuses the privacy hardening from the player_data scrape:
``ShiftyPadFetcher.fetch_home`` already retries on missing
GetUserCharacters and applies conservative-private defaults.
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

from sqlmodel import Session, delete, select

from ..data.db import get_session, init_db, make_engine
from ..data.models import (
    Character,
    PromoTournament,
    RookieArenaSnapshot,
    RookieArenaSnapshotCharacter,
)
from ..data.scrapers.blablalink_user_lookup import (
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
from .rookie_arena_sidecar import (
    RookieOpponentRecord,
    RookieSidecar,
    read_sidecar,
)
from .shiftyspad_importer import (
    NameCodeIndex,
    _build_account_state_updates,
    _build_owned_kwargs_from_detail,
    _build_owned_kwargs_from_summary,
    _build_snapshot_char_payload,
    _find_character,
    _FuzzyReportShim,
    ShiftyPadReport,
)

log = logging.getLogger(__name__)

STATUS_SIDECAR_FILENAME = "players_lookup_status.json"
STATUS_SIDECAR_VERSION = 1

# Status values for the per-opponent record.
STATUS_FOUND = "found"
STATUS_NO_RESULTS = "no_results"
STATUS_NOT_ON_NA = "not_on_na"
STATUS_LEVEL_MISMATCH = "level_mismatch"
STATUS_PRIVATE_BOTH = "private_both"
STATUS_ERROR = "error"

# Tolerance bands keyed off the level provenance chip.
_TOLERANCE_PRECISE = 5         # level from opponent.png (this run)
_TOLERANCE_CROSS_RUN_CACHE = 10  # level from a prior successful scrape of same player
_TOLERANCE_ESTIMATED = 20      # level estimated from my own player level


# Level-source tag set when build_plan substitutes a cached
# actual_level from a prior successful scrape. Tighter tolerance
# than the my-level estimate; the assumption is a player's level
# doesn't drift more than ~10 across a few days of rookie play.
_LEVEL_SOURCE_CACHED = "cached_actual_level"


# ---------------------------------------------------------------------------
# Status sidecar
# ---------------------------------------------------------------------------


@dataclass
class RookieScrapeRecord:
    name: str
    expected_level: Optional[int]
    level_source: str
    status: str
    snapshot_id: Optional[int] = None
    snapshotted_at: Optional[str] = None
    actual_level: Optional[int] = None
    uid: Optional[str] = None
    is_roster_private: Optional[bool] = None
    is_outpost_private: Optional[bool] = None
    char_names_attempted: list[str] = field(default_factory=list)
    char_names_matched: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class RookieStatusSidecar:
    sidecar_version: int
    run_id: int
    run_date: str
    last_run_at: str
    players: dict[str, RookieScrapeRecord] = field(default_factory=dict)

    @classmethod
    def load_or_init(
        cls,
        tournament_root: Path,
        *,
        run_id: int,
        run_date: str,
    ) -> "RookieStatusSidecar":
        p = tournament_root / STATUS_SIDECAR_FILENAME
        if p.is_file():
            try:
                raw = json.loads(p.read_text())
                players = {
                    name: RookieScrapeRecord(**rec)
                    for name, rec in raw.get("players", {}).items()
                }
                return cls(
                    sidecar_version=raw.get("sidecar_version", STATUS_SIDECAR_VERSION),
                    run_id=raw.get("run_id", run_id),
                    run_date=raw.get("run_date", run_date),
                    last_run_at=raw.get("last_run_at", ""),
                    players=players,
                )
            except (json.JSONDecodeError, TypeError) as exc:
                log.warning("malformed status sidecar %s — rebuilding (%s)", p, exc)
        return cls(
            sidecar_version=STATUS_SIDECAR_VERSION,
            run_id=run_id,
            run_date=run_date,
            last_run_at="",
        )

    def save(self, tournament_root: Path) -> Path:
        self.last_run_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        p = tournament_root / STATUS_SIDECAR_FILENAME
        p.write_text(
            json.dumps(
                {
                    "sidecar_version": self.sidecar_version,
                    "run_id": self.run_id,
                    "run_date": self.run_date,
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
# Plan-building
# ---------------------------------------------------------------------------


@dataclass
class PlanEntry:
    name: str
    expected_level: int
    level_source: str
    tolerance: int
    char_names: list[str]


def _tolerance_for(level_source: str) -> int:
    if level_source == "opponent_png":
        return _TOLERANCE_PRECISE
    if level_source == _LEVEL_SOURCE_CACHED:
        return _TOLERANCE_CROSS_RUN_CACHE
    return _TOLERANCE_ESTIMATED


def _scan_rookie_runs_root(tournament_root: Path) -> Path:
    """Return the parent ``captures/rookie_arena/`` dir given any one
    run's root (``captures/rookie_arena/<date_TS>/``)."""
    return tournament_root.parent


def load_actual_level_cache(
    tournament_root: Path,
) -> dict[str, tuple[int, str]]:
    """Walk every other rookie run's status sidecar and build a
    ``{player_name: (actual_level, source_date)}`` cache from prior
    ``status=found`` records.

    Excludes the current run so the cache is strictly cross-run. When
    the same player appears in multiple sidecars, the MOST RECENT one
    wins (newer level reading is closer to current state — players
    drift up over time).

    Levels come from BlablaLink's ``GetUserGamePlayerInfo.player_level``
    (the canonical account level the search/verify step records on
    each Found row), NOT the synchro_level on the snapshot row (those
    are different values — synchro is the outpost device's max char
    level, player_level is the account level).
    """
    rookie_root = _scan_rookie_runs_root(tournament_root)
    if not rookie_root.is_dir():
        return {}
    cache: dict[str, tuple[int, str]] = {}
    for sibling in sorted(rookie_root.iterdir()):
        if not sibling.is_dir() or sibling == tournament_root:
            continue
        status_path = sibling / STATUS_SIDECAR_FILENAME
        if not status_path.is_file():
            continue
        try:
            raw = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            continue
        run_date = raw.get("run_date", "")
        for name, rec in (raw.get("players") or {}).items():
            if rec.get("status") != STATUS_FOUND:
                continue
            lv = rec.get("actual_level")
            if lv is None:
                continue
            try:
                lv_int = int(lv)
            except (TypeError, ValueError):
                continue
            # Most-recent date wins; ISO date strings sort correctly.
            existing = cache.get(name)
            if existing is None or run_date > existing[1]:
                cache[name] = (lv_int, run_date)
    return cache


def build_plan(
    sidecar: RookieSidecar,
    status: RookieStatusSidecar,
    *,
    force: bool = False,
    only: Optional[set[str]] = None,
    limit: Optional[int] = None,
    actual_level_cache: Optional[dict[str, tuple[int, str]]] = None,
) -> list[PlanEntry]:
    """Build the per-opponent scrape plan for one rookie run.

    ``actual_level_cache`` (player_name → (actual_level, source_date))
    lets us substitute a cached level from a prior successful scrape
    of the same player on a different run. When a cache hit exists
    AND the original level_source was ``estimated_from_my_level``,
    we override the expected_level + use a tighter tolerance — a
    given player's level shouldn't drift more than ~10 across a few
    days of rookie play, so ±10 (vs the ±20 my-level fallback) is
    safe and unblocks recurring opponents that the wide my-level
    band misses (e.g. RHUBARB at lv 733 misses 766±20 but hits
    733±10 once we've successfully scraped them once).

    Levels already sourced from opponent.png stay precise (±5); the
    cache only steps in when the original was an estimate.
    """
    only_norm = {n.strip().lower() for n in only} if only else None
    out: list[PlanEntry] = []
    for opp in sidecar.opponents:
        if not opp.player_name:
            continue
        if opp.expected_level is None:
            continue
        if only_norm is not None and opp.player_name.lower() not in only_norm:
            continue
        if not force:
            prior = status.players.get(opp.player_name)
            if prior is not None and prior.status == STATUS_FOUND:
                continue

        expected_level = opp.expected_level
        level_source = opp.level_source
        if (
            actual_level_cache is not None
            and opp.level_source != "opponent_png"
        ):
            cached = actual_level_cache.get(opp.player_name)
            if cached is not None:
                cached_lv, _cache_date = cached
                expected_level = cached_lv
                level_source = _LEVEL_SOURCE_CACHED

        out.append(PlanEntry(
            name=opp.player_name,
            expected_level=expected_level,
            level_source=level_source,
            tolerance=_tolerance_for(level_source),
            char_names=list(opp.team),
        ))
    out.sort(key=lambda e: e.name.lower())
    if limit is not None and limit >= 0:
        out = out[:limit]
    return out


# ---------------------------------------------------------------------------
# Snapshot writer — RookieArenaSnapshot + per-char rows
# ---------------------------------------------------------------------------


def _uid_b64(intl_openid: str) -> str:
    return base64.b64encode(intl_openid.encode()).decode()


def _write_snapshot(
    session: Session,
    *,
    run_tournament_id: int,
    run_date: _dt.date,
    player_username: str,
    intl_openid: str,
    home: HomePayload,
    details: list,
    name_index: NameCodeIndex,
) -> tuple[int, list[str]]:
    """Build a RookieArenaSnapshot + per-char rows. Replaces any prior
    snapshot for (run_date, player_username). Returns
    ``(snapshot_id, matched_char_names)``.
    """
    # Lookup all chars once for fuzzy resolution.
    all_chars = session.exec(select(Character)).all()
    all_names = [c.name for c in all_chars]

    detail_by_code: dict[int, Any] = {
        d.name_code: d for d in details if d.detail is not None
    }

    characters_to_write: list[tuple[int, dict]] = []
    matched_names: list[str] = []
    if home.characters and not home.is_roster_private:
        for summary in home.characters:
            try:
                name_code = int(summary["name_code"])
            except (KeyError, ValueError, TypeError):
                continue
            detail_payload = detail_by_code.get(name_code)
            if detail_payload is None or detail_payload.detail is None:
                continue  # sparse: skip chars we didn't fetch details for
            display_name = name_index.name_code_to_name.get(name_code)
            if not display_name:
                continue
            shim = _FuzzyReportShim(ShiftyPadReport())
            char = _find_character(
                session, display_name, all_names=all_names, report=shim,
            )
            if char is None:
                continue
            matched_names.append(char.name)
            kwargs = _build_owned_kwargs_from_summary(summary, char_id=char.id)
            kwargs.update(
                _build_owned_kwargs_from_detail(detail_payload.detail, char_id=char.id)
            )
            payload = _build_snapshot_char_payload(summary, detail_payload, kwargs)
            characters_to_write.append((char.id, payload))

    # Replace any prior snapshot for the same (run_date, player_username).
    existing = session.exec(
        select(RookieArenaSnapshot).where(
            RookieArenaSnapshot.run_date == run_date,
            RookieArenaSnapshot.player_username == player_username,
        )
    ).first()
    if existing is not None:
        session.exec(
            delete(RookieArenaSnapshotCharacter).where(
                RookieArenaSnapshotCharacter.snapshot_id == existing.id
            )
        )
        session.delete(existing)
        session.commit()

    snap = RookieArenaSnapshot(
        run_date=run_date,
        player_username=player_username,
        intl_openid=intl_openid,
        blablalink_nickname=(
            (home.basic_info or {}).get("nickname") if home.basic_info else None
        ),
        source_run_id=run_tournament_id,
        is_roster_private=bool(home.is_roster_private),
        is_outpost_private=bool(home.is_outpost_private),
        label="rookie_arena_scrape",
    )
    if home.outpost_info:
        for fld, val in _build_account_state_updates(home.outpost_info).items():
            if hasattr(snap, fld) and val is not None:
                setattr(snap, fld, int(val))
    session.add(snap)
    session.commit()
    session.refresh(snap)

    for char_id, payload in characters_to_write:
        session.add(RookieArenaSnapshotCharacter(
            snapshot_id=snap.id,
            character_id=char_id,
            data=payload,
        ))
    session.commit()

    return snap.id, matched_names


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class ScrapeProgress:
    index: int
    total: int
    name: str
    stage: str
    record: Optional[RookieScrapeRecord] = None


def scrape_rookie_run(
    tournament_root: Path,
    *,
    tournament: PromoTournament,
    apply: bool = False,
    only: Optional[set[str]] = None,
    force: bool = False,
    limit: Optional[int] = None,
    max_minutes: float = 90.0,
    headless: bool = True,
    detail_delay_range: tuple[float, float] = DEFAULT_DETAIL_DELAY_RANGE,
    home_pacing_range: tuple[float, float] = DEFAULT_DETAIL_DELAY_RANGE,
    fetcher: Optional[ShiftyPadFetcher] = None,
    db_path: Optional[Path] = None,
    on_progress: Optional[Callable[[ScrapeProgress], None]] = None,
    rng: Optional[random.Random] = None,
) -> RookieStatusSidecar:
    """Scrape one rookie run's opponents from BlablaLink, writing
    RookieArenaSnapshot rows. Idempotent via the status sidecar.

    ``apply=False`` is dry-run: builds the plan, prints/logs each
    entry, returns the status sidecar unchanged.
    """
    rng = rng or random.Random()
    sidecar = read_sidecar(tournament_root)
    if sidecar is None:
        raise FileNotFoundError(
            f"missing players_lookup.json at {tournament_root}; "
            f"re-run ingest first"
        )

    run_date = tournament.capture_date
    status = RookieStatusSidecar.load_or_init(
        tournament_root,
        run_id=tournament.id,
        run_date=run_date.isoformat() if run_date else "",
    )

    # Cross-run cache — substitute a tighter expected_level for
    # opponents we've already successfully scraped on a different day.
    actual_level_cache = load_actual_level_cache(tournament_root)

    plan = build_plan(
        sidecar, status,
        force=force, only=only, limit=limit,
        actual_level_cache=actual_level_cache,
    )
    if not apply or not plan:
        return status

    name_index = NameCodeIndex.from_mirror()
    name_to_code = {v.lower(): k for k, v in name_index.name_code_to_name.items()}

    deadline = time.monotonic() + max_minutes * 60
    last_home_nav = 0.0

    engine = make_engine(db_path)
    init_db(engine)

    with _open_fetcher(
        fetcher, headless=headless, detail_delay_range=detail_delay_range,
    ) as f:
        try:
            f._page.goto(SITE_BASE + "/", wait_until="domcontentloaded")
            f._page.wait_for_timeout(1_500)
        except Exception as exc:  # noqa: BLE001
            log.warning("origin warm-up failed (%s) — continuing", exc)

        for i, entry in enumerate(plan):
            if time.monotonic() > deadline:
                log.warning(
                    "watchdog: max_minutes=%.1f exceeded at opponent %d/%d",
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
                    tolerance=entry.tolerance,
                )
            except Exception as exc:  # noqa: BLE001
                rec = RookieScrapeRecord(
                    name=entry.name,
                    expected_level=entry.expected_level,
                    level_source=entry.level_source,
                    status=STATUS_ERROR,
                    error=f"search failed: {exc!r}",
                )
                status.players[entry.name] = rec
                status.save(tournament_root)
                continue

            if match.status != "Found":
                status_value = {
                    "No Search Results": STATUS_NO_RESULTS,
                    "Not On NA": STATUS_NOT_ON_NA,
                    "Level Mismatch": STATUS_LEVEL_MISMATCH,
                }.get(match.status, STATUS_ERROR)
                rec = RookieScrapeRecord(
                    name=entry.name,
                    expected_level=entry.expected_level,
                    level_source=entry.level_source,
                    status=status_value,
                )
                status.players[entry.name] = rec
                status.save(tournament_root)
                if on_progress is not None:
                    on_progress(ScrapeProgress(
                        index=i, total=len(plan), name=entry.name,
                        stage=status_value, record=rec,
                    ))
                continue

            # Found — pace home navigations like a human.
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
                rec = RookieScrapeRecord(
                    name=entry.name,
                    expected_level=entry.expected_level,
                    level_source=entry.level_source,
                    status=STATUS_ERROR, uid=uid_b64,
                    actual_level=match.actual_level,
                    error=f"home fetch failed: {exc!r}",
                )
                status.players[entry.name] = rec
                status.save(tournament_root)
                continue
            last_home_nav = time.monotonic()

            # Build target name_codes from the loadout names — tight
            # 5-char fetch (per [[blablalink-scraper-behavior]] memory).
            target_codes: list[int] = []
            matched_for_fetch: list[str] = []
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
                    matched_for_fetch.append(char_name)

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
                    rec = RookieScrapeRecord(
                        name=entry.name,
                        expected_level=entry.expected_level,
                        level_source=entry.level_source,
                        status=STATUS_ERROR, uid=uid_b64,
                        actual_level=match.actual_level,
                        is_roster_private=home.is_roster_private,
                        is_outpost_private=home.is_outpost_private,
                        char_names_attempted=entry.char_names,
                        char_names_matched=matched_for_fetch,
                        error=f"detail fetch failed: {exc!r}",
                    )
                    status.players[entry.name] = rec
                    status.save(tournament_root)
                    continue

            try:
                with get_session(engine) as session:
                    snap_id, written_names = _write_snapshot(
                        session,
                        run_tournament_id=tournament.id,
                        run_date=run_date,
                        player_username=entry.name,
                        intl_openid=match.intl_openid,
                        home=home,
                        details=details,
                        name_index=name_index,
                    )
            except Exception as exc:  # noqa: BLE001
                rec = RookieScrapeRecord(
                    name=entry.name,
                    expected_level=entry.expected_level,
                    level_source=entry.level_source,
                    status=STATUS_ERROR, uid=uid_b64,
                    actual_level=match.actual_level,
                    is_roster_private=home.is_roster_private,
                    is_outpost_private=home.is_outpost_private,
                    char_names_attempted=entry.char_names,
                    char_names_matched=matched_for_fetch,
                    error=f"snapshot write failed: {exc!r}",
                )
                status.players[entry.name] = rec
                status.save(tournament_root)
                continue

            terminal_status = (
                STATUS_PRIVATE_BOTH
                if (home.is_roster_private and home.is_outpost_private)
                else STATUS_FOUND
            )
            rec = RookieScrapeRecord(
                name=entry.name,
                expected_level=entry.expected_level,
                level_source=entry.level_source,
                status=terminal_status,
                snapshot_id=snap_id,
                snapshotted_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                actual_level=match.actual_level,
                uid=uid_b64,
                is_roster_private=home.is_roster_private,
                is_outpost_private=home.is_outpost_private,
                char_names_attempted=entry.char_names,
                char_names_matched=written_names,
            )
            status.players[entry.name] = rec
            status.save(tournament_root)

            if on_progress is not None:
                on_progress(ScrapeProgress(
                    index=i, total=len(plan), name=entry.name,
                    stage=terminal_status, record=rec,
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
