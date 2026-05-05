"""Session grouping + completeness tests for slice #135.

Covers:
  * compute_session_kind classification (predictions / partial / complete)
  * session_completeness builds the 5×3 round matrix correctly
  * session_completeness_warnings groups by session_id
  * Adding result rows to a predictions session promotes it to complete
"""
from __future__ import annotations

import importlib.util
import uuid

import pytest

# Skip the entire module when sqlmodel isn't available (simulator-only env).
if importlib.util.find_spec("sqlmodel") is None:  # pragma: no cover
    pytest.skip("sqlmodel not available", allow_module_level=True)


from nikke_copilot.data.models import ArenaMatch  # noqa: E402
from nikke_copilot.roster.arena_importer import (  # noqa: E402
    SESSION_KIND_COMPLETE,
    SESSION_KIND_PARTIAL,
    SESSION_KIND_PREDICTIONS,
    compute_session_kind,
)
from nikke_copilot.web.capture_warnings import (  # noqa: E402
    session_completeness,
    session_completeness_warnings,
)


def _loadout_row(round_index: int, *, user: str = "NIKA", session_id: str) -> ArenaMatch:
    return ArenaMatch(
        mode="champion",
        round_index=round_index,
        user_username=user,
        user_team=["A", "B", "C", "D", "E"],
        session_id=session_id,
    )


def _result_row(round_index: int, *, session_id: str) -> ArenaMatch:
    return ArenaMatch(
        mode="champion_battle_record",
        round_index=round_index,
        user_team=["A", "B", "C", "D", "E"],
        opponent_team=["X", "Y", "Z", "W", "V"],
        session_id=session_id,
    )


def _duel_row(*, session_id: str) -> ArenaMatch:
    return ArenaMatch(
        mode="champion_duel_result",
        session_id=session_id,
    )


class TestComputeSessionKind:
    def test_loadouts_only_is_predictions(self):
        sid = uuid.uuid4().hex
        rows = [_loadout_row(i, session_id=sid) for i in range(1, 6)]
        rows += [
            _loadout_row(i, user="OPPONENT", session_id=sid) for i in range(1, 6)
        ]
        assert compute_session_kind(rows) == SESSION_KIND_PREDICTIONS

    def test_loadouts_plus_some_results_is_partial(self):
        sid = uuid.uuid4().hex
        rows = [_loadout_row(i, session_id=sid) for i in range(1, 6)]
        rows += [_result_row(i, session_id=sid) for i in range(1, 4)]  # only 3
        assert compute_session_kind(rows) == SESSION_KIND_PARTIAL

    def test_full_session_is_complete(self):
        sid = uuid.uuid4().hex
        rows = [_loadout_row(i, session_id=sid) for i in range(1, 6)]
        rows += [
            _loadout_row(i, user="OPPONENT", session_id=sid) for i in range(1, 6)
        ]
        rows += [_result_row(i, session_id=sid) for i in range(1, 6)]
        rows += [_duel_row(session_id=sid)]
        assert compute_session_kind(rows) == SESSION_KIND_COMPLETE

    def test_non_champions_returns_none(self):
        rows = [
            ArenaMatch(mode="rookie", session_id="abc"),
            ArenaMatch(mode="special", session_id="abc"),
        ]
        assert compute_session_kind(rows) is None

    def test_empty_returns_none(self):
        assert compute_session_kind([]) is None


