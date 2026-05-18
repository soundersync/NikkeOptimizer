"""Player-data sidecar.

After the OCR pass populates ``PromoExtractedField`` rows for every
``kind="player_data"`` screenshot (using the shared ``PLAYER_LOADOUT``
region schema — see ``promo_tournament_regions.py``), this module
groups the rows by screenshot and writes one ``players_lookup.json``
sidecar per tournament. The sidecar is the structured input for the
BlablaLink lookup + snapshot scrape (Slice 3) and is also the easiest
artifact for a human to eyeball OCR quality.

Sibling pattern to :mod:`league_leaderboard`:
* OCR runs once → DB rows.
* This module groups + serializes them to JSON next to the source PNGs.
* Idempotent — skip when the sidecar exists unless ``force=True``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..data.models import (
    Character,
    PromoExtractedField,
    PromoGroup,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
)

log = logging.getLogger(__name__)

SIDECAR_FILENAME = "players_lookup.json"

# Bump on any incompatible sidecar schema change. Existing sidecars
# with a different (or missing) version field are auto-invalidated on
# the next ingest pass — no need to remember --force-ocr.
#   1 → original single-popup format (one PlayerRecord per screenshot)
#   2 → per-player aggregation (union chars across rounds)
#   3 → per-round teams[] preserved alongside the chars union
SIDECAR_VERSION = 3


@dataclass
class CharSlot:
    """One of the five character cards in a player-data popup."""

    slot: int                     # 1..5
    name: Optional[str]           # canonical Character.name (fuzzy-matched)
    name_raw: Optional[str]       # raw OCR text from the name region
    name_match_score: Optional[float]
    cp: Optional[int]
    lb: Optional[int]             # 0..3 stars
    core: Optional[str]           # "01".."07" / "MAX" / None when no badge


@dataclass
class RoundTeam:
    """One round's 5-Nikke team selection."""

    round_no: int                 # 1..5
    screenshot_id: int            # source PNG
    team_cp: Optional[int]
    chars: list[CharSlot]         # always 5 (some may have name=None on OCR miss)


@dataclass
class PlayerRecord:
    """Aggregated popup data for one player across all of their per-round
    Arena Info screenshots.

    The capture format writes 5 PNGs per (match, side) — one per
    round — and each round is a different team selection. The sidecar
    collapses those into ONE record per player carrying BOTH the
    deduped union of characters (for the scrape's ``--names`` filter)
    AND the per-round breakdown (for the UI's "Team 1 / 2 / ..." view).

    Header fields (player_name, player_level) come from the highest-
    confidence single round. ``team_cp`` is the max across rounds.
    ``chars`` is the deduped union of canonical character names
    (typically 5-25 unique entries). ``teams`` is the per-round
    breakdown — 5 ``RoundTeam`` entries, each carrying its own 5
    chars and team_cp. ``source_screenshots`` mirrors the union for
    a quick "all sources for this player" lookup.
    """

    group_no: int
    match_no: int
    side: str                     # "top" | "bottom"
    screenshot_id: int            # best-round screenshot id (for the default audit link)
    # Pre-aggregation: this is the round_no of the single source PNG
    # the builder is reading; aggregated records leave it None and
    # carry per-round detail in ``teams``.
    round_no: Optional[int] = None
    source_screenshots: list[int] = field(default_factory=list)
    player_name: Optional[str] = None
    player_name_confidence: Optional[float] = None
    player_level: Optional[int] = None
    team_cp: Optional[int] = None
    chars: list[CharSlot] = field(default_factory=list)
    teams: list[RoundTeam] = field(default_factory=list)


@dataclass
class PlayerDataSidecar:
    season_number: Optional[int]
    tournament_id: int
    storage_root: str
    players: list[PlayerRecord]
    sidecar_version: int = SIDECAR_VERSION


# ---------------------------------------------------------------------------
# Field extraction from PromoExtractedField rows
# ---------------------------------------------------------------------------


def _fields_by_slug(
    session: Session, screenshot_id: int
) -> dict[str, PromoExtractedField]:
    rows = session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.screenshot_id == screenshot_id
        )
    ).all()
    return {r.region_slug: r for r in rows}


def _as_int(text: Optional[str]) -> Optional[int]:
    if text is None:
        return None
    try:
        return int(text)
    except (ValueError, TypeError):
        return None


def _build_char_slot(
    slot: int,
    by_slug: dict[str, PromoExtractedField],
    char_name_by_id: dict[int, str],
) -> CharSlot:
    name_row = by_slug.get(f"char{slot}.name")
    cp_row = by_slug.get(f"char{slot}.cp")
    lb_row = by_slug.get(f"char{slot}.lb_core")

    canonical_name: Optional[str] = None
    name_raw: Optional[str] = None
    score: Optional[float] = None
    if name_row is not None:
        name_raw = name_row.text
        score = name_row.character_match_score
        if name_row.character_id is not None:
            canonical_name = char_name_by_id.get(name_row.character_id)

    cp = _as_int(cp_row.normalized) if cp_row is not None else None

    # lb_core normalized form is "L<stars>C<core>" (e.g. "L3CMAX"); see
    # promo_tournament_lb_core.detect_lb_core. Parse defensively.
    lb: Optional[int] = None
    core: Optional[str] = None
    if lb_row is not None and lb_row.normalized:
        norm = lb_row.normalized
        if norm.startswith("L") and "C" in norm:
            try:
                lb = int(norm[1 : norm.index("C")])
            except ValueError:
                pass
            core_part = norm.split("C", 1)[1]
            core = core_part or None

    return CharSlot(
        slot=slot,
        name=canonical_name,
        name_raw=name_raw,
        name_match_score=score,
        cp=cp,
        lb=lb,
        core=core,
    )


