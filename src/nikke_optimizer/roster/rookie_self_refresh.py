"""Sparse OwnedCharacter refresh from rookie-arena loadouts.

After each daily rookie run, the user has played 5 1v1 battles with
known loadouts. This module harvests the unique Nikke names from
those battles (typically ~5-10 unique chars across the run) and runs
a sparse ShiftyPad fetch for just those characters, so OwnedCharacter
rows stay fresh on a daily cadence without manual fetch-shiftyspad
CSV imports.

Cost: ~15-35s per run (one fetch_home + delay_lo..delay_hi seconds
per unique char in target_codes). Gated on:
  - ``config.json`` has ``intl_openid`` set (or env ``NIKKE_OPTIMIZER_UID``)
  - BlablaLink cookies present (caller's responsibility — daemon
    probes this once already via ``_blablalink_cookies_present``)
  - The tournament hasn't been self-refreshed yet (per-tournament
    cooldown state at ``<user_data_dir>/state/rookie_self_refresh.json``)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir
from sqlmodel import Session, select

from ..data.models import ArenaMatch, PromoTournament

log = logging.getLogger(__name__)

_APP_NAME = "NikkeOptimizer"
_STATE_DIR = Path(user_data_dir(_APP_NAME, appauthor=False)) / "state"
_STATE_FILE = _STATE_DIR / "rookie_self_refresh.json"


@dataclass
class SelfRefreshReport:
    tournament_id: int
    chars_targeted: list[str] = field(default_factory=list)
    chars_unmapped: list[str] = field(default_factory=list)
    chars_matched_in_sync: int = 0
    chars_updated: int = 0
    profile_lookup_failed: bool = False
    error: Optional[str] = None
    skipped_reason: Optional[str] = None


def collect_self_loadout_names(
    session: Session, tournament: PromoTournament,
) -> list[str]:
    """Union of unique non-empty names from ``user_team`` across all
    ArenaMatch rows linked to this rookie tournament. Order preserved
    by first appearance — deterministic for tests and audit logs.

    Rookie ArenaMatch rows are keyed by the synthetic
    ``session_id = "rookie-run-{tournament_id}"`` produced by
    ``rookie_arena_arena_match.session_id_for_run``.
    """
    from .rookie_arena_arena_match import session_id_for_run

    seen: dict[str, None] = {}
    sid = session_id_for_run(tournament.id)
    rows = session.exec(
        select(ArenaMatch).where(ArenaMatch.session_id == sid)
    ).all()
    for row in rows:
        for name in (row.user_team or []):
            n = (name or "").strip()
            if n and n not in seen:
                seen[n] = None
    return list(seen.keys())


def _load_state() -> dict:
    if not _STATE_FILE.is_file():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def _mark_refreshed(tournament_id: int, *, n_chars: int) -> None:
    state = _load_state()
    state[str(tournament_id)] = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "n_chars": n_chars,
    }
    _save_state(state)


def already_refreshed(tournament_id: int) -> bool:
    return str(tournament_id) in _load_state()


def refresh_self_from_rookie_tournament(
    session: Session,
    tournament: PromoTournament,
    *,
    intl_openid: str,
    db_path: Optional[Path] = None,
    delay_range: tuple[float, float] = (3.0, 7.0),
    force: bool = False,
) -> SelfRefreshReport:
    """Sparse ShiftyPad fetch+sync for the user, restricted to the
    unique Nikke names found in this rookie run's loadouts.

    Always writes (``apply=True``) — this is a daemon hook whose
    purpose is to update OwnedCharacter rows. Idempotent via the
    per-tournament cooldown state.
    """
    from ..roster.promo_tournament_ingest import (
        FORMAT_ROOKIE_ARENA, tournament_format,
    )

    report = SelfRefreshReport(tournament_id=tournament.id)
    if tournament_format(Path(tournament.storage_root)) != FORMAT_ROOKIE_ARENA:
        report.skipped_reason = "not-a-rookie-tournament"
        return report
    if not force and already_refreshed(tournament.id):
        report.skipped_reason = "already-refreshed"
        return report

    names = collect_self_loadout_names(session, tournament)
    if not names:
        report.skipped_reason = "no-loadout-names"
        return report
    report.chars_targeted = names

    from ..data.scrapers.shiftyspad import (
        ShiftyPadFetcher,
        fetch_character_details,
    )
    from .shiftyspad_importer import NameCodeIndex, sync

    name_index = NameCodeIndex.from_mirror()
    name_to_code = {v.lower(): k for k, v in name_index.name_code_to_name.items()}

    target_codes: list[int] = []
    for n in names:
        code = name_to_code.get(n.lower())
        if code is None:
            report.chars_unmapped.append(n)
        else:
            target_codes.append(code)
    if not target_codes:
        report.skipped_reason = "no-mappable-names"
        return report

    try:
        with ShiftyPadFetcher(
            headless=True, detail_delay_range=delay_range,
        ) as f:
            home = f.fetch_home(intl_openid)
            if not home.basic_info and not home.characters:
                report.profile_lookup_failed = True
                report.skipped_reason = "fetch-home-empty"
                return report
            roster_codes = {
                int(c["name_code"]) for c in home.characters
                if c.get("name_code") is not None
            }
            effective_codes = [c for c in target_codes if c in roster_codes]
            details = (
                fetch_character_details(
                    intl_openid, effective_codes,
                    name_code_to_resource_id=name_index.name_code_to_resource_id,
                    fetcher=f,
                )
                if effective_codes else []
            )
    except Exception as exc:  # noqa: BLE001
        log.exception("self-refresh fetch failed: %s", exc)
        report.error = repr(exc)
        return report

    try:
        sync_report = sync(
            home, details,
            name_index=name_index, db_path=db_path, apply=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("self-refresh sync failed: %s", exc)
        report.error = repr(exc)
        return report

    report.chars_matched_in_sync = sync_report.matched
    report.chars_updated = sum(
        1 for d in sync_report.diffs if d.changes or d.is_new
    )
    _mark_refreshed(tournament.id, n_chars=len(target_codes))
    return report
