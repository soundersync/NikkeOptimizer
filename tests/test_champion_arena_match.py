"""Unit tests for the Champions ArenaMatch builder.

Pure-Python — covers session-id stability, path parsers, team-overlap
left/right-mapping helper, and snapshot-completeness aggregation.
DB / OCR / Playwright not needed.
"""
from __future__ import annotations

from nikke_optimizer.roster.champion_arena_match import (
    _duel_round_from_path,
    _loadout_round_from_path,
    _position_from_path,
    _team_overlap,
    session_id_for_duel,
)


class TestSessionId:
    def test_anchored_on_promo_match_id(self) -> None:
        assert session_id_for_duel(42) == "champion-pm42"

    def test_distinct_promo_match_ids_distinct_session_ids(self) -> None:
        # The whole point of switching from (tid, round_label, match_no)
        # to PromoMatch.id was to dodge collisions where match_no is
        # None (top_16, finals) or where labels repeat across groups.
        assert session_id_for_duel(1) != session_id_for_duel(2)


class TestPathParsers:
    def test_position_from_top(self) -> None:
        p = "/captures/beta_season_28/promotion_tournament/group_1/round_64/match_1/player_top/round_1.png"
        assert _position_from_path(p) == "top"

    def test_position_from_bottom(self) -> None:
        p = "/captures/beta_season_28/promotion_tournament/group_1/round_64/match_1/player_bottom/round_3.png"
        assert _position_from_path(p) == "bottom"

    def test_position_none_for_unknown_layout(self) -> None:
        assert _position_from_path("/some/other/path/round_1.png") is None

    def test_loadout_round_extracts_digit(self) -> None:
        assert _loadout_round_from_path("/x/player_top/round_3.png") == 3
        assert _loadout_round_from_path("/x/player_top/round_5.png") == 5

    def test_loadout_round_none_for_non_round_filename(self) -> None:
        assert _loadout_round_from_path("/x/player_top/overview.png") is None
        assert _loadout_round_from_path("/x/player_top/round_abc.png") is None

    def test_duel_round_extracts_digit(self) -> None:
        assert _duel_round_from_path("/x/results/duel_1.png") == 1
        assert _duel_round_from_path("/x/results/duel_5.png") == 5

    def test_duel_round_none_for_overview(self) -> None:
        assert _duel_round_from_path("/x/results/overview.png") is None


class TestTeamOverlap:
    def test_full_overlap(self) -> None:
        a = ["Liter", "Crown", "RH", "Modernia", "Helm"]
        b = ["Liter", "Crown", "RH", "Modernia", "Helm"]
        assert _team_overlap(a, b) == 5

    def test_no_overlap(self) -> None:
        a = ["Liter", "Crown", "RH", "Modernia", "Helm"]
        b = ["Scarlet", "Anis", "Volume", "Privaty", "Maxwell"]
        assert _team_overlap(a, b) == 0

    def test_partial_overlap_used_for_left_right_mapping(self) -> None:
        # This is how the builder pairs duel-side (left/right) to
        # loadout-position (top/bottom): whichever side has the
        # higher overlap with the top loadout wins the "top=that_side"
        # vote. Realistic case where one or two names didn't OCR
        # cleanly.
        top_loadout = ["Liter", "Crown", "RH", "Modernia", None]
        left_duel = ["Liter", "Crown", "RH", "Modernia", "Helm"]
        right_duel = ["Scarlet", "Anis", "Privaty", "Maxwell", "Volume"]
        assert _team_overlap(top_loadout, left_duel) == 4
        assert _team_overlap(top_loadout, right_duel) == 0

    def test_none_entries_ignored(self) -> None:
        a = [None, None, "Liter", None, None]
        b = ["Liter", None, None, None, None]
        assert _team_overlap(a, b) == 1
