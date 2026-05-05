"""Multi-capture consensus — promote borderline portrait matches when
the same opponent appears in multiple captures.

Slice #60 added per-cell CP cross-validation that auto-confirms
borderline matches on the user's own team (CP comparison against the
owned roster). This module is the opponent-side complement: when an
opponent_username appears across 3+ captures, group their
``ArenaMatch`` rows. For each (slot, character) tuple where 2+
captures confidently identified the same character, treat that as
ground truth — promote borderline cells in OTHER captures of the same
opponent to the consensus character.

Run after import via ``apply_consensus(session)`` or call ad-hoc from
a CLI command. Idempotent: re-running produces the same result.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from sqlmodel import Session, select

from ..data.models import ArenaMatch


def _confident_cell(quality: dict, slot: int) -> str | None:
    """Return the confident match name at ``slot`` or None when borderline."""
    chars = (quality.get("characters") or []) if quality else []
    if 0 <= slot < len(chars):
        c = chars[slot]
        if c:
            return c
    return None


def _best_match_cell(quality: dict, slot: int) -> str | None:
    chars = (quality.get("best_matches") or []) if quality else []
    if 0 <= slot < len(chars):
        c = chars[slot]
        if c:
            return c
    return None


def apply_consensus(
    session: Session,
    *,
    min_confident_count: int = 2,
    only_opponent_side: bool = True,
) -> dict:
    """Apply multi-capture consensus to all stored arena matches.

    Returns a report dict with counts of promotions per opponent. The
    function mutates ``ArenaMatch.opponent_team`` and
    ``ArenaMatch.capture_quality`` in place; call ``session.commit()``
    afterwards (or wrap your own transaction).

    ``min_confident_count`` (default 2) is the number of captures that
    must agree on a (slot, character) before the consensus promotes
    the same slot in other captures.

    ``only_opponent_side`` (default True) skips the user-side team —
    that's already covered by CP cross-validation in slice #60.
    """
    rows = list(session.exec(select(ArenaMatch)).all())

    # Group rows by opponent_username (skipping rows without one).
    groups: dict[str, list[ArenaMatch]] = defaultdict(list)
    for r in rows:
        opp = (r.opponent_username or "").strip()
        if not opp:
            continue
        groups[opp].append(r)

    report: dict[str, dict] = {}

    for opp_name, opp_rows in groups.items():
        if len(opp_rows) < 2:
            continue  # need at least 2 captures to compute consensus

        # For each slot 0-4, count confident matches across captures.
        # consensus[slot] = name when ≥ min_confident_count captures agree.
        consensus: dict[int, str] = {}
        for slot in range(5):
            counter: Counter[str] = Counter()
            for r in opp_rows:
                q = (r.capture_quality or {}).get("opponent", {})
                conf = _confident_cell(q, slot)
                if conf:
                    counter[conf] += 1
            if not counter:
                continue
            top_name, top_count = counter.most_common(1)[0]
            if top_count >= min_confident_count:
                consensus[slot] = top_name

        if not consensus:
            continue

        # Apply consensus: for any borderline cell (no confident match),
        # if the rank-1 best_match agrees with the consensus, promote it.
        promoted_per_row: dict[int, list[str]] = {}
        for r in opp_rows:
            q = dict(r.capture_quality or {})
            opp_q = dict(q.get("opponent", {}) or {})
            chars = list(opp_q.get("characters") or [None] * 5)
            best = list(opp_q.get("best_matches") or [None] * 5)
            while len(chars) < 5:
                chars.append(None)
            while len(best) < 5:
                best.append(None)

            promoted_here: list[str] = []
            for slot, consensus_name in consensus.items():
                if chars[slot] is not None:
                    continue  # already confident
                # Promote if rank-1 best_match agrees with consensus.
                if best[slot] == consensus_name:
                    chars[slot] = consensus_name
                    promoted_here.append(f"slot {slot+1}: {consensus_name}")

            if promoted_here:
                opp_q["characters"] = chars
                q["opponent"] = opp_q
                r.capture_quality = q
                # Also reflect in opponent_team list (parallel to chars)
                team = list(r.opponent_team or [])
                while len(team) < 5:
                    team.append("")
                for slot in range(5):
                    if chars[slot] and not team[slot]:
                        team[slot] = chars[slot]
                r.opponent_team = team
                # Recompute needs_review across both teams.
                still = False
                for side_q in (r.capture_quality or {}).values():
                    if any(c is None for c in (side_q.get("characters") or [])):
                        still = True
                        break
                r.needs_review = still
                session.add(r)
                if r.id is not None:
                    promoted_per_row[r.id] = promoted_here

        if promoted_per_row:
            report[opp_name] = {
                "captures_in_group": len(opp_rows),
                "consensus": consensus,
                "promoted_per_row": promoted_per_row,
            }

    return report