def aggregate_per_player(records: list[PlayerRecord]) -> list[PlayerRecord]:
    """Collapse per-screenshot records into one record per player.

    The new player_data capture writes 5 rounds × 2 sides per match, so
    each player has up to 5 source screenshots (one per round). Groups
    by ``(group_no, match_no, side)`` — the natural "this is one
    player's bracket slot" key — rather than by ``player_name`` so we
    don't get fooled by OCR jitter producing slightly different name
    spellings across rounds for the same player.

    Within a group:
    * Header fields (``player_name``, ``player_level``,
      ``player_name_confidence``, ``screenshot_id``) come from the
      best-confidence round.
    * ``team_cp`` is the **max** across rounds — each round has its
      own team with its own CP; max is the "strongest team" signal.
    * ``chars`` is the deduped union (by canonical name) across all
      rounds — the set the scrape needs to pass to
      ``fetch-shiftyspad --names``. CharSlot ``slot`` is reset to a
      1-based index within the union list.
    * ``source_screenshots`` is the sorted list of all per-round
      screenshot ids so the audit UI can link back to any of them.
    """
    bucket: dict[tuple[int, int, str], list[PlayerRecord]] = {}
    for r in records:
        bucket.setdefault((r.group_no, r.match_no, r.side), []).append(r)

    aggregated: list[PlayerRecord] = []
    for (g, m, s), group in bucket.items():
        # Pick the best round for header fields — highest confidence
        # wins, ties broken by lowest screenshot_id for determinism.
        best = max(
            group,
            key=lambda r: (r.player_name_confidence or 0.0, -r.screenshot_id),
        )
        # Max team CP across rounds (each round has its own team).
        team_cps = [r.team_cp for r in group if r.team_cp is not None]
        max_team_cp = max(team_cps) if team_cps else None
        # Union chars by canonical name (skip None / unresolved).
        seen: set[str] = set()
        union_chars: list[CharSlot] = []
        for r in sorted(group, key=lambda r: r.screenshot_id):
            for c in r.chars:
                if c.name and c.name not in seen:
                    seen.add(c.name)
                    union_chars.append(CharSlot(
                        slot=len(union_chars) + 1,
                        name=c.name,
                        name_raw=c.name_raw,
                        name_match_score=c.name_match_score,
                        cp=c.cp,
                        lb=c.lb,
                        core=c.core,
                    ))
        # Per-round breakdown for the UI's "Team 1/2/3/..." display.
        # Order by round_no (then screenshot_id as a deterministic
        # fallback when round_no is missing).
        teams_sorted = sorted(
            group,
            key=lambda r: (r.round_no if r.round_no is not None else 99, r.screenshot_id),
        )
        teams = [
            RoundTeam(
                round_no=r.round_no if r.round_no is not None else (idx + 1),
                screenshot_id=r.screenshot_id,
                team_cp=r.team_cp,
                chars=list(r.chars),
            )
            for idx, r in enumerate(teams_sorted)
        ]
        aggregated.append(PlayerRecord(
            group_no=g,
            match_no=m,
            side=s,
            screenshot_id=best.screenshot_id,
            round_no=None,  # aggregated record — per-round detail lives in teams[]
            source_screenshots=sorted(r.screenshot_id for r in group),
            player_name=best.player_name,
            player_name_confidence=best.player_name_confidence,
            player_level=best.player_level,
            team_cp=max_team_cp,
            chars=union_chars,
            teams=teams,
        ))
    return aggregated


def build_player_record(
    session: Session,
    screenshot: PromoMatchScreenshot,
    match: PromoMatch,
    group: PromoGroup,
    char_name_by_id: dict[int, str],
) -> PlayerRecord:
    """Group all OCR rows for one screenshot into a PlayerRecord."""
    by_slug = _fields_by_slug(session, screenshot.id)

    name_row = by_slug.get("player_name")
    level_row = by_slug.get("player_level")
    cp_row = by_slug.get("team_cp")

    return PlayerRecord(
        group_no=group.group_no,
        match_no=match.match_no or 0,
        side=screenshot.side or "?",
        screenshot_id=screenshot.id,
        round_no=screenshot.round_no,
        player_name=(name_row.text if name_row is not None else None),
        player_name_confidence=(
            name_row.confidence if name_row is not None else None
        ),
        player_level=(
            _as_int(level_row.normalized) if level_row is not None else None
        ),
        team_cp=(_as_int(cp_row.normalized) if cp_row is not None else None),
        chars=[
            _build_char_slot(i, by_slug, char_name_by_id)
            for i in range(1, 6)
        ],
    )


