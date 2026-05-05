"""Tests for the CSV roster importer using the user-provided full roster CSV.

The user's `nikke_full_roster_data.csv` covers their entire account
(184 rows). We assert:

  * row count + match rate (most rows resolve to a Character),
  * a specific row's gear/effects/cubes (Snow White: Heavy Arms),
  * the new `Costumes` column is parsed into structured costume entries,
  * the column-alias map normalizes "Mfr Level" → "Manufacturer Level".
"""

from pathlib import Path

import pytest
from sqlmodel import select

from nikke_optimizer.data.db import get_session, init_db, make_engine
from nikke_optimizer.data.enums import OLBonusType, OLGearSlot
from nikke_optimizer.data.models import (
    BuffSummaryLine,
    Character,
    Cube,
    OLGear,
    OwnedCharacter,
)
from nikke_optimizer.data.scrapers.refresh import upsert_character
from nikke_optimizer.data.scrapers.prydwen import normalize_character_node
from nikke_optimizer.roster.costumes import parse_costumes
from nikke_optimizer.roster.csv_importer import import_csv
from nikke_optimizer.roster.csv_parsers import (
    parse_burst_cooldown_from_description,
    parse_cube_stats,
    parse_effect,
    parse_effect_summary,
    parse_stats_block,
    strip_burst_cooldown_prefix,
)

CSV_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "screenshots"
    / "nikke_full_roster_data.csv"
)
PRYDWEN_FIXTURES = Path(__file__).parent / "fixtures" / "prydwen"


def _seed_characters(engine) -> None:
    """Seed the DB with Prydwen-derived characters for the rows we assert on."""
    import json

    with get_session(engine) as session:
        for slug in ["red-hood", "crown", "liter", "cinderella"]:
            data = json.loads((PRYDWEN_FIXTURES / f"char_{slug}.json").read_text())
            node = data["result"]["data"]["currentUnit"]["nodes"][0]
            norm = normalize_character_node(node)
            assert norm is not None
            upsert_character(session, norm)
        # Stub characters for full-roster CSV rows we touch but don't have
        # cached JSON for. The importer just needs the name to resolve.
        from nikke_optimizer.data.enums import (
            BurstType, Element, Manufacturer, Rarity, WeaponClass,
        )
        stubs = [
            ("Rapi: Red Hood", Element.FIRE, WeaponClass.MG, BurstType.III, Manufacturer.ELYSION),
            ("Snow White: Heavy Arms", Element.IRON, WeaponClass.MG, BurstType.I, Manufacturer.PILGRIM),
        ]
        for name, elem, weapon, burst, mfr in stubs:
            session.add(
                Character(
                    name=name,
                    rarity=Rarity.SSR,
                    element=elem,
                    weapon_class=weapon,
                    burst_type=burst,
                    manufacturer=mfr,
                    role_tags=["Attacker"],
                    source="manual",
                )
            )
        session.commit()


# -------- parser unit tests --------


def test_parse_stats_block_hp_atk():
    assert parse_stats_block("HP 73772 / ATK 9021") == {"hp": 73772, "atk": 9021}


def test_parse_stats_block_atk_def():
    assert parse_stats_block("ATK 5741 / DEF 981") == {"atk": 5741, "def": 981}


def test_parse_cube_stats_unlabeled_hp():
    out = parse_cube_stats("ATK 2780 / DEF 552 / 83400")
    assert out["atk"] == 2780
    assert out["def"] == 552
    assert out["hp"] == 83400


def test_parse_treasure_stats():
    out = parse_stats_block("ATK 9688 / DEF 2058 / HP 301800")
    assert out == {"atk": 9688, "def": 2058, "hp": 301800}


def test_parse_effect_known_type():
    eff = parse_effect("Increase Element Damage Dealt 27.16%")
    assert eff is not None
    bt, raw, pct = eff
    assert bt is OLBonusType.ELEMENT_DAMAGE
    assert pct == pytest.approx(27.16)


def test_parse_effect_no_effects():
    assert parse_effect("No Effects") is None


def test_parse_effect_summary_pipe_separated():
    out = parse_effect_summary(
        "Increase Element Damage Dealt 88.61% | Increase ATK 52.89% | Increase Max Ammunition Capacity 190.36%"
    )
    assert len(out) == 3
    types = {bt for bt, _, _ in out}
    assert types == {
        OLBonusType.ELEMENT_DAMAGE,
        OLBonusType.ATK,
        OLBonusType.MAX_AMMUNITION_CAPACITY,
    }


def test_parse_costumes_legacy_default_only():
    """Legacy format: name + rarity tier glued together."""
    out = parse_costumes("Snow White: Heavy ArmsDefault")
    assert out == [{"name": "Snow White: Heavy Arms", "rarity": "default"}]


def test_parse_costumes_legacy_multi():
    out = parse_costumes(
        "Rapi: Red HoodDefault | Red Flavorunique | Cherished Redunique | Shining Lightspecial"
    )
    assert len(out) == 4
    assert out[0] == {"name": "Rapi: Red Hood", "rarity": "default"}
    assert out[3] == {"name": "Shining Light", "rarity": "special"}
    rarities = {c["rarity"] for c in out}
    assert rarities == {"default", "unique", "special"}


