"""Test the auto-classifier + ingest dispatcher."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nikke_optimizer.roster.screenshot_router import (
    classify_screenshot,
    ingest_directory,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Apple Vision OCR required (macOS only)"
)

FIX = Path(__file__).parent / "fixtures" / "screenshots"


def test_classify_csv():
    csv_path = FIX / "nikke_full_roster_data.csv"
    if not csv_path.exists():
        pytest.skip("CSV fixture missing")
    assert classify_screenshot(csv_path) == "csv"


def test_classify_cube():
    p = FIX / "Cubes" / "IMG_2166.jpg"
    if not p.exists():
        pytest.skip("cube fixture missing")
    assert classify_screenshot(p) == "cube"


def test_classify_rookie_arena():
    from glob import glob

    matches = glob(str(FIX / "Rookie_Arena" / "Screenshot*9.37.33*.png"))
    if not matches:
        pytest.skip("rookie fixture missing")
    assert classify_screenshot(Path(matches[0])) == "rookie"


def test_classify_champion_arena():
    p = FIX / "Champion_Arena" / "IMG_2153.PNG"
    if not p.exists():
        pytest.skip("champion fixture missing")
    assert classify_screenshot(p) == "champion"


def test_ingest_dry_run_full_directory():
    """Dry-run on the whole fixtures dir — every CSV + cube + arena file
    should classify, and nothing should be written to the DB."""
    if not FIX.exists():
        pytest.skip("fixtures dir missing")
    report = ingest_directory(FIX, classify_only=True)
    assert report.files_seen > 0
    assert report.csv >= 1
    assert report.cube >= 14
    assert report.rookie >= 1
    assert report.champion >= 1
    # Portrait library files should NOT be classified as anything actionable.
    portrait_paths = [
        p for p, cls in report.classifications.items()
        if "Portrait_library" in p
    ]
    assert all(report.classifications[p] == "unknown" for p in portrait_paths)
