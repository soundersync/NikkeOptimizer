"""Smoke tests for the static character DB + roster persistence schema."""

from pathlib import Path

from sqlmodel import select

from nikke_optimizer.data.db import get_session, init_db, make_engine
from nikke_optimizer.data.enums import (
    BurstType,
    Element,
    OLBonusType,
    OLGearSlot,
    Rarity,
    WeaponClass,
)
from nikke_optimizer.data.models import (
    ArenaMatch,
    BuffSummaryLine,
    Character,
    Cube,
    OLGear,
    OLGearBonus,
    OwnedCharacter,
)


def test_owned_character_with_ol_gear_and_bonuses():
    engine = make_engine(Path(":memory:"))
    init_db(engine)

    with get_session(engine) as session:
        char = Character(
            name="Snow White: Heavy Arms",
            rarity=Rarity.SSR,
            element=Element.IRON,
            weapon_class=WeaponClass.MG,
            burst_type=BurstType.III,
            role_tags=["Attacker"],
            source="manual",
        )
        session.add(char)
        session.commit()
        session.refresh(char)

        owned = OwnedCharacter(
            character_id=char.id,
            sync_level=652,
            limit_break=3,
            star_count=3,
            phase=15,
            skill1_level=10,
            skill2_level=10,
            burst_skill_level=10,
            power=526580,
            total_hp=9324296,
            total_atk=405583,
            total_def=53623,
        )
        gear1 = OLGear(slot=OLGearSlot.HEAD, base_hp=73772, base_atk=9021)
        gear1.bonuses = [
            OLGearBonus(
                bonus_type=OLBonusType.ELEMENT_DAMAGE,
                raw_label="Increase Element Damage Dealt",
                percent=27.16,
                highlighted=False,
            ),
            OLGearBonus(
                bonus_type=OLBonusType.HIT_RATE,
                raw_label="Increase Hit Rate",
                percent=8.29,
                highlighted=False,
            ),
            OLGearBonus(
                bonus_type=OLBonusType.ATK,
                raw_label="Increase ATK",
                percent=14.83,
                highlighted=True,
            ),
        ]
        owned.ol_gear = [gear1]
        owned.buff_summary = [
            BuffSummaryLine(
                bonus_type=OLBonusType.ELEMENT_DAMAGE,
                raw_label="Increase Element Damage Dealt",
                percent=95.62,
                highlighted=True,
            ),
        ]
        session.add(owned)
        session.commit()
        session.refresh(owned)

        roundtrip = session.exec(
            select(OwnedCharacter).where(OwnedCharacter.id == owned.id)
        ).one()
        assert roundtrip.power == 526580
        assert roundtrip.phase == 15
        assert len(roundtrip.ol_gear) == 1
        gear = roundtrip.ol_gear[0]
        assert gear.base_hp == 73772
        assert gear.base_atk == 9021
        assert len(gear.bonuses) == 3
        active = [b for b in gear.bonuses if b.highlighted]
        assert {b.bonus_type for b in active} == {OLBonusType.ATK}
        assert len(roundtrip.buff_summary) == 1


def test_cube_persistence():
    engine = make_engine(Path(":memory:"))
    init_db(engine)

    with get_session(engine) as session:
        session.add(
            Cube(
                name="Assault Cube",
                level=7,
                atk=0,
                hp=0,
                def_=0,
                equipping_count_equipped=4,
                equipping_count_owned=4,
            )
        )
        session.add(
            Cube(
                name="Resilience Cube",
                level=15,
                atk=2783,
                hp=11366,
                def_=552,
                equipping_count_equipped=12,
                equipping_count_owned=12,
            )
        )
        session.commit()

        cubes = session.exec(select(Cube)).all()
        assert len(cubes) == 2
        names = {c.name for c in cubes}
        assert names == {"Assault Cube", "Resilience Cube"}
        resilience = session.exec(
            select(Cube).where(Cube.name == "Resilience Cube")
        ).one()
        assert resilience.level == 15
        assert resilience.equipping_count_owned == 12


def test_arena_match_fixture():
    engine = make_engine(Path(":memory:"))
    init_db(engine)

    with get_session(engine) as session:
        match = ArenaMatch(
            mode="rookie",
            user_username="NIKA",
            opponent_username="WINTER",
            user_team=["Snow White: Heavy Arms", "Blanc", "Little Mermaid", "Centi", "Jackal"],
            opponent_team=["Noah", "Noise", "Scarlet: Black Shadow", "Helm", "Biscuit"],
            user_power=2134760,
            opponent_power=1885854,
            user_role="attack",
            outcome="win",
            raw_battle_record={"NIKA": {"Snow White: Heavy Arms": {"damage_dealt": 1234567}}},
        )
        session.add(match)
        session.commit()

        m = session.exec(select(ArenaMatch).where(ArenaMatch.mode == "rookie")).one()
        assert m.outcome == "win"
        assert len(m.user_team) == 5
        assert m.raw_battle_record["NIKA"]["Snow White: Heavy Arms"]["damage_dealt"] == 1234567


def test_unique_character_name():
    engine = make_engine(Path(":memory:"))
    init_db(engine)

    with get_session(engine) as session:
        session.add(
            Character(
                name="Liter",
                rarity=Rarity.SSR,
                element=Element.IRON,
                weapon_class=WeaponClass.SMG,
                burst_type=BurstType.I,
            )
        )
        session.commit()

        session.add(
            Character(
                name="Liter",
                rarity=Rarity.SSR,
                element=Element.IRON,
                weapon_class=WeaponClass.SMG,
                burst_type=BurstType.I,
            )
        )
        try:
            session.commit()
        except Exception:
            session.rollback()
            return
        raise AssertionError("expected unique constraint violation on Character.name")