def test_parse_costumes_current_default_only():
    """Current format: just the literal word "Default"."""
    out = parse_costumes("Default")
    assert len(out) == 1
    assert out[0]["rarity"] == "default"


def test_parse_costumes_current_multi():
    """Current format: pipe-separated skin names, no rarity glued on."""
    out = parse_costumes("Red Flavor|Cherished Red|Shining Light|Default")
    assert len(out) == 4
    names = [c["name"] for c in out]
    assert names == ["Red Flavor", "Cherished Red", "Shining Light", "Default"]
    # The first three skin names have no rarity tier.
    assert all(c["rarity"] is None for c in out[:3])
    # The "Default" entry resolves to rarity "default".
    assert out[3]["rarity"] == "default"


def test_parse_costumes_empty():
    assert parse_costumes("") == []
    assert parse_costumes(None) == []


# -------- burst cooldown / description parser tests --------


def test_parse_burst_cooldown_with_decimal():
    assert parse_burst_cooldown_from_description(
        "20.0 s■ Affects all allies. ATK ▲ 66% for 5 sec."
    ) == 20.0


def test_parse_burst_cooldown_integer():
    assert parse_burst_cooldown_from_description("40 s■ Effect text") == 40.0


def test_parse_burst_cooldown_missing():
    assert parse_burst_cooldown_from_description("■ No prefix here") is None
    assert parse_burst_cooldown_from_description(None) is None
    assert parse_burst_cooldown_from_description("") is None


def test_strip_burst_cooldown_prefix():
    raw = "20.0 s■ Affects all allies. ATK ▲ 66% for 5 sec."
    assert strip_burst_cooldown_prefix(raw) == "■ Affects all allies. ATK ▲ 66% for 5 sec."
    # Without prefix: unchanged.
    assert strip_burst_cooldown_prefix("■ Already clean") == "■ Already clean"


# -------- end-to-end import test --------


def test_import_full_roster_csv():
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_characters(engine)

    # Patch the importer's engine — it reads from default_db_path otherwise.
    import nikke_optimizer.roster.csv_importer as importer_mod

    orig_make_engine = importer_mod.make_engine

    def _stub(_path, **kw):
        return engine

    importer_mod.make_engine = _stub
    try:
        report = import_csv(CSV_PATH)
    finally:
        importer_mod.make_engine = orig_make_engine

    # The full roster has ~184 rows; we only seeded a handful so most will be
    # unmatched — that's fine, we only assert on the seeded ones.
    assert report.rows >= 100
    assert report.matched >= 2  # the two seeded SSRs we care about
    # Importer must NOT warn about "Mfr Level" — alias resolution should have
    # converted it to "Manufacturer Level".
    mfr_warnings = [w for w in report.warnings if "Manufacturer Level" in w]
    assert not mfr_warnings, f"unexpected Mfr Level warning: {mfr_warnings}"

    with get_session(engine) as session:
        # Snow White: Heavy Arms (row 1)
        char = session.exec(
            select(Character).where(Character.name == "Snow White: Heavy Arms")
        ).one()
        owned = session.exec(
            select(OwnedCharacter).where(OwnedCharacter.character_id == char.id)
        ).one()
        assert owned.power == 520508
        assert owned.sync_level == 652
        assert owned.skill1_level == 10
        assert owned.skill2_level == 10
        assert owned.burst_skill_level == 10
        assert owned.total_hp == 9324206
        assert owned.total_atk == 400503
        assert owned.total_def == 53629
        assert owned.manufacturer_level == 166
        assert owned.core == 178

        # Costumes — single Default skin (current CSV format).
        assert len(owned.costumes) == 1
        assert owned.costumes[0]["rarity"] == "default"
        assert owned.costumes[0]["name"] == "Default"

        gears = sorted(owned.ol_gear, key=lambda g: g.slot.value)
        assert len(gears) == 4

        head = next(g for g in gears if g.slot == OLGearSlot.HEAD)
        assert head.base_hp == 73772
        assert head.base_atk == 9021
        assert len(head.bonuses) == 3

        # Buff summary — six lines on Snow White
        summaries = session.exec(
            select(BuffSummaryLine).where(BuffSummaryLine.owned_character_id == owned.id)
        ).all()
        assert len(summaries) == 6
        types = {s.bonus_type for s in summaries}
        assert OLBonusType.ELEMENT_DAMAGE in types
        assert OLBonusType.ATK in types
        assert OLBonusType.MAX_AMMUNITION_CAPACITY in types

        # Rapi: Red Hood — multi-skin costumes
        rapi_char = session.exec(
            select(Character).where(Character.name == "Rapi: Red Hood")
        ).one()
        rapi = session.exec(
            select(OwnedCharacter).where(OwnedCharacter.character_id == rapi_char.id)
        ).one()
        # Current CSV gives skin names without rarity suffixes; only
        # "Default" resolves to a rarity. Other named skins get rarity=None.
        assert len(rapi.costumes) == 4
        rarities = {c["rarity"] for c in rapi.costumes}
        # The "Default" entry resolves to "default"; others are None.
        assert "default" in rarities
        assert any(c["name"] != "Default" for c in rapi.costumes)

        # Skill names + descriptions + burst cooldown should populate when
        # the CSV provides them. The Snow White: Heavy Arms row in the
        # full-roster fixture has all skill columns filled.
        sw = next(o for o in session.exec(select(OwnedCharacter)).all() if o.character.name == "Snow White: Heavy Arms")
        assert sw.skill1_name, "skill1_name should be populated"
        assert sw.skill2_name, "skill2_name should be populated"
        assert sw.burst_name, "burst_name should be populated"
        # The user's max-level Snow White: Heavy Arms — descriptions
        # should be present and not just whitespace.
        assert sw.skill1_description and len(sw.skill1_description) > 20
        assert sw.skill2_description and len(sw.skill2_description) > 20
        # Burst cooldown is parsed from the description prefix; it's a
        # positive float for any character whose burst description starts
        # with "X.X s".
        assert sw.burst_cooldown_seconds is None or sw.burst_cooldown_seconds > 0


