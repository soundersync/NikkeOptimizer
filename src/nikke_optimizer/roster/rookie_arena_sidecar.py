"""Per-run ``players_lookup.json`` sidecar for rookie arena scrapes.

Each daily rookie run produces one sidecar at the archive root:

  ``captures/rookie_arena/<YYYY-MM-DD>_<HHMMSS>/players_lookup.json``

The sidecar carries one record per UNIQUE opponent — deduped across
the run's 5 battles (same player can appear twice if they're in your
small Rookie Arena pool and you re-rolled the refresh). Each record
carries the player name, expected level + provenance chip, the 5
char names from their loadout, and the battle_no(s) where they
appeared.

Reads from the already-populated ``ArenaMatch`` rows (mode="rookie")
so it doesn't re-OCR — just denormalizes existing data into the
shape the scrape driver wants.

Mirrors the patterns in :mod:`promo_tournament_player_data`:

* Schema version + auto-invalidate on bump.
* Idempotent: written-once per (date, player) until the version
  changes or ``--force`` is passed.
* Status sibling sidecar (``players_lookup_status.json``) lives
  alongside; the scrape driver owns that one.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..data.models import ArenaMatch, PromoTournament

log = logging.getLogger(__name__)

SIDECAR_FILENAME = "players_lookup.json"
SIDECAR_VERSION = 1


@dataclass
class RookieOpponentRecord:
    """One unique opponent in a daily rookie run (deduped across battles)."""

    player_name: str
    expected_level: Optional[int]
    level_source: str                 # "opponent_png" | "estimated_from_my_level" | ...
    team: list[str]                   # 5 canonical char names (or fewer if OCR missed)
    battles: list[int]                # battle_no(s) where this opponent appeared
    source_screenshots: list[int] = field(default_factory=list)


@dataclass
class RookieSidecar:
    sidecar_version: int
    run_id: int                       # PromoTournament.id
    run_date: str                     # YYYY-MM-DD
    captured_at: str                  # ISO timestamp
    storage_root: str
    opponents: list[RookieOpponentRecord]


# ---------------------------------------------------------------------------
# Build from DB
# ---------------------------------------------------------------------------


def _session_id_for(tournament_id: int) -> str:
    return f"rookie-run-{tournament_id}"


def build_sidecar(session: Session, tournament: PromoTournament) -> RookieSidecar:
    """Construct the sidecar payload for one rookie tournament.

    Reads every ArenaMatch row for the session (one per battle), dedupes
    by ``opponent_username``, and merges battles when the same opponent
    appears more than once.
    """
    rows = session.exec(
        select(ArenaMatch).where(
            ArenaMatch.session_id == _session_id_for(tournament.id),
            ArenaMatch.mode == "rookie",
        ).order_by(ArenaMatch.round_index)
    ).all()

    # Dedupe by opponent_username. First-write-wins for the team data
    # (Rookie Arena opponents don't change teams within a run, so any
    # one battle's view is canonical for that opponent). Append all
    # battle_no's + source screenshot ids for audit traceability.
    by_name: dict[str, RookieOpponentRecord] = {}
    for am in rows:
        name = (am.opponent_username or "").strip()
        if not name:
            continue
        cq = am.capture_quality or {}
        level = cq.get("opponent_level")
        # When opponent.png missing OR weak match, fall back to my
        # player level (matchmade pair). The source chip lets the
        # scrape choose a wider tolerance.
        if level is None:
            level = cq.get("my_player_level")
        level_source = cq.get("opponent_level_source", "unknown")
        # ArenaMatch.opponent_team is a list[str] (padded with "" for
        # any slot the OCR missed). Drop empties for the scrape; the
        # full team's elsewhere if needed.
        team_canon = [n for n in (am.opponent_team or []) if n]

        rec = by_name.get(name)
        if rec is None:
            rec = RookieOpponentRecord(
                player_name=name,
                expected_level=level,
                level_source=level_source,
                team=team_canon,
                battles=[am.round_index],
            )
            by_name[name] = rec
        else:
            rec.battles.append(am.round_index)
            # If the first occurrence had no opponent.png but this one
            # does, prefer the precise level + source.
            if (
                rec.level_source != "opponent_png"
                and level_source == "opponent_png"
                and level is not None
            ):
                rec.expected_level = level
                rec.level_source = level_source
            # Merge teams — keep names from any battle (same opponent =
            # same team in Rookie Arena, but OCR may have caught
            # different slots cleanly on different battles).
            seen = set(rec.team)
            for n in team_canon:
                if n not in seen:
                    rec.team.append(n)
                    seen.add(n)

    opponents = sorted(by_name.values(), key=lambda r: r.player_name)
    return RookieSidecar(
        sidecar_version=SIDECAR_VERSION,
        run_id=tournament.id,
        run_date=tournament.capture_date.isoformat() if tournament.capture_date else "",
        captured_at=tournament.captured_at.isoformat(),
        storage_root=tournament.storage_root,
        opponents=opponents,
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def sidecar_path(tournament_root: Path) -> Path:
    return tournament_root / SIDECAR_FILENAME


def write_sidecar(tournament_root: Path, sidecar: RookieSidecar) -> Path:
    out = sidecar_path(tournament_root)
    out.write_text(json.dumps(asdict(sidecar), indent=2, sort_keys=True))
    return out


def read_sidecar(tournament_root: Path) -> Optional[RookieSidecar]:
    p = sidecar_path(tournament_root)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        log.warning("malformed rookie sidecar %s — treating as absent", p)
        return None
    opponents = [
        RookieOpponentRecord(**rec) for rec in raw.get("opponents", [])
    ]
    return RookieSidecar(
        sidecar_version=raw.get("sidecar_version", 1),
        run_id=raw["run_id"],
        run_date=raw.get("run_date", ""),
        captured_at=raw["captured_at"],
        storage_root=raw["storage_root"],
        opponents=opponents,
    )


def process_rookie_run(
    session: Session,
    tournament: PromoTournament,
    *,
    force: bool = False,
) -> Optional[Path]:
    """Build + persist the players_lookup.json sidecar for one rookie
    run. Idempotent — skips when the sidecar's version matches the
    current SIDECAR_VERSION unless ``force=True``.
    """
    storage_root = Path(tournament.storage_root)
    if not storage_root.is_dir():
        return None
    target = sidecar_path(storage_root)
    if target.is_file() and not force:
        try:
            existing_v = int(
                json.loads(target.read_text()).get("sidecar_version", 1)
            )
        except (json.JSONDecodeError, ValueError, OSError):
            existing_v = 1
        if existing_v == SIDECAR_VERSION:
            return None
        log.info(
            "regenerating rookie sidecar %s (version %d → %d)",
            target, existing_v, SIDECAR_VERSION,
        )

    sidecar = build_sidecar(session, tournament)
    return write_sidecar(storage_root, sidecar)