# ---------------------------------------------------------------------------
# Sidecar I/O
# ---------------------------------------------------------------------------


def sidecar_path(tournament_root: Path) -> Path:
    return tournament_root / SIDECAR_FILENAME


def write_sidecar(tournament_root: Path, sidecar: PlayerDataSidecar) -> Path:
    out = sidecar_path(tournament_root)
    out.write_text(json.dumps(asdict(sidecar), indent=2, sort_keys=True))
    return out


def read_sidecar(tournament_root: Path) -> Optional[PlayerDataSidecar]:
    """Read + deserialize a sidecar. ``None`` when missing or malformed.

    Tolerant of older sidecar versions on read (the player_data scrape
    + UI both want to keep working against pre-existing files); the
    ingest pass's regeneration is what enforces version freshness.
    """
    p = sidecar_path(tournament_root)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        log.warning("malformed sidecar %s — treating as absent", p)
        return None
    def _to_record(row: dict) -> PlayerRecord:
        # ``teams`` carries nested CharSlot dicts; strip both nested
        # fields off before splatting the rest into PlayerRecord(**...).
        teams_raw = row.get("teams", []) or []
        teams = [
            RoundTeam(
                round_no=t["round_no"],
                screenshot_id=t["screenshot_id"],
                team_cp=t.get("team_cp"),
                chars=[CharSlot(**c) for c in (t.get("chars", []) or [])],
            )
            for t in teams_raw
        ]
        chars = [CharSlot(**c) for c in row.get("chars", [])]
        return PlayerRecord(
            **{k: v for k, v in row.items() if k not in ("chars", "teams")},
            chars=chars,
            teams=teams,
        )

    players = [_to_record(row) for row in raw.get("players", [])]
    return PlayerDataSidecar(
        season_number=raw.get("season_number"),
        tournament_id=raw["tournament_id"],
        storage_root=raw["storage_root"],
        players=players,
        sidecar_version=raw.get("sidecar_version", 1),
    )


# ---------------------------------------------------------------------------
# Per-tournament driver
# ---------------------------------------------------------------------------


def process_player_data_tournament(
    session: Session,
    tournament: PromoTournament,
    *,
    season_number: Optional[int] = None,
    force: bool = False,
) -> Optional[Path]:
    """Build + persist the players_lookup.json sidecar for one tournament.

    Returns the sidecar path on write, or ``None`` when the sidecar
    already exists and ``force=False``.
    """
    storage_root = Path(tournament.storage_root)
    if not storage_root.is_dir():
        return None
    target = sidecar_path(storage_root)
    if target.is_file() and not force:
        # Auto-invalidate when the file is from an older schema —
        # avoids the "stale sidecar shape" foot-gun.
        try:
            existing_version = int(
                json.loads(target.read_text()).get("sidecar_version", 1)
            )
        except (json.JSONDecodeError, ValueError, OSError):
            existing_version = 1
        if existing_version == SIDECAR_VERSION:
            return None
        log.info(
            "regenerating sidecar %s (version %d → %d)",
            target, existing_version, SIDECAR_VERSION,
        )

    char_name_by_id = {c.id: c.name for c in session.exec(select(Character)).all()}

    groups = session.exec(
        select(PromoGroup).where(PromoGroup.tournament_id == tournament.id)
    ).all()
    group_by_id = {g.id: g for g in groups}

    matches = session.exec(
        select(PromoMatch).where(PromoMatch.tournament_id == tournament.id)
    ).all()
    match_by_id = {m.id: m for m in matches}
    match_ids = list(match_by_id.keys())
    if not match_ids:
        return None

    shots = session.exec(
        select(PromoMatchScreenshot).where(
            PromoMatchScreenshot.match_id.in_(match_ids),
            # ``player_data`` tournaments now use the same kind value
            # as regular promo tournament loadout screens — the source
            # distinction lives in the tournament's storage_root, not
            # at the screenshot level. See Option B in the player_data
            # refactor notes.
            PromoMatchScreenshot.kind == "player_loadout",
        )
    ).all()

    per_screenshot: list[PlayerRecord] = []
    for shot in shots:
        match = match_by_id.get(shot.match_id)
        if match is None:
            continue
        group = group_by_id.get(match.group_id)
        if group is None:
            continue
        per_screenshot.append(
            build_player_record(session, shot, match, group, char_name_by_id)
        )

    # Aggregate the per-round screenshots into one record per player
    # (5 rounds × 1 side per player slot → 1 union'd record).
    records = aggregate_per_player(per_screenshot)

    # Stable sort: group → match → side. Makes hand-eyeballing easy and
    # the JSON deterministic so re-running on unchanged data is a no-op
    # at the bytes level (good for git noise + caching).
    records.sort(key=lambda r: (r.group_no, r.match_no, r.side))

    sidecar = PlayerDataSidecar(
        season_number=season_number,
        tournament_id=tournament.id,
        storage_root=str(storage_root),
        players=records,
    )
    return write_sidecar(storage_root, sidecar)
