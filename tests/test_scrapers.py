"""Offline tests for the Prydwen scraper using cached fixtures.

The fixtures in tests/fixtures/prydwen/ are real Prydwen page-data.json files
captured at a known good state. These tests exercise normalization + DB upsert
without requiring network access.
"""

import json
from pathlib import Path

import pytest
from sqlmodel import select

from nikke_copilot.data.db import get_session, init_db, make_engine
from nikke_copilot.data.enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)
from nikke_copilot.data.models import Character
from nikke_copilot.data.scrapers.prydwen import (
    NormalizedCharacter,
    normalize_character_node,
)
from nikke_copilot.data.scrapers.refresh import upsert_character

FIXTURES = Path(__file__).parent / "fixtures" / "prydwen"


def _load_node(slug: str) -> dict:
    data = json.loads((FIXTURES / f"char_{slug}.json").read_text())
    return data["result"]["data"]["currentUnit"]["nodes"][0]


def test_normalize_crown():
    node = _load_node("crown")
    norm = normalize_character_node(node)
    assert norm is not None
    assert norm.name == "Crown"
    assert norm.rarity == Rarity.SSR
    assert norm.element == Element.IRON
    assert norm.weapon_class == WeaponClass.MG
    assert norm.burst_type == BurstType.II
    assert norm.manufacturer == Manufacturer.PILGRIM
    assert "Defender" in norm.role_tags
    assert "Buffer" in norm.role_tags
    assert norm.skill1_description and len(norm.skill1_description) > 20
    assert norm.burst_description and len(norm.burst_description) > 20


def test_normalize_red_hood_flex_burst():
    node = _load_node("red-hood")
    norm = normalize_character_node(node)
    assert norm is not None
    assert norm.name == "Red Hood"
    assert norm.burst_type == BurstType.FLEX


@pytest.mark.parametrize(
    "slug,expected_weapon",
    [
        ("crown", WeaponClass.MG),
        ("liter", WeaponClass.SMG),
        ("cinderella", WeaponClass.RL),
    ],
)
def test_weapon_normalization(slug: str, expected_weapon: WeaponClass):
    node = _load_node(slug)
    norm = normalize_character_node(node)
    assert norm is not None
    assert norm.weapon_class is expected_weapon


def test_upsert_inserts_then_updates():
    engine = make_engine(Path(":memory:"))
    init_db(engine)

    node = _load_node("crown")
    norm = normalize_character_node(node)
    assert norm is not None

    with get_session(engine) as session:
        upsert_character(session, norm)
        session.commit()

        count1 = len(session.exec(select(Character)).all())
        assert count1 == 1

        # Mutate then upsert again — should update, not insert
        norm2 = NormalizedCharacter(**{**norm.to_kwargs(), "raw_node": None})
        norm2.role_tags = ["Defender", "Buffer", "MutatedTag"]
        upsert_character(session, norm2)
        session.commit()

        count2 = len(session.exec(select(Character)).all())
        assert count2 == 1
        existing = session.exec(
            select(Character).where(Character.name == "Crown")
        ).one()
        assert "MutatedTag" in existing.role_tags
