"""Rookie Arena — opponent matching + my-level resolution.

Pulls together the two pieces of cross-screenshot logic for a rookie
battle:

* ``match_opponent_card`` — given the opponent player_name from
  ``loadout.png`` and the 3 candidate names from ``opponent.png``,
  fuzzy-match to pick the right card and return ``(index, level, score)``.
  Returns ``None`` when no opponent.png is present OR when the best
  fuzzy score falls below the confident threshold — caller falls back
  to the estimated-level path.

* ``resolve_my_level`` — implements the fallback chain documented
  in the planning doc:
    1. This battle's own ``opponent.png`` my_player_level
    2. Same-run other battles' opponent.png my_player_level
    3. Most-recent prior run's opponent.png my_player_level
    4. ``AccountState.synchro_level`` (last resort, flagged as
       potentially stale)

  Returns the level + a ``LevelSource`` enum so the UI can chip the
  precision honestly.

Both helpers are pure functions over ``PromoExtractedField`` rows —
they don't perform OCR, just consume what the existing OCR pass wrote.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session, select

from ..data.models import (
    AccountState,
    PromoExtractedField,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
)

log = logging.getLogger(__name__)


# Confident fuzzy-match threshold for opponent_name vs the 3 candidate
# names on opponent.png. The three candidates are deliberately
# different players, so any reasonable OCR + small typo correction
# should land well above this floor. Below it we treat the match as
# ambiguous and fall back to estimated-level semantics.
OPPONENT_MATCH_CONFIDENT_SCORE = 80.0


class LevelSource(str, enum.Enum):
    """How a player-level value was determined for a rookie battle.

    Stored in ``ArenaMatch.capture_quality["opponent_level_source"]``
    and surfaced in the UI as a precision chip. ``UNKNOWN`` is the
    sentinel for "we couldn't determine the level at all" — should be
    rare in practice but kept distinct from the estimated cases so
    bugs are visible.
    """

    OPPONENT_PNG = "opponent_png"                 # exact, ±5 tolerance
    OPPONENT_PNG_FALLBACK = "opponent_png_fallback"  # weak match, ±20
    ESTIMATED_FROM_MY_LEVEL = "estimated_from_my_level"  # ±20
    ACCOUNT_STATE = "account_state"               # last resort
    UNKNOWN = "unknown"


@dataclass
class OpponentMatch:
    """Result of fuzzy-matching the loadout's opponent_name against
    the 3 candidates on opponent.png."""

    card_index: int               # 0..2 — which of the 3 cards matched
    name_on_card: str             # canonical name as it appeared on the card
    level: Optional[int]          # the level OCR'd from that card
    score: float                  # fuzzy-match score 0..100
    confident: bool               # score >= OPPONENT_MATCH_CONFIDENT_SCORE


@dataclass
class MyLevelResolution:
    level: Optional[int]
    source: LevelSource
    source_screenshot_id: Optional[int] = None   # which opponent.png we read from
    source_battle_label: Optional[str] = None    # "battle_1 (this run)" etc.


# ---------------------------------------------------------------------------
# Opponent matching
# ---------------------------------------------------------------------------


def _read_loadout_opponent_name(
    session: Session, loadout_screenshot_id: int,
) -> Optional[str]:
    row = session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.screenshot_id == loadout_screenshot_id,
            PromoExtractedField.region_slug == "opponent_name",
        )
    ).first()
    return (row.text or None) if row is not None else None


def _read_opponent_candidates(
    session: Session, opponent_screenshot_id: int,
) -> list[tuple[int, Optional[str], Optional[int]]]:
    """Return ``[(card_index, name_text, level_int), ...]`` for the
    3 candidate slots on an opponent.png.

    ``card_index`` is 0-based to match Python conventions; the UI
    + region slugs (``opp1``, ``opp2``, ``opp3``) are 1-based and
    handled at their respective edges.
    """
    fields = session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.screenshot_id == opponent_screenshot_id,
        )
    ).all()
    by_slug = {f.region_slug: f for f in fields}
    out: list[tuple[int, Optional[str], Optional[int]]] = []
    for i in range(3):
        n = i + 1
        name_row = by_slug.get(f"opp{n}.name")
        level_row = by_slug.get(f"opp{n}.level")
        name = (name_row.text or None) if name_row is not None else None
        level: Optional[int] = None
        if level_row is not None and level_row.normalized:
            try:
                level = int(level_row.normalized)
            except ValueError:
                level = None
        out.append((i, name, level))
    return out


def _score(query: str, candidate: str) -> float:
    """Same fuzzy-match heuristic the character matcher uses —
    mean of ``fuzz.ratio`` and ``fuzz.partial_ratio``. Handles short
    name OCR variations (extra trailing chars, missing letter)."""
    from rapidfuzz import fuzz
    return (fuzz.ratio(query, candidate) + fuzz.partial_ratio(query, candidate)) / 2.0


def match_opponent_card(
    session: Session,
    *,
    loadout_screenshot_id: int,
    opponent_screenshot_id: Optional[int],
) -> Optional[OpponentMatch]:
    """Pick which of the 3 candidates on opponent.png is the player
    we actually fought.

    Returns ``None`` when:
      * ``opponent_screenshot_id`` is None (no opponent.png for this
        battle — older runs, today's match 4)
      * The loadout doesn't have an opponent_name extracted yet
      * None of the 3 candidates have OCR'd names

    Always returns a result (potentially with confident=False) when
    BOTH images have OCR data — callers can use the score + confident
    flag to decide whether to trust the level or fall back to
    estimation.
    """
    if opponent_screenshot_id is None:
        return None
    target = _read_loadout_opponent_name(session, loadout_screenshot_id)
    if not target:
        return None
    target = target.strip()
    if not target:
        return None
    candidates = _read_opponent_candidates(session, opponent_screenshot_id)

    best_idx: Optional[int] = None
    best_score = -1.0
    best_name = ""
    best_level: Optional[int] = None
    for idx, name, level in candidates:
        if not name:
            continue
        s = _score(target.upper(), name.upper())
        if s > best_score:
            best_score = s
            best_idx = idx
            best_name = name
            best_level = level

    if best_idx is None:
        return None
    return OpponentMatch(
        card_index=best_idx,
        name_on_card=best_name,
        level=best_level,
        score=best_score,
        confident=best_score >= OPPONENT_MATCH_CONFIDENT_SCORE,
    )


# ---------------------------------------------------------------------------
# My-level fallback chain
# ---------------------------------------------------------------------------


def _read_my_player_level(
    session: Session, opponent_screenshot_id: int,
) -> Optional[int]:
    row = session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.screenshot_id == opponent_screenshot_id,
            PromoExtractedField.region_slug == "my_player_level",
        )
    ).first()
    if row is None or not row.normalized:
        return None
    try:
        return int(row.normalized)
    except ValueError:
        return None


def resolve_my_level(
    session: Session,
    *,
    battle_match_id: int,
    this_opponent_screenshot_id: Optional[int],
) -> MyLevelResolution:
    """Walk the my-level fallback chain.

    Order:
      1. ``this_opponent_screenshot_id``'s ``my_player_level``.
      2. Other battles' opponent.png in the SAME run.
      3. Most-recent prior run's opponent.png.
      4. ``AccountState.synchro_level`` (last resort).
    """
    # Step 1: this battle's own opponent.png.
    if this_opponent_screenshot_id is not None:
        lv = _read_my_player_level(session, this_opponent_screenshot_id)
        if lv is not None:
            return MyLevelResolution(
                level=lv,
                source=LevelSource.OPPONENT_PNG,
                source_screenshot_id=this_opponent_screenshot_id,
                source_battle_label="this battle",
            )

    # Step 2: same-run other battles. Find the run's PromoTournament
    # via this match, then look for sibling opponent screenshots.
    this_match = session.get(PromoMatch, battle_match_id)
    if this_match is None:
        return MyLevelResolution(level=None, source=LevelSource.UNKNOWN)
    tournament_id = this_match.tournament_id

    siblings = session.exec(
        select(PromoMatchScreenshot, PromoMatch).where(
            PromoMatchScreenshot.kind == "rookie_opponent",
            PromoMatch.tournament_id == tournament_id,
            PromoMatch.id == PromoMatchScreenshot.match_id,
            PromoMatchScreenshot.match_id != battle_match_id,
        )
    ).all()
    for shot, match in siblings:
        lv = _read_my_player_level(session, shot.id)
        if lv is not None:
            return MyLevelResolution(
                level=lv,
                source=LevelSource.OPPONENT_PNG,
                source_screenshot_id=shot.id,
                source_battle_label=f"battle_{match.match_no} (same run)",
            )

    # Step 3: prior runs' opponent.png. Order by tournament captured_at
    # descending so we pick the most-recent.
    prior_shots = session.exec(
        select(PromoMatchScreenshot, PromoMatch, PromoTournament).where(
            PromoMatchScreenshot.kind == "rookie_opponent",
            PromoMatch.id == PromoMatchScreenshot.match_id,
            PromoTournament.id == PromoMatch.tournament_id,
            PromoTournament.id != tournament_id,
        ).order_by(PromoTournament.captured_at.desc())
    ).all()
    for shot, match, prior_t in prior_shots:
        lv = _read_my_player_level(session, shot.id)
        if lv is not None:
            return MyLevelResolution(
                level=lv,
                source=LevelSource.OPPONENT_PNG,
                source_screenshot_id=shot.id,
                source_battle_label=(
                    f"battle_{match.match_no} from {prior_t.captured_at:%Y-%m-%d}"
                ),
            )

    # Step 4: AccountState. Singleton row (id=1 by convention).
    state = session.exec(select(AccountState)).first()
    if state is not None and state.synchro_level:
        return MyLevelResolution(
            level=int(state.synchro_level),
            source=LevelSource.ACCOUNT_STATE,
            source_battle_label="AccountState.synchro_level (may be stale)",
        )

    return MyLevelResolution(level=None, source=LevelSource.UNKNOWN)


def opponent_level_source(
    opp_match: Optional[OpponentMatch],
) -> LevelSource:
    """Map an opponent-match result to its provenance enum."""
    if opp_match is None:
        return LevelSource.ESTIMATED_FROM_MY_LEVEL
    if opp_match.level is None:
        return LevelSource.ESTIMATED_FROM_MY_LEVEL
    if opp_match.confident:
        return LevelSource.OPPONENT_PNG
    return LevelSource.OPPONENT_PNG_FALLBACK
