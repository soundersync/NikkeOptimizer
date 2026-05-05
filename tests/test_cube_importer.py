"""Test the cube screenshot extractor + importer against the user's fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlmodel import select

from nikke_copilot.data.db import get_session, init_db, make_engine
from nikke_copilot.data.models import Cube
from nikke_copilot.roster.cube_extractor import extract_cube
from nikke_copilot.roster.cube_importer import import_cubes

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Apple Vision OCR required (macOS only)"
)

CUBE_DIR = Path(__file__).parent / "fixtures" / "screenshots" / "Cubes"

# Every cube in the user's fixture set should fully parse. The full list is
# checked below; numeric OCR character errors (e.g. one cube reads ATK=190
# when the true value is 790) are silent — flagged via cross-level sanity
# checks downstream rather than at extraction time.
EXPECTED_FULLY_PARSED = {
    "Assault Cube",
    "Onslaught Cube",
    "Resilience Cube",
    "Bastion Cube",
    "Adjutant Cube",
    "Wingman Cube",
    "Quantum Cube",
    "Vigor Cube",
    "Endurance Cube",
    "Healing Cube",
    "Tempering Cube",
    "Assist Cube",
    "Destruction Cube",
    "Piercing Cube",
}


def test_extract_assault_cube():
    """Smoke test on the canonical Assault Cube screenshot."""
    if not (CUBE_DIR / "IMG_2166.jpg").exists():
        pytest.skip("Assault Cube fixture missing")
    e = extract_cube(CUBE_DIR / "IMG_2166.jpg")
    assert e.name == "Assault Cube"
    assert e.level == 7
    assert e.atk == 910
    assert e.hp == 27300
    assert e.def_ == 180
    assert e.equipping_count_equipped == 4
    assert e.equipping_count_owned == 4
    assert e.rarity_scope == "Universal"
    assert e.is_complete


def test_equip_status_close_bracket_repair():
    """The 'Endurance Cube' fixture loses the closing ')' to OCR — extractor
    must recover the equipping count via the trailing-1 repair heuristic."""
    if not (CUBE_DIR / "IMG_2174.jpg").exists():
        pytest.skip("Endurance Cube fixture missing")
    e = extract_cube(CUBE_DIR / "IMG_2174.jpg")
    assert e.name == "Endurance Cube"
    # Should be 3/4 not 3/41 (the ')' OCR's as '1').
    assert e.equipping_count_equipped == 3
    assert e.equipping_count_owned == 4


def test_import_all_cubes(tmp_path):
    if not CUBE_DIR.exists():
        pytest.skip("Cube fixture directory missing")
    db_path = tmp_path / "cubes.sqlite3"
    report = import_cubes(CUBE_DIR, db_path=db_path)
    assert report.files_seen == 14
    assert report.upserted == 14
    assert report.incomplete == 0, f"incomplete extractions: {report.warnings}"

    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as session:
        cubes = session.exec(select(Cube)).all()
        names = {c.name for c in cubes}
    assert names == EXPECTED_FULLY_PARSED, f"name mismatch: {names ^ EXPECTED_FULLY_PARSED}"

    # Per-cube spot check — the Resilience Cube is L15 with the highest
    # ownership count (12/12).
    resilience = next(c for c in cubes if c.name == "Resilience Cube")
    assert resilience.level == 15
    assert resilience.equipping_count_owned == 12
    assert resilience.atk == 2780
