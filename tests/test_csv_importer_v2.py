"""Tests for the v2 CSV format (2026-05-08+) parsing.

The v2 CSV adds:
  - ``Limit Break`` column ("3/3" format) — separates LB stars from Core
  - ``Core Level`` column accepts ``"max"`` (= 7) instead of numeric only
  - ``Bond Rank`` / ``Bond HP/DEF/ATK`` (per-character bond stats)
  - ``Class Rank Level`` / ``Class Rank HP/DEF/ATK``
  - ``Manufacturer Rank Level`` / ``Mfr Rank HP/DEF/ATK``

Plus a parser fix: stat blocks now accept ``,`` as a separator
(previously only ``/`` and ``;``).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from nikke_optimizer.roster.csv_importer import (
    _is_v2_format,
    _parse_core_level,
    _parse_limit_break,
)
from nikke_optimizer.roster.csv_parsers import parse_stats_block


def test_parse_core_level_max_means_seven():
    assert _parse_core_level("max") == 7
    assert _parse_core_level("MAX") == 7
    assert _parse_core_level(" max ") == 7


def test_parse_core_level_numeric():
    for v in range(0, 8):
        assert _parse_core_level(str(v)) == v


def test_parse_core_level_empty_or_invalid():
    assert _parse_core_level("") is None
    assert _parse_core_level(None) is None
    assert _parse_core_level("nonsense") is None


def test_parse_core_level_clamps_out_of_range():
    assert _parse_core_level("99") == 7
    assert _parse_core_level("-3") == 0


def test_parse_limit_break_current_max_format():
    assert _parse_limit_break("3/3") == 3
    assert _parse_limit_break("0/3") == 0
    assert _parse_limit_break("0/2") == 0
    assert _parse_limit_break("2/2") == 2
    assert _parse_limit_break("2/3") == 2


def test_parse_limit_break_empty_or_invalid():
    assert _parse_limit_break("") is None
    assert _parse_limit_break(None) is None
    assert _parse_limit_break("garbage") is None


def test_is_v2_format_detects_limit_break_column():
    assert _is_v2_format(["Name", "Power", "Limit Break", "Core Level"]) is True
    assert _is_v2_format(["Name", "Power", "Core Level"]) is False


def test_parse_stats_block_handles_comma_separator():
    """v2 CSV uses ", " between stats. v1 used " / " or "; ".
    All three must work."""
    # v2 format
    assert parse_stats_block("HP 301800, ATK 9688, DEF 2058") == {
        "hp": 301800, "atk": 9688, "def": 2058
    }
    assert parse_stats_block("ATK 2780, DEF 552, HP 83400") == {
        "atk": 2780, "def": 552, "hp": 83400
    }
    # v1 legacy formats
    assert parse_stats_block("HP 73772 / ATK 9021") == {"hp": 73772, "atk": 9021}
    assert parse_stats_block("HP 73772; ATK 9021") == {"hp": 73772, "atk": 9021}


def test_parse_stats_block_empty():
    assert parse_stats_block("") == {}
    assert parse_stats_block(None) == {}


@pytest.fixture
def v2_csv(tmp_path: Path) -> Path:
    """Tiny v2-format CSV with one fully-described character."""
    p = tmp_path / "roster_v2.csv"
    headers = [
        "Name", "Power", "Synchro Level", "Rank", "Rarity", "Squad", "Class",
        "Manufacturer", "Class Rank Level", "Manufacturer Rank Level",
        "Limit Break", "Core Level", "HP", "ATK", "DEF",
        "Bond Rank", "Bond HP", "Bond DEF", "Bond ATK",
        "Class Rank HP", "Class Rank DEF", "Class Rank ATK",
        "Mfr Rank HP", "Mfr Rank DEF", "Mfr Rank ATK",
        "Skill 1 Level", "Skill 2 Level", "Burst Level",
    ]
    row = [
        "Snow White: Heavy Arms", "534315", "654", "35", "SSR", "Goddess",
        "Attacker", "Pilgrim", "179", "167",
        "3/3", "max", "9356366", "401922", "53820",
        "35", "44658", "298", "1985",
        "134250", "895", "0",
        "0", "835", "4175",
        "10", "10", "10",
    ]
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerow(row)
    return p


def test_v2_csv_dry_run_detects_format(v2_csv: Path, tmp_path: Path):
    """End-to-end: dry-run a v2 CSV against an empty DB. Should detect
    v2, attempt to match the row, and report unmatched (since the DB
    is empty)."""
    from nikke_optimizer.roster.csv_importer import dry_run_diff

    db_path = tmp_path / "test.sqlite3"
    report = dry_run_diff(v2_csv, db_path=db_path)
    assert report.format_version == "v2"
    assert report.rows == 1
    # Empty DB → unmatched
    assert report.unmatched == ["Snow White: Heavy Arms"]
