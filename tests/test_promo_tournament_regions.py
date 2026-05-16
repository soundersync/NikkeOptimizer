"""Sanity tests for the Promotion Tournament coord schema.

These are pure-data assertions — every coord must be in-bounds, have
positive dimensions, and slugs must be unique within each kind.
"""

from __future__ import annotations

import pytest

from nikke_optimizer.roster.promo_tournament_regions import (
    DUEL,
    KINDS,
    OVERVIEW,
    PLAYER_LOADOUT,
    REFERENCE_IMAGE_SIZE,
    Region,
    region_by_slug,
    regions_for_kind,
)


def _all_regions() -> list[Region]:
    return [*PLAYER_LOADOUT, *OVERVIEW, *DUEL]


def test_kinds_match_dispatch():
    for kind in KINDS:
        assert regions_for_kind(kind), f"empty regions for {kind}"


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        regions_for_kind("not_a_kind")


@pytest.mark.parametrize("region", _all_regions())
def test_bbox_in_bounds(region: Region):
    w, h = REFERENCE_IMAGE_SIZE
    x1, y1, x2, y2 = region.bbox
    assert 0 <= x1 < x2 <= w, f"{region.slug}: x out of range {region.bbox}"
    assert 0 <= y1 < y2 <= h, f"{region.slug}: y out of range {region.bbox}"


@pytest.mark.parametrize("region", _all_regions())
def test_bbox_positive_dims(region: Region):
    x1, y1, x2, y2 = region.bbox
    assert x2 - x1 >= 5, f"{region.slug}: width {x2 - x1} too small"
    assert y2 - y1 >= 5, f"{region.slug}: height {y2 - y1} too small"


@pytest.mark.parametrize("kind", KINDS)
def test_slugs_unique_within_kind(kind: str):
    slugs = [r.slug for r in regions_for_kind(kind)]
    assert len(slugs) == len(set(slugs)), f"duplicate slugs in {kind}: {slugs}"


def test_player_loadout_count():
    # 3 header (name + level + team CP) + 5 chars × 4 fields = 23
    assert len(PLAYER_LOADOUT) == 23


def test_overview_count():
    # 3 header (winner + left + right) + 5 round strips = 8
    assert len(OVERVIEW) == 8


def test_duel_count():
    # 5 chars × 5 fields × 2 sides = 50
    assert len(DUEL) == 50


def test_region_by_slug_lookup():
    r = region_by_slug("player_loadout", "char3.cp")
    assert r is not None
    assert r.bbox == (680, 1373, 829, 1412)
    assert region_by_slug("player_loadout", "nope") is None


def test_duel_groups_partition_by_side_and_char():
    by_group: dict[str, list[Region]] = {}
    for r in DUEL:
        by_group.setdefault(r.group or "", []).append(r)
    # 10 groups (left.char1..char5, right.char1..char5), each with 5 fields.
    assert len(by_group) == 10
    for group, regions in by_group.items():
        assert len(regions) == 5, f"group {group} has {len(regions)} regions"
