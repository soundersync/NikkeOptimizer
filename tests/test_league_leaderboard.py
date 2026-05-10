"""Unit tests for league leaderboard regions, crop cutting, and OCR.

PaddleOCR is not exercised here — the heavy ``extract_leaderboard``
path is covered by an end-to-end ingest run on real data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL.Image")

from nikke_optimizer.roster.league_leaderboard import (
    LeaderboardEntry,
    cut_leaderboard_crops,
    parse_cp,
    parse_synchro_level,
    process_league_archive,
    read_sidecar,
    sidecar_path,
    write_sidecar,
)
from nikke_optimizer.roster.league_leaderboard_regions import (
    CP_Y_MIN_BY_RANK,
    LEADERBOARD_REGIONS,
    NAME_Y_MIN_BY_RANK,
    RANK_STRIDE,
    SYNCHRO_Y_MIN_BY_RANK,
    crop_filename,
    regions_by_rank,
)


# ---------------------------------------------------------------------------
# Region constants
# ---------------------------------------------------------------------------


def test_leaderboard_regions_count():
    assert len(LEADERBOARD_REGIONS) == 12


def test_leaderboard_regions_uniform_within_each_field_family():
    """All 4 ranks of a given field share width × height — that's the
    canonical-size invariant the constants exist to encode."""
    by_rank = regions_by_rank()
    for field in ("synchro", "name", "cp"):
        sizes = set()
        for rank in (1, 2, 3, 4):
            r = by_rank[rank][field]
            sizes.add((r.bbox[2] - r.bbox[0], r.bbox[3] - r.bbox[1]))
        assert len(sizes) == 1, f"{field} sizes differ across ranks: {sizes}"


def test_leaderboard_regions_canonical_sizes():
    """Snapshot the canonical sizes so a regression that resizes a
    region (e.g., bad coord-picker paste) trips immediately."""
    by_rank = regions_by_rank()
    r1 = by_rank[1]
    assert (r1["synchro"].bbox[2] - r1["synchro"].bbox[0],
            r1["synchro"].bbox[3] - r1["synchro"].bbox[1]) == (68, 29)
    assert (r1["name"].bbox[2] - r1["name"].bbox[0],
            r1["name"].bbox[3] - r1["name"].bbox[1]) == (263, 48)
    assert (r1["cp"].bbox[2] - r1["cp"].bbox[0],
            r1["cp"].bbox[3] - r1["cp"].bbox[1]) == (287, 52)


def test_regions_by_rank_keys():
    by_rank = regions_by_rank()
    assert sorted(by_rank.keys()) == [1, 2, 3, 4]
    for rank, fields in by_rank.items():
        assert sorted(fields.keys()) == ["cp", "name", "synchro"]


def test_leaderboard_regions_x_locked_per_field():
    """Every rank of a given field shares the same x_min and x_max —
    the in-game UI puts each column at a fixed x, so per-rank variance
    in the constants would be a click-jitter regression."""
    by_rank = regions_by_rank()
    for field in ("synchro", "name", "cp"):
        x_mins = {by_rank[r][field].bbox[0] for r in (1, 2, 3, 4)}
        x_maxs = {by_rank[r][field].bbox[2] for r in (1, 2, 3, 4)}
        assert len(x_mins) == 1, f"{field} x_min varies across ranks: {x_mins}"
        assert len(x_maxs) == 1, f"{field} x_max varies across ranks: {x_maxs}"


def test_synchro_y_stride_locked_across_all_ranks():
    """Synchro is in the left column, outside the rank-1 banner's
    horizontal span. Every consecutive-rank stride is locked to
    exactly RANK_STRIDE (no per-click drift)."""
    strides = [
        SYNCHRO_Y_MIN_BY_RANK[i + 1] - SYNCHRO_Y_MIN_BY_RANK[i]
        for i in range(3)
    ]
    for s in strides:
        assert s == RANK_STRIDE, f"synchro stride {s} != {RANK_STRIDE}"


def test_name_cp_y_stride_locked_ranks_2_to_4():
    """Name + cp share the same row template from rank 2 onward, with
    stride locked to exactly RANK_STRIDE. The rank-1→2 stride is
    intentionally NOT asserted here — it's compressed by the
    qualifying banner above rank 1's name + cp."""
    for label, anchors in (("name", NAME_Y_MIN_BY_RANK), ("cp", CP_Y_MIN_BY_RANK)):
        for i in (1, 2):  # ranks 2→3, 3→4 only
            stride = anchors[i + 1] - anchors[i]
            assert stride == RANK_STRIDE, (
                f"{label} rank-{i + 1}→{i + 2} stride {stride} != {RANK_STRIDE}"
            )


def test_rank1_name_cp_offset_by_banner():
    """Rank 1's row carries a 'qualified for Promotion Tournament'
    banner above the name + cp fields, pushing both ~20 px below the
    flat-stride position. The constants must encode this offset; a
    future "stride correction" pass that flattens rank 1 will trip
    this guard.

    Specifically: the rank-1→2 stride for name + cp should fall in
    [225, 240] (≈ 251 − 20), well below the uniform 251 ± 2 the
    later ranks share.
    """
    name_stride_1_to_2 = NAME_Y_MIN_BY_RANK[1] - NAME_Y_MIN_BY_RANK[0]
    cp_stride_1_to_2 = CP_Y_MIN_BY_RANK[1] - CP_Y_MIN_BY_RANK[0]
    assert 225 <= name_stride_1_to_2 <= 240, (
        f"name rank-1→2 stride {name_stride_1_to_2} outside the banner range"
    )
    assert 225 <= cp_stride_1_to_2 <= 240, (
        f"cp rank-1→2 stride {cp_stride_1_to_2} outside the banner range"
    )


