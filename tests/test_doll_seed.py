"""Tests for the Doll catalog seeder.

Validates the user's two ground-truth examples:
  - AR-SR Phase 15 ("Cooking Commander Doll Ltd."):
      Skill 1 = Damage to core ▲ 17.04%, DEF ▲ 37%
      Skill 2 = Damage Taken ▼ 17%, Cover Max HP ▲ 30% ("Grounding Pillar")
  - RL-SR Phase 1 ("Exercising Commander Doll Ltd."):
      Skill 1 = Charge Damage Multiplier ▲ 1.58%, DEF ▲ 25%

Plus structural invariants: every (doll, skill, phase) row is unique;
R-rarity dolls have exactly 1 skill; SR dolls have exactly 2; phases
1/15 are flagged interpolated=False (verbatim from checkpoints) while
intermediate phases are flagged interpolated=True.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlmodel")

from sqlmodel import select

from nikke_optimizer.data.db import get_session, init_db, make_engine
from nikke_optimizer.data.doll_seed import (
    expand_skill_phases,
    interpolate_phase,
    seed_dolls,
)
from nikke_optimizer.data.enums import Rarity, WeaponClass
from nikke_optimizer.data.models import Doll, DollSkill, DollSkillPhase


@pytest.fixture
def session():
    engine = make_engine(db_path=None) if False else make_engine_in_memory()
    init_db(engine)
    with get_session(engine) as s:
        yield s


def make_engine_in_memory():
    from pathlib import Path

    return make_engine(Path(":memory:"))


def _effects_by_stat(effects: list[dict]) -> dict[str, float]:
    return {e["stat"]: e["magnitude"] for e in effects}


# --- user-validated examples ----------------------------------------------


def test_ar_sr_phase15_matches_user_capture(session):
    """AR-SR Phase 15: Skill 1 = Core Damage 17.04% + DEF 37%; Skill 2 = -17%/+30%."""
    seed_dolls(session)

    doll = session.exec(
        select(Doll)
        .where(Doll.weapon_class == WeaponClass.AR)
        .where(Doll.rarity == Rarity.SR)
    ).one()
    assert doll.name == "Cooking Commander Doll Ltd."

    skills = session.exec(
        select(DollSkill).where(DollSkill.doll_id == doll.id).order_by(DollSkill.skill_index)
    ).all()
    assert len(skills) == 2
    assert skills[0].name == "Gaze of Courage"
    assert skills[1].name == "Grounding Pillar"

    # Skill 1 Phase 15 — verbatim user values.
    s1_p15 = session.exec(
        select(DollSkillPhase)
        .where(DollSkillPhase.skill_id == skills[0].id)
        .where(DollSkillPhase.phase == 15)
    ).one()
    eff = _effects_by_stat(s1_p15.effects)
    assert eff["Damage dealt when attacking core"] == pytest.approx(17.04)
    assert eff["DEF"] == pytest.approx(37.0)
    assert s1_p15.interpolated is False

    # Skill 2 (Grounding Pillar) Phase 15.
    s2_p15 = session.exec(
        select(DollSkillPhase)
        .where(DollSkillPhase.skill_id == skills[1].id)
        .where(DollSkillPhase.phase == 15)
    ).one()
    eff = _effects_by_stat(s2_p15.effects)
    assert eff["Damage Taken"] == pytest.approx(17.0)
    assert eff["Max HP of Cover"] == pytest.approx(30.0)
    assert s2_p15.interpolated is False


def test_rl_sr_phase1_matches_user_capture(session):
    """RL-SR Phase 1: Charge Damage Mult ▲ 1.58%, DEF ▲ 25%."""
    seed_dolls(session)

    doll = session.exec(
        select(Doll)
        .where(Doll.weapon_class == WeaponClass.RL)
        .where(Doll.rarity == Rarity.SR)
    ).one()
    assert doll.name == "Exercising Commander Doll Ltd."

    skill = session.exec(
        select(DollSkill)
        .where(DollSkill.doll_id == doll.id)
        .where(DollSkill.skill_index == 1)
    ).one()
    p1 = session.exec(
        select(DollSkillPhase)
        .where(DollSkillPhase.skill_id == skill.id)
        .where(DollSkillPhase.phase == 1)
    ).one()
    eff = _effects_by_stat(p1.effects)
    assert eff["Charge Damage Multiplier"] == pytest.approx(1.58)
    assert eff["DEF"] == pytest.approx(25.0)
    assert p1.interpolated is False


# --- structural invariants ------------------------------------------------


def test_seed_counts_are_consistent(session):
    """6 weapon classes × {R, SR} = 12 dolls; SR has 2 skills, R has 1; phases match."""
    counts = seed_dolls(session)
    assert counts["dolls"] == 12
    assert counts["skills"] == 6 * 2 + 6 * 1  # SR (2 skills) + R (1 skill) per weapon

    # Per-doll structural checks.
    dolls = session.exec(select(Doll)).all()
    n_phase_rows_expected = 0
    for doll in dolls:
        skills = session.exec(
            select(DollSkill).where(DollSkill.doll_id == doll.id)
        ).all()
        if doll.rarity == Rarity.R:
            assert len(skills) == 1
            assert doll.max_phase == 5
            n_phase_rows_expected += 5  # skill 1 only, phases 1..5
        else:
            assert len(skills) == 2
            assert doll.max_phase == 15
            n_phase_rows_expected += 15  # skill 1, phases 1..15
            n_phase_rows_expected += 10  # skill 2 (Grounding Pillar), phases 6..15
    assert counts["phases"] == n_phase_rows_expected


def test_phases_2_through_14_are_marked_interpolated(session):
    """Verify intermediate phases are flagged interpolated=True; checkpoints are not."""
    seed_dolls(session)
    skill = session.exec(
        select(DollSkill)
        .join(Doll, DollSkill.doll_id == Doll.id)
        .where(Doll.weapon_class == WeaponClass.RL)
        .where(Doll.rarity == Rarity.SR)
        .where(DollSkill.skill_index == 1)
    ).one()
    phases = session.exec(
        select(DollSkillPhase)
        .where(DollSkillPhase.skill_id == skill.id)
        .order_by(DollSkillPhase.phase)
    ).all()
    by_phase = {p.phase: p for p in phases}
    assert by_phase[1].interpolated is False  # checkpoint
    assert by_phase[15].interpolated is False  # checkpoint
    for p in (2, 3, 5, 8, 10, 12, 14):
        assert by_phase[p].interpolated is True, f"phase {p} should be interpolated"


def test_linear_interp_midpoint_is_average_of_checkpoints():
    """Phase 8 is exactly the midpoint between phase 1 and 15 — values average."""
    checkpoints = {
        1: [{"stat": "X", "magnitude": 1.58}, {"stat": "DEF", "magnitude": 25.0}],
        15: [{"stat": "X", "magnitude": 9.47}, {"stat": "DEF", "magnitude": 37.0}],
    }
    effects, interp = interpolate_phase(8, checkpoints)
    by_stat = _effects_by_stat(effects)
    # (1.58 + 9.47) / 2 = 5.525, (25 + 37) / 2 = 31.0
    assert by_stat["X"] == pytest.approx(5.525, rel=1e-3)
    assert by_stat["DEF"] == pytest.approx(31.0, rel=1e-3)
    assert interp is True


def test_interpolation_at_checkpoint_returns_verbatim():
    checkpoints = {
        1: [{"stat": "X", "magnitude": 1.58}],
        15: [{"stat": "X", "magnitude": 9.47}],
    }
    effects, interp = interpolate_phase(15, checkpoints)
    assert interp is False
    assert effects[0]["magnitude"] == 9.47


def test_grounding_pillar_skipped_below_phase_6():
    """Skill 2 unlocks at phase 6 — no rows for phase < 6."""
    skill_spec = {
        "skill_index": 2,
        "name": "Grounding Pillar",
        "trigger": "Activates at the start of the battle.",
        "checkpoints": {
            6: [{"stat": "Damage Taken", "magnitude": 6.0}],
            15: [{"stat": "Damage Taken", "magnitude": 17.0}],
        },
    }
    rows = expand_skill_phases(skill_spec, max_phase=15)
    phases = [r[0] for r in rows]
    assert phases == list(range(6, 16))
    assert all(r[2] is False for r in rows if r[0] in (6, 15))


def test_lookup_phase_returns_none_for_ssr(session):
    """SSR is the Treasure tier, not in the doll catalog."""
    from nikke_optimizer.data.doll_seed import lookup_phase

    seed_dolls(session)
    result = lookup_phase(
        session,
        weapon_class="AR",
        rarity="SSR",  # not a doll
        skill_index=1,
        phase=15,
    )
    assert result is None
