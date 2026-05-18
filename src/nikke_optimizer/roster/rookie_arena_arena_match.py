"""Bridge rookie-arena ingest data into ``ArenaMatch`` rows.

Each rookie battle yields one ``ArenaMatch`` row (mode="rookie")
populated from the PromoExtractedField rows the OCR pass wrote for
the battle's loadout.png + opponent.png. Natural key for upsert is
``(session_id, round_index)`` where ``session_id`` =
``"rookie-run-{tournament_id}"`` and ``round_index`` = battle_no.

Rookie-specific data that doesn't have first-class ArenaMatch columns
(per-Nikke levels, LB/Core, opponent level + provenance) lands in
``capture_quality`` as a structured dict — easy to promote to columns
later if needed.

Hooked into ``rookie_arena_ingest.ingest_rookie_root`` as a pass that
runs after OCR. Standalone CLI ``build-rookie-arena-matches`` would
also be useful for re-running just this pass, but it's not strictly
needed (the natural-key upsert makes re-ingest idempotent).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from ..data.models import (
    ArenaMatch,
    Character,
    PromoExtractedField,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
)
from .rookie_arena_match import (
    LevelSource,
    match_opponent_card,
    opponent_level_source,
    resolve_my_level,
)

log = logging.getLogger(__name__)


def session_id_for_run(tournament_id: int) -> str:
    """Stable session_id for one rookie daily run."""
    return f"rookie-run-{tournament_id}"


# ---------------------------------------------------------------------------
# Field readers — pull typed values out of PromoExtractedField rows.
# ---------------------------------------------------------------------------


def _fields_by_slug(
    session: Session, screenshot_id: int,
) -> dict[str, PromoExtractedField]:
    rows = session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.screenshot_id == screenshot_id,
        )
    ).all()
    return {r.region_slug: r for r in rows}


def _as_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _read_team(
    by_slug: dict[str, PromoExtractedField],
    side: str,
    char_name_by_id: dict[int, str],
) -> tuple[list[Optional[str]], list[Optional[int]], list[Optional[str]]]:
    """Read 5 (canonical_name, level, lb_core) entries for one side
    of a rookie loadout. ``side`` is ``"opp"`` or ``"my"``."""
    names: list[Optional[str]] = []
    levels: list[Optional[int]] = []
    lb_cores: list[Optional[str]] = []
    for slot in range(1, 6):
        nrow = by_slug.get(f"{side}.char{slot}.name")
        lrow = by_slug.get(f"{side}.char{slot}.level")
        brow = by_slug.get(f"{side}.char{slot}.lb_core")
        if nrow is not None and nrow.character_id is not None:
            names.append(char_name_by_id.get(nrow.character_id))
        else:
            names.append(None)
        levels.append(
            _as_int(lrow.normalized) if lrow is not None else None
        )
        lb_cores.append(
            (brow.normalized if brow is not None else None)
        )
    return names, levels, lb_cores


def _read_battle_records_names(
    by_slug: dict[str, PromoExtractedField],
    side: str,
    char_name_by_id: dict[int, str],
) -> list[Optional[str]]:
    """Read 5 character names from a Battle Records screen for one
    side. ``side`` is ``"left"`` (my team) or ``"right"`` (opponent).

    Battle Records is the post-match screen — text is ~3× larger than
    the loadout's popup, so OCR + fuzzy matching is dramatically more
    reliable. Used as the AUTHORITATIVE source of character names; the
    loadout's per-slot name is only consulted when the battle-records
    pass missed (rare).
    """
    out: list[Optional[str]] = []
    for slot in range(1, 6):
        nrow = by_slug.get(f"{side}.char{slot}.name")
        if nrow is not None and nrow.character_id is not None:
            out.append(char_name_by_id.get(nrow.character_id))
        else:
            out.append(None)
    return out


def _merge_names(
    primary: list[Optional[str]],
    fallback: list[Optional[str]],
) -> tuple[list[Optional[str]], list[str]]:
    """Per-slot prefer the primary name; fall back to ``fallback``
    when primary is None. Returns ``(merged, sources)`` where
    ``sources[i]`` is one of ``"primary"`` / ``"fallback"`` /
    ``"missing"`` for audit.
    """
    merged: list[Optional[str]] = []
    sources: list[str] = []
    for p, f in zip(primary, fallback):
        if p:
            merged.append(p)
            sources.append("primary")
        elif f:
            merged.append(f)
            sources.append("fallback")
        else:
            merged.append(None)
            sources.append("missing")
    return merged, sources


# ---------------------------------------------------------------------------
# Build payload from one PromoMatch
# ---------------------------------------------------------------------------


@dataclass
class _RookieBattlePayload:
    """All the data we extract from one rookie battle's OCR fields,
    ready to drop into an ArenaMatch row."""

    user_username: Optional[str]
    opponent_username: Optional[str]
    user_team: list[str]              # only matched (non-None) names
    opponent_team: list[str]
    user_power: Optional[int]
    opponent_power: Optional[int]
    pre_battle_screenshot: Optional[str]
    battle_record_screenshot: Optional[str]
    capture_quality: dict
    # Derived from the 10 `(left|right).char{N}.disconnect` OCR
    # fields on the results_duel screenshot. The "DISCONNECTED"
    # badge marks a Nikke as **defeated/wiped** (NOT network-
    # disconnected — confirmed with user 2026-05-18). "loss" iff
    # user side (left) shows 5/5 wiped, "win" iff opponent side
    # (right) shows 5/5. None means OCR data-quality issue —
    # Rookie Arena has no ties and no observed timeouts, so every
    # real match should resolve to win/loss.
    outcome: Optional[str] = None
    # Internal — surfaces the loadout's screenshot id + the canonical
    # per-slot team lists so upsert_arena_match can backfill the
    # loadout's char.name character_ids with the authoritative names.
    loadout_screenshot_id: Optional[int] = None
    canonical_my_team: list[Optional[str]] = field(default_factory=list)
    canonical_opp_team: list[Optional[str]] = field(default_factory=list)


def _is_disconnect_text(text: Optional[str]) -> bool:
    """Lenient substring check for the DISCONNECTED overlay text.

    **Naming note**: the badge says literally "DISCONNECTED" but in
    NIKKE's UI semantics it means **"this Nikke was defeated/wiped"**,
    NOT "the player lost their network connection." Slug/function
    names match the literal badge text the OCR sees; the per-side
    aggregator (`_outcome_from_disconnects`) treats 5/5 as "team
    wiped → that side lost."

    Anchors on the distinctive 5-char run "NNECT" — robust against
    common OCR misreads of the boundary letters (I↔1, O↔0, D dropped
    on first-char detection misses) while still rejecting unrelated
    text that might leak into the bbox.
    """
    if not text:
        return False
    s = text.upper().replace("0", "O").replace("1", "I").replace("L", "I")
    return "NNECT" in s


def _disconnect_flags_from_results(
    br_by_slug: dict, side: str,
) -> list[bool]:
    """Return 5 booleans — one per slot — True iff the
    `(side).char{N}.disconnect` OCR text matches the DISCONNECTED
    badge (i.e. that Nikke was defeated in the match).
    """
    out: list[bool] = []
    for n in range(1, 6):
        slug = f"{side}.char{n}.disconnect"
        f = br_by_slug.get(slug)
        text = f.text if f else None
        out.append(_is_disconnect_text(text))
    return out


def _outcome_from_disconnects(
    my_dc: list[bool], opp_dc: list[bool],
) -> Optional[str]:
    """Per-side wipe count → ArenaMatch.outcome.

    5/5 user-side wiped → ``"loss"``; 5/5 opp-side wiped → ``"win"``.
    Anything else → None.

    **None means data-quality issue, not a valid outcome bucket.**
    Per the user (2026-05-18), Rookie Arena resolves every match via
    a 5/5 wipe — no ties, no observed timeouts. So if this returns
    None on a real rookie ArenaMatch, it's an OCR miss (one of the
    DISCONNECTED badges failed to read) or missing `results.png` —
    something to flag, not a normal "we'll figure it out later" case.
    """
    if sum(my_dc) == 5 and sum(opp_dc) < 5:
        return "loss"
    if sum(opp_dc) == 5 and sum(my_dc) < 5:
        return "win"
    return None


def build_payload(
    session: Session,
    match: PromoMatch,
    char_name_by_id: dict[int, str],
) -> Optional[_RookieBattlePayload]:
    """Read one rookie battle's screenshots + extracted fields and
    produce an ``_RookieBattlePayload``. Returns ``None`` when the
    loadout screenshot is missing (can't build a meaningful row).
    """
    shots = session.exec(
        select(PromoMatchScreenshot).where(
            PromoMatchScreenshot.match_id == match.id,
        )
    ).all()
    shot_by_kind = {s.kind: s for s in shots}
    loadout_shot = shot_by_kind.get("rookie_loadout")
    opp_shot = shot_by_kind.get("rookie_opponent")
    results_shot = shot_by_kind.get("results_duel")
    if loadout_shot is None:
        log.warning("match %s has no rookie_loadout screenshot", match.id)
        return None

    by_slug = _fields_by_slug(session, loadout_shot.id)

    # Header fields.
    opp_name = (
        by_slug["opponent_name"].text.strip()
        if "opponent_name" in by_slug and by_slug["opponent_name"].text
        else None
    )
    my_name = (
        by_slug["my_name"].text.strip()
        if "my_name" in by_slug and by_slug["my_name"].text
        else None
    )
    opp_cp = (
        _as_int(by_slug["opponent_team_cp"].normalized)
        if "opponent_team_cp" in by_slug else None
    )
    my_cp = (
        _as_int(by_slug["my_team_cp"].normalized)
        if "my_team_cp" in by_slug else None
    )

    # Teams (full per-slot data from the loadout — names, levels,
    # lb_core). Loadout names use tiny popup text and OCR ~95-99%
    # depending on the slot; we keep them as the fallback.
    opp_names_loadout, opp_levels, opp_lb_cores = _read_team(
        by_slug, "opp", char_name_by_id,
    )
    my_names_loadout, my_levels, my_lb_cores = _read_team(
        by_slug, "my", char_name_by_id,
    )

    # Battle-records names — same in-game screen as Champion duels,
    # so the existing results_duel region schema works pixel-for-pixel.
    # Text is ~3× larger here than the loadout's popup. Used as the
    # PRIMARY source for character identity; loadout names are the
    # fallback for any slot the battle-records pass missed.
    opp_names_br: list[Optional[str]] = [None] * 5
    my_names_br: list[Optional[str]] = [None] * 5
    my_disconnect: list[bool] = [False] * 5
    opp_disconnect: list[bool] = [False] * 5
    outcome: Optional[str] = None
    if results_shot is not None:
        br_by_slug = _fields_by_slug(session, results_shot.id)
        # NIKA (me) is on the LEFT, opponent on the RIGHT — matches
        # the loadout layout convention (my team on the bottom row,
        # opponent on top of the popup; battle records mirror this
        # with my team on the left page, opponent on the right).
        my_names_br = _read_battle_records_names(
            br_by_slug, "left", char_name_by_id,
        )
        opp_names_br = _read_battle_records_names(
            br_by_slug, "right", char_name_by_id,
        )
        my_disconnect = _disconnect_flags_from_results(br_by_slug, "left")
        opp_disconnect = _disconnect_flags_from_results(br_by_slug, "right")
        outcome = _outcome_from_disconnects(my_disconnect, opp_disconnect)

    opp_names, opp_name_sources = _merge_names(opp_names_br, opp_names_loadout)
    my_names, my_name_sources = _merge_names(my_names_br, my_names_loadout)

    # Opponent matching + level source.
    opp_match = match_opponent_card(
        session,
        loadout_screenshot_id=loadout_shot.id,
        opponent_screenshot_id=opp_shot.id if opp_shot else None,
    )
    opp_level_src = opponent_level_source(opp_match)

    # Bookkeeping for the my-level fallback chain.
    my_level = resolve_my_level(
        session,
        battle_match_id=match.id,
        this_opponent_screenshot_id=opp_shot.id if opp_shot else None,
    )

    capture_quality = {
        # Per-Nikke detail that doesn't have first-class columns.
        "user_team_levels": my_levels,
        "user_team_lb_cores": my_lb_cores,
        "opponent_team_levels": opp_levels,
        "opponent_team_lb_cores": opp_lb_cores,
        # Per-slot name source ("primary" = battle_records,
        # "fallback" = loadout, "missing" = neither). Useful for
        # debugging which side of the OCR pipeline carried each name.
        "user_team_name_sources": my_name_sources,
        "opponent_team_name_sources": opp_name_sources,
        # Opponent-match decision + level provenance.
        "opponent_level": opp_match.level if opp_match else None,
        "opponent_level_source": opp_level_src.value,
        "opponent_match_score": (
            opp_match.score if opp_match is not None else None
        ),
        "opponent_match_card_index": (
            opp_match.card_index if opp_match is not None else None
        ),
        # My-level resolution (for the "my level was estimated" badge).
        "my_player_level": my_level.level,
        "my_player_level_source": my_level.source.value,
        "my_player_level_source_label": my_level.source_battle_label,
        # Per-slot disconnect flags from the results screen. Outcome is
        # already on `payload.outcome` but the per-slot map is useful
        # for debugging (e.g. partial disconnects when only some Nikkes
        # forfeited but the match continued).
        "user_team_disconnect": my_disconnect,
        "opponent_team_disconnect": opp_disconnect,
    }

    return _RookieBattlePayload(
        user_username=my_name,
        opponent_username=opp_name,
        # ArenaMatch.user_team / opponent_team are JSON list[str]. Keep
        # the None-padded shape so consumers know which slot was missed.
        user_team=[n or "" for n in my_names],
        opponent_team=[n or "" for n in opp_names],
        user_power=my_cp,
        opponent_power=opp_cp,
        pre_battle_screenshot=loadout_shot.file_path,
        battle_record_screenshot=(
            results_shot.file_path if results_shot else None
        ),
        capture_quality=capture_quality,
        outcome=outcome,
        loadout_screenshot_id=loadout_shot.id,
        canonical_my_team=my_names,
        canonical_opp_team=opp_names,
    )


# ---------------------------------------------------------------------------
# Upsert into ArenaMatch
# ---------------------------------------------------------------------------


def _backfill_loadout_char_ids(
    session: Session,
    *,
    loadout_screenshot_id: int,
    canonical_my_team: list[Optional[str]],
    canonical_opp_team: list[Optional[str]],
    char_id_by_name: dict[str, int],
) -> int:
    """Backfill the loadout's per-slot ``(opp|my).charN.name`` rows
    with the canonical character_id derived from battle_records.

    The loadout's text + confidence stay as-is so the audit viewer
    still shows what was OCR'd, but the ``character_id`` (and
    therefore the displayed matched-character name) reflects the
    authoritative battle_records identity. Returns the count of rows
    updated.
    """
    updates = 0
    for side_prefix, canonical in (("my", canonical_my_team), ("opp", canonical_opp_team)):
        for slot, canonical_name in enumerate(canonical, start=1):
            if not canonical_name:
                continue
            target_cid = char_id_by_name.get(canonical_name)
            if target_cid is None:
                continue
            row = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.screenshot_id == loadout_screenshot_id,
                    PromoExtractedField.region_slug == f"{side_prefix}.char{slot}.name",
                )
            ).first()
            if row is None:
                continue
            if row.character_id == target_cid:
                continue
            row.character_id = target_cid
            session.add(row)
            updates += 1
    if updates:
        session.commit()
    return updates


def upsert_arena_match(
    session: Session,
    *,
    tournament: PromoTournament,
    match: PromoMatch,
    char_name_by_id: dict[int, str],
) -> Optional[ArenaMatch]:
    """Build + upsert one ArenaMatch row from a rookie PromoMatch.

    Returns the row (existing-or-new) or None when the loadout
    screenshot was missing (skipped). Idempotent via the
    (session_id, round_index) natural key — re-running on the same
    PromoMatch updates the existing row in place.
    """
    payload = build_payload(session, match, char_name_by_id)
    if payload is None:
        return None

    sid = session_id_for_run(tournament.id)
    existing = session.exec(
        select(ArenaMatch).where(
            ArenaMatch.session_id == sid,
            ArenaMatch.round_index == match.match_no,
            ArenaMatch.mode == "rookie",
        )
    ).first()

    fields = {
        "mode": "rookie",
        "user_username": payload.user_username,
        "opponent_username": payload.opponent_username,
        "user_team": payload.user_team,
        "opponent_team": payload.opponent_team,
        "user_power": payload.user_power,
        "opponent_power": payload.opponent_power,
        "pre_battle_screenshot": payload.pre_battle_screenshot,
        "battle_record_screenshot": payload.battle_record_screenshot,
        "capture_quality": payload.capture_quality,
        "outcome": payload.outcome,
        "session_id": sid,
        "session_label": (
            f"Rookie Arena {tournament.captured_at:%Y-%m-%d %H:%M} UTC"
        ),
        "session_kind": "rookie_run",
        "round_index": match.match_no,
        "captured_at": tournament.captured_at,
        # Rookie is 1v1 — known role layout, no ambiguity.
        "is_user_lineup": None,
    }

    if existing is None:
        row = ArenaMatch(**fields)
        session.add(row)
        session.commit()
        session.refresh(row)
    else:
        for k, v in fields.items():
            setattr(existing, k, v)
        session.add(existing)
        session.commit()
        row = existing

    # Backfill the loadout's char.name character_ids with the
    # canonical names (from battle_records) so per-screenshot audit
    # views show the authoritative character. Original OCR text +
    # confidence stay untouched.
    if payload.loadout_screenshot_id is not None:
        char_id_by_name = {n: i for i, n in char_name_by_id.items()}
        _backfill_loadout_char_ids(
            session,
            loadout_screenshot_id=payload.loadout_screenshot_id,
            canonical_my_team=payload.canonical_my_team,
            canonical_opp_team=payload.canonical_opp_team,
            char_id_by_name=char_id_by_name,
        )

    return row


def build_arena_matches_for_run(
    session: Session, tournament: PromoTournament,
) -> int:
    """Build/refresh ArenaMatch rows for every battle in a rookie run.
    Returns count of rows touched (new + updated)."""
    matches = session.exec(
        select(PromoMatch).where(
            PromoMatch.tournament_id == tournament.id,
            PromoMatch.round_label == "rookie",
        ).order_by(PromoMatch.match_no)
    ).all()
    if not matches:
        return 0
    char_name_by_id = {
        c.id: c.name for c in session.exec(select(Character)).all()
    }
    n = 0
    for m in matches:
        row = upsert_arena_match(
            session,
            tournament=tournament,
            match=m,
            char_name_by_id=char_name_by_id,
        )
        if row is not None:
            n += 1
    return n
