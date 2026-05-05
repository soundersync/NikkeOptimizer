"""End-to-end test against the user-provided Character_icons screenshot.

This is intentionally lenient: OCR on stylized name banners with cut-off
text is imperfect, so we assert "≥ K of the visible characters resolve to
high-confidence matches" rather than 100%. The threshold can be tightened
once we add icon-classifier fallback for low-OCR-confidence cells.
"""

from __future__ import annotations

import sys
from glob import glob
from pathlib import Path

import pytest
from sqlmodel import select

from nikke_copilot.data.db import get_session, init_db, make_engine
from nikke_copilot.data.models import Character, CharacterIcon
from nikke_copilot.data.scrapers.prydwen import normalize_character_node
from nikke_copilot.data.scrapers.refresh import upsert_character

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Apple Vision OCR required (macOS only)"
)

PRYDWEN_FIXTURES = Path(__file__).parent / "fixtures" / "prydwen"


def _seed_full_index(engine):
    """Seed the DB with the cached Prydwen index fixture (all 206 chars)."""
    import json

    data = json.loads((PRYDWEN_FIXTURES / "index.json").read_text())
    nodes = data["result"]["data"]["allCharacters"]["nodes"]
    # Index nodes lack the rich detail; promote each to a minimal Character row.
    from nikke_copilot.data.enums import (
        BurstType,
        Element,
        Manufacturer,
        Rarity,
        WeaponClass,
    )

    burst_map = {"1": BurstType.I, "2": BurstType.II, "3": BurstType.III, "All": BurstType.FLEX}
    weapon_map = {
        "SMG": WeaponClass.SMG,
        "Assault Rifle": WeaponClass.AR,
        "Sniper Rifle": WeaponClass.SR,
        "Rocket Launcher": WeaponClass.RL,
        "Shotgun": WeaponClass.SG,
        "Minigun": WeaponClass.MG,
    }
    elem_map = {
        "Fire": Element.FIRE,
        "Water": Element.WATER,
        "Electric": Element.ELECTRIC,
        "Iron": Element.IRON,
        "Wind": Element.WIND,
    }
    rar_map = {"R": Rarity.R, "SR": Rarity.SR, "SSR": Rarity.SSR}
    mfg_map = {
        "Elysion": Manufacturer.ELYSION,
        "Missilis": Manufacturer.MISSILIS,
        "Tetra": Manufacturer.TETRA,
        "Pilgrim": Manufacturer.PILGRIM,
        "Abnormal": Manufacturer.ABNORMAL,
    }
    with get_session(engine) as session:
        seen = set()
        for n in nodes:
            try:
                char = Character(
                    name=n["name"],
                    rarity=rar_map[n["rarity"]],
                    element=elem_map[n["element"]],
                    weapon_class=weapon_map[n["weapon"]],
                    burst_type=burst_map[str(n["burstType"])],
                    manufacturer=mfg_map.get(n.get("manufacturer", "")),
                    role_tags=[n["class"]] + (n.get("specialities") or []),
                )
            except KeyError:
                continue
            if n["name"] in seen:
                continue
            seen.add(n["name"])
            session.add(char)
        session.commit()


def _icon_screenshot() -> Path:
    matches = glob(str(Path(__file__).parent / "fixtures" / "screenshots" / "Character_icons" / "*.png"))
    if not matches:
        pytest.skip(
            "Character_icons fixture absent — superseded by labeled Portrait_library "
            "+ CSV import flow; icon-library tests retained for reference."
        )
    return Path(matches[0])


def test_extract_icons_returns_grid(tmp_path):
    from nikke_copilot.roster.icon_library import extract_icons

    extractions = extract_icons(_icon_screenshot(), cols=4)
    assert len(extractions) >= 16  # at least 4 rows × 4 cols
    # All cells should have produced a non-empty crop image
    assert all(x.crop.size[0] > 0 and x.crop.size[1] > 0 for x in extractions)


def test_resolve_matches_against_full_index():
    from nikke_copilot.roster.icon_library import (
        extract_icons,
        resolve_matches,
    )

    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_full_index(engine)

    extractions = extract_icons(_icon_screenshot(), cols=4)
    with get_session(engine) as session:
        all_names = [c.name for c in session.exec(select(Character)).all()]

    resolved = resolve_matches(extractions, all_names)
    confident = [x for x in resolved if x.is_confident and x.matched_name]
    print(f"\n--- ICON MATCHES ({len(confident)}/{len(resolved)} confident) ---")
    for x in resolved:
        marker = "OK " if x.is_confident else "?? "
        print(
            f"{marker} {x.cell_index} ocr={x.ocr_name_raw!r:30s} "
            f"-> {x.matched_name!r} (conf={x.match_confidence:.2f})"
        )
    # Lenient: at least 8 of 20 cells should resolve confidently.
    assert len(confident) >= 8, f"only {len(confident)} confident matches"


def test_save_icon_library(tmp_path):
    from nikke_copilot.roster.icon_library import (
        extract_icons,
        resolve_matches,
        save_icon_library,
    )

    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_full_index(engine)

    extractions = extract_icons(_icon_screenshot(), cols=4)
    with get_session(engine) as session:
        all_names = [c.name for c in session.exec(select(Character)).all()]
    resolved = resolve_matches(extractions, all_names)

    output = tmp_path / "icons"
    with get_session(engine) as session:
        counts = save_icon_library(resolved, output, session)
    assert counts["confident"] + counts["review"] >= len(resolved) - 5
    # Each confident extraction wrote exactly one PNG into its character folder
    # (excluding the _review folder).
    confident_pngs = [
        p for p in output.glob("*/*.png") if p.parent.name != "_review"
    ]
    review_pngs = list((output / "_review").glob("*.png"))
    assert len(confident_pngs) == counts["confident"]
    assert len(review_pngs) == counts["review"]

    with get_session(engine) as session:
        rows = session.exec(select(CharacterIcon)).all()
        assert len(rows) == counts["confident"]
    # ≥ 17 of 20 visible icons should resolve confidently — anchor for regression.
    assert counts["confident"] >= 17, f"only {counts['confident']} confident icons saved"
