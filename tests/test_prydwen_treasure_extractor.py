"""Tests for ``prydwen.extract_treasure_skills``.

Uses a fixture file captured from Prydwen's gatsby data endpoint
(``page-data/nikke/characters/helm-treasure/page-data.json``). Validates:

  - 3 skills are returned with phase 1, 2, 3 in order;
  - skill names + slots match Prydwen's labels;
  - description text contains key magnitudes from the in-game text.

Captured fixture is committed under ``tests/fixtures/prydwen/`` and
trimmed to only the fields the extractor reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nikke_optimizer.data.scrapers.prydwen import extract_treasure_skills


FIXTURE = Path(__file__).parent / "fixtures" / "prydwen" / "helm_treasure_node.json"


def _load_node() -> dict:
    return json.loads(FIXTURE.read_text())


def test_extracts_three_skills_with_phases():
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    node = _load_node()
    rows = extract_treasure_skills(node)
    assert len(rows) == 3
    assert [r["upgrade_phase"] for r in rows] == [1, 2, 3]
    assert [r["skill_index"] for r in rows] == [1, 2, 3]


def test_skill_names_match_prydwen():
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    rows = extract_treasure_skills(_load_node())
    names = [r["name"] for r in rows]
    assert names == ["Frontline Command", "Fire Away", "Aegis Cannon"]


def test_descriptions_contain_treasure_magnitudes():
    """Spot-check a magnitude unique to the treasured skill text."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    rows = extract_treasure_skills(_load_node())
    # Burst (skill 3, phase 3) should mention the 8236.8% nuke.
    burst = next(r for r in rows if r["skill_index"] == 3)
    assert "8236.8" in (burst["description_treasured"] or "")


def test_returns_empty_for_non_treasure_node():
    """A node without phase fields on its skills returns an empty list."""
    node = {"skills": [{"name": "X", "slot": "Skill 1"}]}
    assert extract_treasure_skills(node) == []


def test_handles_missing_skills_field():
    assert extract_treasure_skills({}) == []
    assert extract_treasure_skills({"skills": None}) == []