# ---------------------------------------------------------------------------
# Cutting from master
# ---------------------------------------------------------------------------


def test_cut_leaderboard_crops_writes_12_files(tmp_path: Path):
    PIL.new("RGB", (1080, 2400), (12, 14, 18)).save(tmp_path / "leaderboard.png")
    n = cut_leaderboard_crops(tmp_path)
    assert n == 12
    crops = sorted(tmp_path.glob("leaderboard__*__crop.png"))
    assert len(crops) == 12
    # Every crop matches its region's bbox dimensions exactly.
    by_filename = {c.name: c for c in crops}
    for region in LEADERBOARD_REGIONS:
        path = by_filename[crop_filename(region)]
        with PIL.open(path) as img:
            expected_w = region.bbox[2] - region.bbox[0]
            expected_h = region.bbox[3] - region.bbox[1]
            assert img.size == (expected_w, expected_h)


def test_cut_leaderboard_crops_idempotent(tmp_path: Path):
    PIL.new("RGB", (1080, 2400), (12, 14, 18)).save(tmp_path / "leaderboard.png")
    first = cut_leaderboard_crops(tmp_path)
    assert first == 12
    second = cut_leaderboard_crops(tmp_path)
    assert second == 0


def test_cut_leaderboard_crops_skips_when_master_missing(tmp_path: Path):
    assert cut_leaderboard_crops(tmp_path) == 0


def test_cut_leaderboard_crops_clamps_to_master_bounds(tmp_path: Path):
    """A master too small for a region's bbox gets the bbox clamped to
    the image bounds rather than throwing."""
    # The leaderboard regions go up to y≈1634; this 1080×800 master
    # forces clamping for the bottom-rank crops.
    PIL.new("RGB", (1080, 800), (10, 10, 10)).save(tmp_path / "leaderboard.png")
    n = cut_leaderboard_crops(tmp_path)
    assert n == 12
    # Every output file still exists at its canonical dimensions.
    for region in LEADERBOARD_REGIONS:
        path = tmp_path / crop_filename(region)
        assert path.is_file()
        with PIL.open(path) as img:
            assert img.size == (
                region.bbox[2] - region.bbox[0],
                region.bbox[3] - region.bbox[1],
            )


# ---------------------------------------------------------------------------
# Text post-processors
# ---------------------------------------------------------------------------


def test_parse_cp_handles_commas_and_units():
    assert parse_cp("3,294,200") == 3294200
    assert parse_cp("3294200") == 3294200
    assert parse_cp("CP 3,294,200") == 3294200
    assert parse_cp("X 3736822") == 3736822  # OCR sometimes prefixes garbage
    assert parse_cp("") is None
    assert parse_cp("---") is None


def test_parse_synchro_level_strips_prefix():
    assert parse_synchro_level("Lv. 257") == 257
    assert parse_synchro_level("LV.300") == 300
    assert parse_synchro_level("257") == 257
    assert parse_synchro_level("") is None


# ---------------------------------------------------------------------------
# Sidecar
# ---------------------------------------------------------------------------


def test_sidecar_round_trip(tmp_path: Path):
    entries = [
        LeaderboardEntry(
            rank=1, name="Alpha", name_confidence=0.99,
            name_crop="leaderboard__rank1_name__crop.png",
            cp=3294200, cp_text="3,294,200", cp_confidence=0.95,
            cp_crop="leaderboard__rank1_cp__crop.png",
            synchro_level=257, synchro_text="Lv.257", synchro_confidence=0.97,
            synchro_crop="leaderboard__rank1_synchro__crop.png",
        ),
        LeaderboardEntry(
            rank=2, name="Bravo", name_confidence=0.98,
            name_crop="leaderboard__rank2_name__crop.png",
            cp=3100000, cp_text="3,100,000", cp_confidence=0.94,
            cp_crop="leaderboard__rank2_cp__crop.png",
            synchro_level=255, synchro_text="Lv.255", synchro_confidence=0.96,
            synchro_crop="leaderboard__rank2_synchro__crop.png",
        ),
    ]
    out = write_sidecar(tmp_path, entries)
    assert out == sidecar_path(tmp_path)
    assert out.is_file()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "entries" in payload and len(payload["entries"]) == 2

    parsed = read_sidecar(tmp_path)
    assert parsed == entries


def test_read_sidecar_missing_returns_none(tmp_path: Path):
    assert read_sidecar(tmp_path) is None


def test_process_league_archive_skips_when_no_crops(tmp_path: Path):
    # No crops + no master → no OCR call, no sidecar.
    assert process_league_archive(tmp_path) is None


def test_process_league_archive_idempotent_when_sidecar_exists(tmp_path: Path):
    write_sidecar(tmp_path, [])
    out = process_league_archive(tmp_path)
    assert out == sidecar_path(tmp_path)