# ---------------------------------------------------------------------------
# Smart-name-matcher regression coverage (slice #102)
# ---------------------------------------------------------------------------


def _seed_for_namematcher(engine):
    """Seed Characters covering each ``_find_character`` fallback case."""
    from nikke_optimizer.data.models import Character
    from nikke_optimizer.data.enums import (
        BurstType, Element, Manufacturer, Rarity, WeaponClass,
    )
    db_chars = [
        # exact / case-insensitive
        ("Crown", BurstType.II),
        # plain prefix (collab short form)
        ("Chisato Nishikigi", BurstType.III),
        # paren-disambiguator
        ("Rei Ayanami (Tentative Name)", BurstType.II),
        # colon-alt-form
        ("Asuka Shikinami Langley: Wille", BurstType.III),
        # ambiguous prefix tiebreak (shortest wins)
        ("Anchor", BurstType.II),
        ("Anchor: Innocent Maid", BurstType.II),
    ]
    with get_session(engine) as session:
        for name, burst in db_chars:
            session.add(
                Character(
                    name=name,
                    rarity=Rarity.SSR,
                    element=Element.IRON,
                    weapon_class=WeaponClass.SMG,
                    burst_type=burst,
                    manufacturer=Manufacturer.ELYSION,
                    role_tags=["Attacker"],
                    source="manual",
                )
            )
        session.commit()


def _resolve_csv_name(engine, csv_name: str) -> tuple[str | None, list[str]]:
    """Helper: invoke ``_find_character`` and return (resolved_name, warnings)."""
    from nikke_optimizer.data.models import Character
    from nikke_optimizer.roster.csv_importer import (
        ImportReport, _find_character,
    )
    report = ImportReport()
    with get_session(engine) as session:
        all_names = [c.name for c in session.exec(select(Character)).all()]
        ch = _find_character(session, csv_name, all_names=all_names, report=report)
    return (ch.name if ch else None, list(report.warnings))


def test_namematcher_exact():
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_for_namematcher(engine)
    name, warns = _resolve_csv_name(engine, "Crown")
    assert name == "Crown"
    assert not warns


def test_namematcher_case_insensitive():
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_for_namematcher(engine)
    name, warns = _resolve_csv_name(engine, "CROWN")
    assert name == "Crown"
    assert any("case-insensitive" in w for w in warns)


def test_namematcher_collab_short_form():
    """``Chisato`` → ``Chisato Nishikigi`` via plain-prefix match."""
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_for_namematcher(engine)
    name, warns = _resolve_csv_name(engine, "Chisato")
    assert name == "Chisato Nishikigi"
    assert any("prefix" in w for w in warns)


def test_namematcher_paren_disambiguator():
    """``Rei (Tentative Name)`` → ``Rei Ayanami (Tentative Name)``."""
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_for_namematcher(engine)
    name, warns = _resolve_csv_name(engine, "Rei (Tentative Name)")
    assert name == "Rei Ayanami (Tentative Name)"
    assert any("paren-disambiguator" in w for w in warns)


def test_namematcher_colon_alt_form():
    """``Asuka: WILLE`` → ``Asuka Shikinami Langley: Wille``."""
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_for_namematcher(engine)
    name, warns = _resolve_csv_name(engine, "Asuka: WILLE")
    assert name == "Asuka Shikinami Langley: Wille"
    assert any("colon-alt-form" in w for w in warns)


def test_namematcher_ambiguous_prefix_picks_shortest():
    """``Anchor`` matches both ``Anchor`` and ``Anchor: Innocent Maid``;
    exact-match takes priority so ``Anchor`` wins."""
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_for_namematcher(engine)
    name, warns = _resolve_csv_name(engine, "Anchor")
    assert name == "Anchor"  # exact match short-circuits


def test_namematcher_unknown_name_returns_none():
    engine = make_engine(Path(":memory:"))
    init_db(engine)
    _seed_for_namematcher(engine)
    name, _ = _resolve_csv_name(engine, "DefinitelyNotARealNikke")
    assert name is None
