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

from ..data.models import (
    AccountState,
    ArenaMatch,
    Character,
    OwnedCharacter,
    PromoTournament,
    RookieArenaSnapshot,
    RookieArenaSnapshotCharacter,
)

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
    # User-side snapshot — populated when write_user_snapshot_for_tournament
    # is invoked (either by the live daemon hook after sync, or directly by
    # the manual backfill CLI).
    user_snapshot_id: Optional[int] = None
    user_snapshot_chars: int = 0


@dataclass
class UserSnapshotReport:
    tournament_id: int
    username: str
    snapshot_id: Optional[int] = None
    chars_written: int = 0
    chars_missing_owned: list[str] = field(default_factory=list)
    replaced_existing: bool = False
    skipped_reason: Optional[str] = None


def _build_owned_snapshot_payload(owned: OwnedCharacter) -> dict:
    """Render a minimal RookieArenaSnapshotCharacter.data dict from a
    live OwnedCharacter row.

    Only fields the simulator's stat predictor needs (and a couple of
    convenience keys for the validation UI). Marked with
    ``source="owned_backfill"`` so the validation page can distinguish
    a backfilled-from-OwnedCharacter snapshot from a live shiftyspad
    fetch (which carries richer fields like ol_gear and cube tids).
    """
    return {
        "sync_level": owned.sync_level,
        "core": owned.core,
        "limit_break": owned.limit_break,
        "skill1_level": owned.skill1_level,
        "skill2_level": owned.skill2_level,
        "burst_skill_level": owned.burst_skill_level,
        "power": owned.power,
        "bond_rank": owned.bond_rank,
        "arena_combat": owned.power,  # closest available proxy
        "source": "owned_backfill",
    }


def write_user_snapshot_for_tournament(
    session: Session,
    tournament: PromoTournament,
    *,
    username: str,
    intl_openid: Optional[str] = None,
) -> UserSnapshotReport:
    """Write (or replace) a ``RookieArenaSnapshot`` for the user side
    of a rookie tournament, sourced from current ``OwnedCharacter``.

    Idempotent: if a snapshot already exists for
    ``(run_date, username)`` the existing row is updated in-place and
    its per-character rows are replaced.

    Used by both the daemon hook (called after the
    OwnedCharacter sync completes) and the manual backfill CLI.
    """
    report = UserSnapshotReport(
        tournament_id=tournament.id, username=username,
    )
    names = collect_self_loadout_names(session, tournament)
    if not names:
        report.skipped_reason = "no-loadout-names"
        return report

    acct = session.exec(select(AccountState)).first()

    existing = session.exec(
        select(RookieArenaSnapshot).where(
            RookieArenaSnapshot.run_date == tournament.capture_date,
            RookieArenaSnapshot.player_username == username,
        )
    ).first()
    if existing is None:
        snap = RookieArenaSnapshot(
            run_date=tournament.capture_date,
            player_username=username,
            captured_at=datetime.now(timezone.utc),
            intl_openid=intl_openid,
            source_run_id=tournament.id,
            synchro_level=acct.synchro_level if acct else 1,
            general_research_level=acct.general_research_level if acct else 0,
            class_attacker_level=acct.class_attacker_level if acct else 0,
            class_defender_level=acct.class_defender_level if acct else 0,
            class_supporter_level=acct.class_supporter_level if acct else 0,
            mfr_pilgrim_level=acct.mfr_pilgrim_level if acct else 0,
            mfr_elysion_level=acct.mfr_elysion_level if acct else 0,
            mfr_tetra_level=acct.mfr_tetra_level if acct else 0,
            mfr_missilis_level=acct.mfr_missilis_level if acct else 0,
            mfr_abnormal_level=acct.mfr_abnormal_level if acct else 0,
            is_roster_private=False,
            is_outpost_private=False,
        )
        session.add(snap)
        session.flush()
    else:
        snap = existing
        snap.captured_at = datetime.now(timezone.utc)
        snap.source_run_id = tournament.id
        if intl_openid:
            snap.intl_openid = intl_openid
        if acct is not None:
            snap.synchro_level = acct.synchro_level
            snap.general_research_level = acct.general_research_level
            snap.class_attacker_level = acct.class_attacker_level
            snap.class_defender_level = acct.class_defender_level
            snap.class_supporter_level = acct.class_supporter_level
            snap.mfr_pilgrim_level = acct.mfr_pilgrim_level
            snap.mfr_elysion_level = acct.mfr_elysion_level
            snap.mfr_tetra_level = acct.mfr_tetra_level
            snap.mfr_missilis_level = acct.mfr_missilis_level
            snap.mfr_abnormal_level = acct.mfr_abnormal_level
        session.add(snap)
        report.replaced_existing = True
        # Drop existing per-char rows; we'll rewrite below.
        old = session.exec(
            select(RookieArenaSnapshotCharacter).where(
                RookieArenaSnapshotCharacter.snapshot_id == snap.id
            )
        ).all()
        for row in old:
            session.delete(row)
        session.flush()

    for name in names:
        row = session.exec(
            select(OwnedCharacter, Character)
            .where(OwnedCharacter.character_id == Character.id)
            .where(Character.name == name)
        ).first()
        if row is None:
            report.chars_missing_owned.append(name)
            continue
        owned, char = row
        session.add(RookieArenaSnapshotCharacter(
            snapshot_id=snap.id,
            character_id=char.id,
            data=_build_owned_snapshot_payload(owned),
        ))
        report.chars_written += 1

    session.commit()
    report.snapshot_id = snap.id
    return report


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

    # After OwnedCharacter is fresh from the BlablaLink fetch, write a
    # user-side RookieArenaSnapshot anchored to this tournament's date
    # — symmetric to the opponent snapshots we already write at ingest.
    # Sourced from OwnedCharacter (now just-refreshed in the same call)
    # so historical match-replay has accurate user roster state.
    from ..data.config import get_self_username

    username = get_self_username()
    if username:
        try:
            snap_report = write_user_snapshot_for_tournament(
                session, tournament,
                username=username, intl_openid=intl_openid,
            )
            report.user_snapshot_id = snap_report.snapshot_id
            report.user_snapshot_chars = snap_report.chars_written
        except Exception as exc:  # noqa: BLE001
            log.exception("user snapshot write failed: %s", exc)
            # Don't fail the whole refresh — OwnedCharacter is already
            # written; surface the error in the report.
            report.error = (report.error or "") + f"  user-snap: {exc!r}"
    else:
        log.info(
            "skipping user-snapshot write for tournament %s: no username configured",
            tournament.id,
        )

    _mark_refreshed(tournament.id, n_chars=len(target_codes))
    return report
