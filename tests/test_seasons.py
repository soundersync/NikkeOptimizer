"""Unit tests for the beta-season cadence module."""

from __future__ import annotations

from datetime import date

from nikke_optimizer.data.seasons import (
    is_season_folder,
    parse_season_number,
    season_for_date,
    season_id,
    season_id_for_number,
    season_start,
)


def test_anchor_dates_resolve_to_their_own_seasons():
    cases = [
        (date(2025, 12, 4), 18),
        (date(2025, 12, 18), 19),
        (date(2026, 1, 1), 20),
        (date(2026, 1, 15), 21),
        (date(2026, 1, 29), 22),
        (date(2026, 2, 12), 23),
        (date(2026, 2, 26), 24),
        (date(2026, 3, 12), 25),
        (date(2026, 3, 25), 26),
        (date(2026, 4, 9), 27),
        (date(2026, 4, 23), 28),
        (date(2026, 5, 7), 29),
    ]
    for d, expected in cases:
        assert season_for_date(d) == expected, f"{d} should be season {expected}"


def test_existing_dataset_date_maps_to_season_28():
    # The two datasets currently archived under captures/2026-05-05/
    # belong to Beta Season 28 (Apr 23 — May 6 2026).
    assert season_for_date(date(2026, 5, 5)) == 28
    assert season_id(date(2026, 5, 5)) == "beta_season_28"


def test_dates_within_anchor_ranges_round_down():
    # Day before next anchor still belongs to current season.
    assert season_for_date(date(2026, 5, 6)) == 28
    # Day after a previous anchor's start.
    assert season_for_date(date(2026, 4, 24)) == 28
    # Mid-season day.
    assert season_for_date(date(2026, 4, 30)) == 28


def test_forward_extrapolation_past_latest_anchor():
    # Latest anchor is 29 (May 7 2026). +14 days = season 30.
    assert season_for_date(date(2026, 5, 21)) == 30
    # Day before that is still season 29.
    assert season_for_date(date(2026, 5, 20)) == 29
    # Far future: 4 cadence periods after season 29.
    assert season_for_date(date(2026, 7, 2)) == 33  # May 7 + 56d = Jul 2


def test_backward_extrapolation_before_earliest_anchor():
    # Earliest anchor is 18 (Dec 4 2025). -14 days = season 17 start.
    assert season_for_date(date(2025, 11, 20)) == 17
    # Day before is end of season 17.
    assert season_for_date(date(2025, 12, 3)) == 17
    # Two cadences back.
    assert season_for_date(date(2025, 11, 6)) == 16
    # Day before season 16 start.
    assert season_for_date(date(2025, 11, 5)) == 15


def test_season_start_round_trip_for_anchors():
    for n in range(18, 30):
        assert season_for_date(season_start(n)) == n


def test_season_start_extrapolates_outside_table():
    assert season_start(30) == date(2026, 5, 21)  # 29 + 14d
    assert season_start(31) == date(2026, 6, 4)
    assert season_start(17) == date(2025, 11, 20)  # 18 - 14d


def test_parse_season_number_handles_archive_and_staging_names():
    assert parse_season_number("beta_season_29") == 29
    assert parse_season_number("beta_season_29_2026-05-07") == 29
    assert parse_season_number("beta_season_18") == 18
    assert parse_season_number("not_a_season") is None
    assert parse_season_number("2026-05-05") is None


def test_is_season_folder_strict_match():
    assert is_season_folder("beta_season_29")
    assert is_season_folder("beta_season_18")
    # Staging-style names with extra suffix are NOT canonical archive folders.
    assert not is_season_folder("beta_season_29_2026-05-07")
    assert not is_season_folder("2026-05-05")
    assert not is_season_folder("promotion_tournament")


def test_season_id_for_number():
    assert season_id_for_number(28) == "beta_season_28"
    assert season_id_for_number(29) == "beta_season_29"
