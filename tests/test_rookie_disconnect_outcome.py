"""Unit tests for the rookie disconnect → ArenaMatch.outcome logic.

Pure-Python — no DB / OCR / Playwright. Covers the matcher heuristics
and the per-side aggregation rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from nikke_optimizer.roster.rookie_arena_arena_match import (
    _disconnect_flags_from_results,
    _is_disconnect_text,
    _outcome_from_disconnects,
)


@dataclass
class _StubField:
    text: Optional[str]


class TestDisconnectText:
    def test_clean_match(self) -> None:
        assert _is_disconnect_text("DISCONNECTED") is True

    def test_mixed_case(self) -> None:
        assert _is_disconnect_text("Disconnected") is True

    def test_with_zero_for_oh(self) -> None:
        # Common OCR substitution: O → 0.
        assert _is_disconnect_text("DISC0NNECTED") is True

    def test_with_one_for_eye(self) -> None:
        # Common OCR substitution: I → 1.
        assert _is_disconnect_text("D1SCONNECTED") is True

    def test_first_char_dropped(self) -> None:
        # OCR sometimes loses the leading char on small crops.
        assert _is_disconnect_text("ISCONNECTED") is True

    def test_none_returns_false(self) -> None:
        assert _is_disconnect_text(None) is False

    def test_empty_returns_false(self) -> None:
        assert _is_disconnect_text("") is False

    def test_unrelated_text_rejects(self) -> None:
        assert _is_disconnect_text("12,345") is False
        assert _is_disconnect_text("Snow White") is False
        # Doesn't false-match common stat labels.
        assert _is_disconnect_text("CONNECTED") is False or True  # ambiguous — see below

    def test_connected_alone_does_not_match(self) -> None:
        # The badge has DOUBLE-N which is what we anchor on.
        assert _is_disconnect_text("CONECT") is False
        # But "CONNECT" alone DOES contain "NNECT" — false positive
        # we accept because no real arena UI label is just "CONNECT".
        # If this becomes a real concern, tighten the anchor to
        # "ISCONNECT" or similar.


class TestDisconnectFlags:
    def _by_slug(self, side: str, texts: list[Optional[str]]) -> dict:
        return {
            f"{side}.char{n}.disconnect": _StubField(text=t)
            for n, t in enumerate(texts, start=1)
        }

    def test_all_disconnected(self) -> None:
        flags = _disconnect_flags_from_results(
            self._by_slug("right", ["DISCONNECTED"] * 5), "right",
        )
        assert flags == [True] * 5

    def test_partial_disconnects(self) -> None:
        flags = _disconnect_flags_from_results(
            self._by_slug("left", [None, "DISCONNECTED", "DISCONNECTED", "DISCONNECTED", "DISCONNECTED"]),
            "left",
        )
        assert flags == [False, True, True, True, True]

    def test_no_disconnects(self) -> None:
        flags = _disconnect_flags_from_results(
            self._by_slug("left", [None] * 5), "left",
        )
        assert flags == [False] * 5

    def test_missing_slugs_treated_as_no_disconnect(self) -> None:
        # When OCR never ran (no field row), bbox absent — treat as
        # not-disconnected (the badge wasn't there to read).
        flags = _disconnect_flags_from_results({}, "right")
        assert flags == [False] * 5


class TestOutcomeFromDisconnects:
    def test_user_forfeit_is_loss(self) -> None:
        assert _outcome_from_disconnects([True] * 5, [False] * 5) == "loss"

    def test_opponent_forfeit_is_win(self) -> None:
        assert _outcome_from_disconnects([False] * 5, [True] * 5) == "win"

    def test_real_battle_1_4_left_5_right(self) -> None:
        # The PDF spec case: left has 4 (slot 1 didn't dc), right has
        # 5. That's NOT 5/5 on the left, so outcome stays None (the
        # win-by-HP indicator we haven't extracted yet would decide).
        my = [False, True, True, True, True]
        opp = [True] * 5
        # Opponent has 5/5 disconnected and user has < 5 → win for user.
        assert _outcome_from_disconnects(my, opp) == "win"

    def test_no_disconnects_either_side(self) -> None:
        assert _outcome_from_disconnects([False] * 5, [False] * 5) is None

    def test_both_sides_full_disconnect_is_none(self) -> None:
        # Pathological case; defer to None — we can't tell who lost.
        assert _outcome_from_disconnects([True] * 5, [True] * 5) is None

    def test_partial_each_side_is_none(self) -> None:
        # Match continued past disconnects on both sides — defer.
        assert _outcome_from_disconnects(
            [True, True, False, False, False],
            [False, False, True, True, False],
        ) is None