class TestSessionCompleteness:
    def test_matrix_has_5_rounds(self):
        sid = uuid.uuid4().hex
        rows = [_loadout_row(1, session_id=sid)]
        sc = session_completeness(rows, user_username="NIKA")
        assert sc is not None
        assert len(sc.rounds) == 5
        assert all(sc.rounds[i].round_index == i + 1 for i in range(5))

    def test_loadout_buckets_user_into_p1(self):
        sid = uuid.uuid4().hex
        rows = [
            _loadout_row(3, user="NIKA", session_id=sid),
            _loadout_row(3, user="OPPONENT", session_id=sid),
        ]
        sc = session_completeness(rows, user_username="NIKA")
        round_3 = sc.rounds[2]
        assert round_3.p1_loadout.captured is True
        assert round_3.p2_loadout.captured is True

    def test_cheered_duel_buckets_two_observed_players(self):
        """When the user uploads a Duel between two OTHER players (cheering),
        both players become P1 and P2 — neither is the user."""
        sid = uuid.uuid4().hex
        rows = [
            _loadout_row(3, user="ALICE", session_id=sid),
            _loadout_row(3, user="BOB", session_id=sid),
        ]
        sc = session_completeness(rows, user_username="NIKA")
        round_3 = sc.rounds[2]
        assert round_3.p1_loadout.captured is True
        assert round_3.p2_loadout.captured is True

    def test_orphaned_result_is_warned(self):
        sid = uuid.uuid4().hex
        # Round 2 has a result but no loadouts → warning.
        rows = [_loadout_row(1, session_id=sid), _result_row(2, session_id=sid)]
        sc = session_completeness(rows, user_username="NIKA")
        assert any("Round 2" in w for w in sc.warnings)

    def test_grouping_handles_multiple_sessions(self):
        sid1 = uuid.uuid4().hex
        sid2 = uuid.uuid4().hex
        rows = [
            _loadout_row(1, session_id=sid1),
            _loadout_row(2, session_id=sid1),
            _loadout_row(1, session_id=sid2),
        ]
        out = session_completeness_warnings(rows, user_username="NIKA")
        assert sid1 in out
        assert sid2 in out
        assert sum(1 for r in out[sid1].rounds if r.p1_loadout.captured) == 2
        assert sum(1 for r in out[sid2].rounds if r.p1_loadout.captured) == 1


class TestPromotionToComplete:
    """Adding result rows to a predictions session must update its kind."""

    def test_predictions_promotes_to_complete_when_results_added(self):
        sid = uuid.uuid4().hex
        # Initial: predictions-only.
        rows = [_loadout_row(i, session_id=sid) for i in range(1, 6)]
        rows += [
            _loadout_row(i, user="OPPONENT", session_id=sid) for i in range(1, 6)
        ]
        assert compute_session_kind(rows) == SESSION_KIND_PREDICTIONS
        # Add the missing results + duel.
        rows += [_result_row(i, session_id=sid) for i in range(1, 6)]
        rows += [_duel_row(session_id=sid)]
        assert compute_session_kind(rows) == SESSION_KIND_COMPLETE


class TestKindRecomputesOnDelete:
    """compute_session_kind must downgrade when rows are removed."""

    def test_complete_downgrades_to_partial_after_result_delete(self):
        sid = uuid.uuid4().hex
        rows = [_loadout_row(i, session_id=sid) for i in range(1, 6)]
        rows += [
            _loadout_row(i, user="OPPONENT", session_id=sid) for i in range(1, 6)
        ]
        rows += [_result_row(i, session_id=sid) for i in range(1, 6)]
        rows += [_duel_row(session_id=sid)]
        assert compute_session_kind(rows) == SESSION_KIND_COMPLETE
        # Remove ONE result row → must drop to partial.
        rows = [r for r in rows if not (
            r.mode == "champion_battle_record" and r.round_index == 3
        )]
        assert compute_session_kind(rows) == SESSION_KIND_PARTIAL

    def test_complete_downgrades_to_predictions_after_all_results_deleted(self):
        sid = uuid.uuid4().hex
        rows = [_loadout_row(i, session_id=sid) for i in range(1, 6)]
        rows += [
            _loadout_row(i, user="OPPONENT", session_id=sid) for i in range(1, 6)
        ]
        rows += [_result_row(i, session_id=sid) for i in range(1, 6)]
        rows += [_duel_row(session_id=sid)]
        assert compute_session_kind(rows) == SESSION_KIND_COMPLETE
        # Remove all results AND the duel.
        rows = [r for r in rows if r.mode == "champion"]
        assert compute_session_kind(rows) == SESSION_KIND_PREDICTIONS
