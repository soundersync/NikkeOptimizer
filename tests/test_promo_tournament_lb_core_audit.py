"""Tests for the LB/Core audit constants module."""
from __future__ import annotations

import pytest

from nikke_optimizer.roster.promo_tournament_lb_core_audit import (
    AUDIT_KEYS,
    DISPLAY_LABELS,
    EXEMPLAR_FILES,
    OLD_TO_NEW_NORMALIZED,
    parse_lb_core_class,
)


def test_twelve_audit_keys():
    assert len(AUDIT_KEYS) == 12
    assert len(set(AUDIT_KEYS)) == 12


def test_display_labels_cover_all_keys():
    assert set(DISPLAY_LABELS) == set(AUDIT_KEYS)


def test_exemplar_files_cover_all_non_unknown_keys():
    """Every key except ``unknown`` should map to a PNG filename."""
    assert set(EXEMPLAR_FILES) == set(AUDIT_KEYS) - {"unknown"}


@pytest.mark.parametrize(
    "key,expected",
    [
        ("lb0", (0, None)),
        ("lb1", (1, None)),
        ("lb2", (2, None)),
        ("mlb_c0", (3, 0)),
        ("mlb_c1", (3, 1)),
        ("mlb_c6", (3, 6)),
        ("mlb_max", (3, 7)),
        ("unknown", (-1, None)),
    ],
)
def test_parse_lb_core_class(key, expected):
    assert parse_lb_core_class(key) == expected


def test_parse_unknown_key_raises():
    with pytest.raises(ValueError):
        parse_lb_core_class("not-a-real-key")


def test_old_to_new_normalized_targets_are_valid():
    """Every target of the migration map must be in AUDIT_KEYS."""
    for v in OLD_TO_NEW_NORMALIZED.values():
        assert v in AUDIT_KEYS, f"migration target {v!r} not in AUDIT_KEYS"


def test_old_to_new_normalized_covers_phase2_outputs():
    """Every value the Phase 2 detector could have emitted must appear
    as a key in OLD_TO_NEW_NORMALIZED. Old shapes were:

        - ``"0"``..``"2"`` for LB<3
        - ``"3"`` for MLB+badge but unparseable
        - ``"3,0"``..``"3,7"`` for MLB+Core 0..7
    """
    expected = {"0", "1", "2", "3"} | {f"3,{i}" for i in range(8)}
    assert expected.issubset(set(OLD_TO_NEW_NORMALIZED))
