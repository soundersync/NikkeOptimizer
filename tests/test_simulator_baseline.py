"""Smoke tests for the baseline accuracy harness.

These exercise the data-model surface (dataclasses, predicted/correct
computation, mode bucketing) without needing a real DB. The CLI smoke
test (``baseline-sim``) wires the live DB and isn't part of this file —
it's the end-to-end harness driven by hand.
"""

from __future__ import annotations

from nikke_optimizer.simulator.baseline import (
    BaselineReport,
    MatchPrediction,
)


def _pred(*, match_id=1, mode="rookie", actual="win", predicted="user"):
    return MatchPrediction(
        match_id=match_id,
        mode=mode,
        user_username="NIKA",
        opponent_username="OPP",
        round_index=1,
        actual_outcome=actual,
        predicted_winner=predicted,
        user_clear_sec=30.0,
        opp_clear_sec=50.0,
        user_team_dps=1_000_000.0,
        opp_team_dps=500_000.0,
        user_def_ehp=10_000_000.0,
        opp_def_ehp=8_000_000.0,
    )


class TestMatchPredictionCorrect:
    def test_user_predicted_user_win(self):
        assert _pred(actual="win", predicted="user").correct is True

    def test_user_predicted_opp_win(self):
        assert _pred(actual="win", predicted="opp").correct is False

    def test_opp_predicted_opp_loss(self):
        assert _pred(actual="loss", predicted="opp").correct is True

    def test_opp_predicted_user_loss(self):
        assert _pred(actual="loss", predicted="user").correct is False

    def test_missing_outcome_yields_none(self):
        assert _pred(actual=None, predicted="user").correct is None

    def test_tie_prediction_yields_none(self):
        assert _pred(actual="win", predicted=None).correct is None


class TestBaselineReport:
    def test_overall_accuracy(self):
        r = BaselineReport(predictions=[
            _pred(match_id=1, actual="win", predicted="user"),
            _pred(match_id=2, actual="loss", predicted="opp"),
            _pred(match_id=3, actual="win", predicted="opp"),
        ])
        assert r.n_total == 3
        assert r.n_correct == 2
        assert abs(r.accuracy - 2 / 3) < 1e-9

    def test_skips_unscoreable(self):
        r = BaselineReport(predictions=[
            _pred(match_id=1, actual="win", predicted="user"),
            _pred(match_id=2, actual=None, predicted="user"),  # no outcome
            _pred(match_id=3, actual="loss", predicted=None),  # tie
        ])
        assert r.n_total == 1
        assert r.n_correct == 1
        assert r.accuracy == 1.0

    def test_by_mode_bucketing(self):
        r = BaselineReport(predictions=[
            _pred(match_id=1, mode="rookie", actual="win", predicted="user"),
            _pred(match_id=2, mode="rookie", actual="loss", predicted="opp"),
            _pred(match_id=3, mode="rookie", actual="win", predicted="opp"),
            _pred(match_id=4, mode="champion", actual="win", predicted="user"),
            _pred(match_id=5, mode="champion", actual="loss", predicted="user"),
        ])
        by_mode = r.by_mode()
        assert by_mode["rookie"] == (2, 3)
        assert by_mode["champion"] == (1, 2)

    def test_empty(self):
        r = BaselineReport(predictions=[])
        assert r.n_total == 0
        assert r.accuracy == 0.0
        assert r.by_mode() == {}
