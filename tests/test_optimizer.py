"""Tests for the Phase-2 heuristic optimizer."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlmodel import select

from nikke_optimizer.data.db import get_session, init_db, make_engine
from nikke_optimizer.data.enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)
from nikke_optimizer.data.models import Character, OwnedCharacter
from nikke_optimizer.optimizer.constraints import (
    DEFAULT_MIN_SKILL_SUM,
    effective_min_skill_sum,
    has_burst_chain,
    has_minimum_investment,
    has_unique_members,
    is_correct_size,
    is_valid_team,
)
from nikke_optimizer.optimizer.loader import filter_eligible, load_owned
from nikke_optimizer.optimizer.models import CharacterView
from nikke_optimizer.optimizer.scoring import DEFAULT_WEIGHTS, score_team
from nikke_optimizer.optimizer.search import beam_search_top_teams, local_search_improve
from nikke_optimizer.optimizer.rookie import recommend_rookie


def _view(name: str, burst: BurstType, element: Element = Element.IRON, power: int = 100_000) -> CharacterView:
    """Tiny factory for synthetic views in unit tests."""
    return CharacterView(
        name=name,
        rarity=Rarity.SSR,
        element=element,
        weapon_class=WeaponClass.AR,
        burst_type=burst,
        manufacturer=Manufacturer.ELYSION,
        role_tags=("Main DPS",),
        owned=True,
        power=power,
        skill1_level=10,
        skill2_level=10,
        burst_skill_level=10,
    )


# ------------------------- constraints ----------------------------


def test_burst_chain_valid_2_1_2():
    team = [
        _view("A", BurstType.I),
        _view("B", BurstType.I),
        _view("C", BurstType.II),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert has_burst_chain(team)


def test_burst_chain_valid_1_1_3():
    team = [
        _view("A", BurstType.I),
        _view("B", BurstType.II),
        _view("C", BurstType.III),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert has_burst_chain(team)


def test_burst_chain_invalid_no_b1():
    team = [
        _view("A", BurstType.II),
        _view("B", BurstType.II),
        _view("C", BurstType.III),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert not has_burst_chain(team)


def test_burst_chain_flex_fills_gap():
    """A FLEX burst character can substitute for whichever bucket is short."""
    team = [
        _view("A", BurstType.FLEX),
        _view("B", BurstType.II),
        _view("C", BurstType.III),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert has_burst_chain(team)


def test_unique_members_dedup():
    a = _view("A", BurstType.I)
    assert not has_unique_members([a, a, _view("C", BurstType.II), _view("D", BurstType.III), _view("E", BurstType.III)])


def test_is_correct_size():
    team = [_view(f"X{i}", BurstType.I) for i in range(5)]
    assert is_correct_size(team)
    assert not is_correct_size(team[:4])


# ------------------------- investment floor ----------------------------


def _undertrained(view: CharacterView, *, skill_each: int = 1) -> CharacterView:
    """Return a copy with all three skills set to ``skill_each``."""
    return replace(
        view,
        skill1_level=skill_each,
        skill2_level=skill_each,
        burst_skill_level=skill_each,
    )


def test_has_minimum_investment_passes_for_built_team():
    """A team where every member meets the floor passes the check."""
    team = [
        _view("A", BurstType.I),
        _view("B", BurstType.I),
        _view("C", BurstType.II),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert has_minimum_investment(team)


def test_has_minimum_investment_vetos_undertrained_member():
    """Even one undertrained member (1/1/1) vetos the team."""
    team = [
        _view("A", BurstType.I),
        _undertrained(_view("Rapunzel: Pure Grace", BurstType.I)),
        _view("C", BurstType.II),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert not has_minimum_investment(team)


def test_is_valid_team_runs_minimum_investment_by_default():
    """Live-testing repro: undertrained member should be rejected by the
    full validity check, not just the lower-level constraint."""
    team = [
        _view("A", BurstType.I),
        _undertrained(_view("Dolla", BurstType.I), skill_each=4),  # 4/4/4 = 12 < 18
        _view("C", BurstType.II),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert not is_valid_team(team)
    # And the scorer drops it before the breakdown is built.
    assert score_team(team) is None


def test_is_valid_team_can_disable_floor_for_explainer_mode():
    team = [
        _view("A", BurstType.I),
        _undertrained(_view("Rapunzel: Pure Grace", BurstType.I)),
        _view("C", BurstType.II),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert is_valid_team(team, enforce_minimum_investment=False)


def test_effective_min_skill_sum_default():
    """No env override → DEFAULT_MIN_SKILL_SUM."""
    assert effective_min_skill_sum() == DEFAULT_MIN_SKILL_SUM


def test_effective_min_skill_sum_env_override(monkeypatch):
    """Env override flows into the floor read by call sites."""
    monkeypatch.setenv("NIKKE_OPTIMIZER_MIN_SKILL_SUM", "9")
    assert effective_min_skill_sum() == 9
    # And a 4/4/4 member (sum 12) now passes.
    team = [
        _view("A", BurstType.I),
        _undertrained(_view("Dolla", BurstType.I), skill_each=4),
        _view("C", BurstType.II),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert has_minimum_investment(team, min_skill_sum=effective_min_skill_sum())


def test_effective_min_skill_sum_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("NIKKE_OPTIMIZER_MIN_SKILL_SUM", "not-an-int")
    assert effective_min_skill_sum() == DEFAULT_MIN_SKILL_SUM


def test_effective_min_skill_sum_zero_disables_floor(monkeypatch):
    """Power-user escape hatch: ``=0`` disables the veto entirely."""
    monkeypatch.setenv("NIKKE_OPTIMIZER_MIN_SKILL_SUM", "0")
    team = [
        _view("A", BurstType.I),
        _undertrained(_view("Rapunzel: Pure Grace", BurstType.I)),
        _view("C", BurstType.II),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert is_valid_team(team, min_skill_sum=effective_min_skill_sum())


# ------------------------- scoring ----------------------------


def _balanced_team() -> list[CharacterView]:
    return [
        _view("Liter", BurstType.I, Element.WIND),
        _view("Crown", BurstType.II, Element.IRON),
        _view("Red Hood", BurstType.III, Element.IRON),
        _view("Modernia", BurstType.III, Element.ELECTRIC),
        _view("Snow White: Heavy Arms", BurstType.I, Element.IRON),
    ]


def test_score_team_returns_breakdown():
    cand = score_team(_balanced_team())
    assert cand is not None
    assert cand.score > 0
    breakdown = cand.breakdown.to_dict()
    assert breakdown["total"] == pytest.approx(cand.score)
    # The synergy table includes Liter+Red Hood and Crown+Red Hood pairs.
    assert breakdown["synergy_pairs"] > 0


def test_score_team_rejects_invalid_burst_chain():
    team = [
        _view("A", BurstType.II),
        _view("B", BurstType.II),
        _view("C", BurstType.III),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    assert score_team(team) is None


def test_synergy_bonus_increases_score():
    plain = [
        _view("A", BurstType.I),
        _view("B", BurstType.II),
        _view("C", BurstType.III),
        _view("D", BurstType.III),
        _view("E", BurstType.III),
    ]
    synergy_team = list(plain)
    synergy_team[0] = _view("Crown", BurstType.II)
    synergy_team[1] = _view("Red Hood", BurstType.III)
    synergy_team[2] = _view("Liter", BurstType.I)
    plain_score = score_team(plain)
    syn_score = score_team(synergy_team)
    assert plain_score is not None
    assert syn_score is not None
    assert syn_score.score > plain_score.score


# ------------------------- search ----------------------------


def test_beam_search_returns_valid_top_k():
    pool = [
        _view("Liter", BurstType.I),
        _view("Dorothy", BurstType.II),
        _view("Crown", BurstType.II),
        _view("Naga", BurstType.II),
        _view("Tia", BurstType.I),
        _view("Red Hood", BurstType.III),
        _view("Modernia", BurstType.III),
        _view("Scarlet: Black Shadow", BurstType.III),
        _view("Snow White: Heavy Arms", BurstType.I),
        _view("Asuka Shikinami Langley", BurstType.III),
    ]
    teams = beam_search_top_teams(pool, top_k=3, beam_width=50)
    assert len(teams) == 3
    for t in teams:
        assert len(t.members) == 5
        assert t.score > 0


def test_local_search_does_not_regress():
    pool = [
        _view("Liter", BurstType.I, power=200_000),
        _view("Dorothy", BurstType.II, power=180_000),
        _view("Crown", BurstType.II, power=190_000),
        _view("Red Hood", BurstType.III, power=200_000),
        _view("Modernia", BurstType.III, power=180_000),
        _view("Scarlet: Black Shadow", BurstType.III, power=180_000),
        _view("Snow White: Heavy Arms", BurstType.I, power=190_000),
        _view("Asuka Shikinami Langley", BurstType.III, power=170_000),
        _view("Tia", BurstType.I, power=120_000),
        _view("Naga", BurstType.II, power=140_000),
    ]
    teams = beam_search_top_teams(pool, top_k=1, beam_width=30)
    initial = teams[0]
    polished = local_search_improve(initial, pool)
    assert polished.score >= initial.score


# ------------------------- end-to-end against real DB ----------------------------


def _real_db_engine():
    p = Path("/tmp/nikke_test.sqlite3")
    if not p.exists():
        pytest.skip("/tmp/nikke_test.sqlite3 not found; rebuild the dev DB first")
    engine = make_engine(p)
    init_db(engine)
    with get_session(engine) as s:
        chars = len(s.exec(select(Character)).all())
        owned = len(s.exec(select(OwnedCharacter)).all())
        if chars < 100 or owned < 50:
            pytest.skip(f"DB underpopulated (chars={chars}, owned={owned})")
    return engine


def test_route_treasure_forms_substitutes_when_unlocked(tmp_path, monkeypatch):
    """``_route_treasure_forms`` swaps base name → ``<name> (Treasure)``
    when the user's roster shows SSR rarity + phase >= 1 AND the
    registry has the Treasure-form library entry."""
    from nikke_optimizer.simulator.evaluator import _route_treasure_forms

    db = tmp_path / "treasures.sqlite3"
    monkeypatch.setenv("NIKKE_OPTIMIZER_DB", str(db))
    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as s:
        # Seed: Helm with Treasure unlocked, Crown without.
        helm = Character(
            name="Helm", rarity=Rarity.SSR, element=Element.WATER,
            weapon_class=WeaponClass.SR, burst_type=BurstType.II,
        )
        crown = Character(
            name="Crown", rarity=Rarity.SSR, element=Element.IRON,
            weapon_class=WeaponClass.SMG, burst_type=BurstType.II,
        )
        s.add(helm)
        s.add(crown)
        s.commit()
        s.refresh(helm)
        s.refresh(crown)
        s.add(OwnedCharacter(
            character_id=helm.id,
            treasure_rarity="SSR", treasure_phase=3,
        ))
        s.add(OwnedCharacter(
            character_id=crown.id,
            treasure_rarity=None, treasure_phase=None,
        ))
        s.commit()
    out = _route_treasure_forms(["Helm", "Crown", "Unknown"])
    # Helm has Treasure unlocked + library has "Helm (Treasure)" → substituted.
    assert out[0] == "Helm (Treasure)"
    # Crown has no Treasure → stays.
    assert out[1] == "Crown"
    # Unknown char (not in DB) → falls through to base name.
    assert out[2] == "Unknown"


def test_route_treasure_forms_skips_when_no_treasure_form_in_registry(
    tmp_path, monkeypatch
):
    """When the registry doesn't have a ``(Treasure)`` library entry
    for the char, routing falls back to the base form even if the user
    has Treasure unlocked. Avoids None lookups in the registry."""
    from nikke_optimizer.simulator.evaluator import _route_treasure_forms

    db = tmp_path / "no-treasure-form.sqlite3"
    monkeypatch.setenv("NIKKE_OPTIMIZER_DB", str(db))
    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as s:
        # NotInRegistry has Treasure unlocked but no library entry.
        ch = Character(
            name="NotInRegistry", rarity=Rarity.SSR,
            element=Element.WATER, weapon_class=WeaponClass.SR,
            burst_type=BurstType.II,
        )
        s.add(ch)
        s.commit()
        s.refresh(ch)
        s.add(OwnedCharacter(
            character_id=ch.id,
            treasure_rarity="SSR", treasure_phase=3,
        ))
        s.commit()
    out = _route_treasure_forms(["NotInRegistry"])
    # No ``NotInRegistry (Treasure)`` in encoded library → stays as-is.
    assert out == ["NotInRegistry"]


def test_optimizer_context_caches_per_db_path(tmp_path):
    """``get_context`` returns the same ``OptimizerContext`` instance for
    repeated calls with the same DB path + mtime; rebuilds when mtime
    advances (simulating a CSV re-import)."""
    import os
    import time
    from nikke_optimizer.optimizer.loader import (
        get_context, invalidate_context_cache,
    )

    invalidate_context_cache()
    db_path = tmp_path / "ctx.sqlite3"
    engine = make_engine(db_path)
    init_db(engine)

    with get_session(engine) as s:
        c1 = get_context(s, db_path=db_path)
        c2 = get_context(s, db_path=db_path)
    assert c1 is c2  # cached

    # Bump the file's mtime — context should rebuild.
    new_mtime = time.time() + 5.0
    os.utime(db_path, (new_mtime, new_mtime))
    with get_session(engine) as s:
        c3 = get_context(s, db_path=db_path)
    assert c3 is not c1


def test_optimizer_context_no_path_means_no_cache(tmp_path):
    """No ``db_path`` → no caching (used by tests with in-memory engines)."""
    from nikke_optimizer.optimizer.loader import get_context, invalidate_context_cache

    invalidate_context_cache()
    db_path = tmp_path / "fresh.sqlite3"
    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as s:
        c1 = get_context(s)
        c2 = get_context(s)
    assert c1 is not c2  # both freshly built


def test_recommend_counter_accepts_context(tmp_path, monkeypatch):
    """Pre-supplied context skips DB load — exercised end-to-end."""
    from nikke_optimizer.optimizer.counter import recommend_counter
    from nikke_optimizer.optimizer.loader import OptimizerContext

    db_path = tmp_path / "rc.sqlite3"
    monkeypatch.setenv("NIKKE_OPTIMIZER_DB", str(db_path))
    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as s:
        # Seed an opponent (Crown) — empty roster so no recommendations,
        # but the path through _resolve_opponent must succeed.
        s.add(Character(
            name="Crown", rarity=Rarity.SSR, element=Element.IRON,
            weapon_class=WeaponClass.SMG, burst_type=BurstType.II,
        ))
        s.commit()
        ctx = OptimizerContext.from_session(s)
        rec = recommend_counter(s, ["Crown"], context=ctx)
    assert rec is not None
    assert len(rec.opponent.opponent_members) == 1
    assert rec.opponent.opponent_members[0].name == "Crown"


def test_load_owned_stats_returns_owned_totals(tmp_path, monkeypatch):
    """``_load_owned_stats`` pulls per-Nikke ATK/HP/DEF from OwnedCharacter
    into the dict consumed by ``evaluate_team``. Owned-with-stats →
    populated; unowned or stat-less → omitted."""
    from nikke_optimizer.simulator.evaluator import _load_owned_stats

    db_path = tmp_path / "stats.sqlite3"
    monkeypatch.setenv("NIKKE_OPTIMIZER_DB", str(db_path))
    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as s:
        crown_char = Character(
            name="Crown",
            rarity=Rarity.SSR,
            element=Element.IRON,
            weapon_class=WeaponClass.SMG,
            burst_type=BurstType.II,
        )
        liter_char = Character(
            name="Liter",
            rarity=Rarity.SSR,
            element=Element.WIND,
            weapon_class=WeaponClass.SMG,
            burst_type=BurstType.I,
        )
        unstated_char = Character(
            name="Drake",
            rarity=Rarity.SSR,
            element=Element.FIRE,
            weapon_class=WeaponClass.SMG,
            burst_type=BurstType.III,
        )
        s.add(crown_char)
        s.add(liter_char)
        s.add(unstated_char)
        s.commit()
        s.refresh(crown_char)
        s.refresh(liter_char)
        s.refresh(unstated_char)
        s.add(OwnedCharacter(
            character_id=crown_char.id,
            total_atk=222_000, total_hp=2_500_000, total_def=44_000,
            skill1_level=10, skill2_level=10, burst_skill_level=10,
        ))
        s.add(OwnedCharacter(
            character_id=liter_char.id,
            total_atk=180_000, total_hp=2_100_000, total_def=33_000,
            skill1_level=10, skill2_level=10, burst_skill_level=10,
        ))
        # Drake is owned but stat columns are None — should be omitted.
        s.add(OwnedCharacter(
            character_id=unstated_char.id,
            total_atk=None, total_hp=None, total_def=None,
            skill1_level=10, skill2_level=10, burst_skill_level=10,
        ))
        s.commit()

    stats = _load_owned_stats(["Crown", "Liter", "Drake", "Unowned"])
    assert stats["Crown"] == {"base_atk": 222_000, "base_hp": 2_500_000, "base_def": 44_000}
    assert stats["Liter"] == {"base_atk": 180_000, "base_hp": 2_100_000, "base_def": 33_000}
    assert "Drake" not in stats  # all-None stats → omitted
    assert "Unowned" not in stats  # not in DB → omitted


def test_load_owned_stats_returns_empty_dict_when_db_unavailable(monkeypatch):
    """No DB at the path → empty dict, no crash. Tests the defensive
    fallback that keeps simulator-only tests passing without a DB."""
    from nikke_optimizer.simulator.evaluator import _load_owned_stats

    monkeypatch.setenv("NIKKE_OPTIMIZER_DB", "/nonexistent/path/no.sqlite3")
    assert _load_owned_stats(["Crown", "Liter"]) == {}


def test_loader_loads_owned_views():
    engine = _real_db_engine()
    with get_session(engine) as session:
        views = load_owned(session)
    assert len(views) >= 50
    assert all(v.owned for v in views)
    high_power = [v for v in views if v.power > 100_000]
    assert high_power, "expected at least one high-power character"


def test_loader_filter_eligible_min_power():
    engine = _real_db_engine()
    with get_session(engine) as session:
        views = load_owned(session)
    full = filter_eligible(views, min_power=0)
    over = filter_eligible(views, min_power=200_000)
    assert len(full) > len(over)


def test_element_advantage_table():
    from nikke_optimizer.optimizer.counter import has_element_advantage

    # Cycle: Fire > Wind > Iron > Electric > Water > Fire
    assert has_element_advantage(Element.FIRE, Element.WIND)
    assert has_element_advantage(Element.WIND, Element.IRON)
    assert has_element_advantage(Element.IRON, Element.ELECTRIC)
    assert has_element_advantage(Element.ELECTRIC, Element.WATER)
    assert has_element_advantage(Element.WATER, Element.FIRE)
    # No advantage between non-adjacent (e.g. Fire vs Iron — Iron is two
    # steps from Fire on the wheel).
    assert not has_element_advantage(Element.FIRE, Element.IRON)
    # No self-advantage.
    assert not has_element_advantage(Element.FIRE, Element.FIRE)


def test_element_coverage_counts_covered_opponent_elements():
    """``element_coverage`` returns (covered, distinct) where covered
    is the count of opponent elements at least one team member has
    advantage over."""
    from nikke_optimizer.optimizer.counter import element_coverage

    # Opponent: 3 distinct elements (Wind, Iron, Electric).
    opp = [
        _view("W1", BurstType.II, Element.WIND),
        _view("W2", BurstType.II, Element.WIND),
        _view("I1", BurstType.II, Element.IRON),
        _view("E1", BurstType.III, Element.ELECTRIC),
        _view("E2", BurstType.III, Element.ELECTRIC),
    ]
    # My team: Fire (counters Wind), Wind (counters Iron), unrelated.
    me = [
        _view("M1", BurstType.I, Element.FIRE),
        _view("M2", BurstType.I, Element.WIND),
        _view("M3", BurstType.II, Element.WATER),  # counters Fire — not present
        _view("M4", BurstType.III, Element.WATER),
        _view("M5", BurstType.III, Element.WATER),
    ]
    covered, distinct = element_coverage(me, opp)
    assert distinct == 3  # Wind, Iron, Electric
    assert covered == 2  # Wind (covered by Fire) + Iron (covered by Wind)


def test_score_counter_adds_element_bonus():
    from nikke_optimizer.optimizer.counter import CounterContext, score_counter

    fire_team = [
        _view("F1", BurstType.I, Element.FIRE),
        _view("F2", BurstType.II, Element.FIRE),
        _view("F3", BurstType.III, Element.FIRE),
        _view("F4", BurstType.III, Element.FIRE),
        _view("F5", BurstType.III, Element.FIRE),
    ]
    # Opponent runs all-Wind — Fire team should be heavily favored.
    wind_opp = CounterContext(
        opponent_members=tuple(
            _view(f"W{i}", BurstType.II, Element.WIND) for i in range(5)
        )
    )
    favored = score_counter(fire_team, wind_opp)
    assert favored is not None

    # Same team vs all-Water (Water counters Fire) — no Fire→Water bonus.
    water_opp = CounterContext(
        opponent_members=tuple(
            _view(f"X{i}", BurstType.II, Element.WATER) for i in range(5)
        )
    )
    unfavored = score_counter(fire_team, water_opp)
    assert unfavored is not None

    # Favored matchup must score higher.
    assert favored.score > unfavored.score
    # Unfavored should still pass burst-chain (it's the same team).
    assert unfavored.breakdown.burst_feasibility == 1.0


def test_recommend_counter_end_to_end():
    """Counter-pick on the actual rookie capture stored in the dev DB."""
    from sqlmodel import select
    from nikke_optimizer.data.models import ArenaMatch
    from nikke_optimizer.optimizer.counter import recommend_counter

    engine = _real_db_engine()
    with get_session(engine) as session:
        cap = session.exec(
            select(ArenaMatch).where(ArenaMatch.mode == "rookie")
        ).first()
        if cap is None or not cap.opponent_team:
            pytest.skip("no rookie capture with opponent_team in dev DB")
        opp_names = [n for n in cap.opponent_team if n]
        rec = recommend_counter(
            session, opp_names, top_k=3, beam_width=80, min_power=100_000
        )

    assert rec.opponent.opponent_members, "opponent must resolve at least one character"
    assert len(rec.teams) >= 1
    for t in rec.teams:
        assert len(t.members) == 5
        assert t.score > 0


def test_compute_coverage_perfect():
    from nikke_optimizer.optimizer.coverage import compute_coverage

    # Build 5 teams, one for each element. Every element should be covered.
    teams = []
    for elem in (Element.FIRE, Element.WATER, Element.WIND, Element.IRON, Element.ELECTRIC):
        team = [
            _view(f"{elem.value}1", BurstType.I, elem),
            _view(f"{elem.value}2", BurstType.II, elem),
            _view(f"{elem.value}3", BurstType.III, elem),
            _view(f"{elem.value}4", BurstType.III, elem),
            _view(f"{elem.value}5", BurstType.III, elem),
        ]
        cand = score_team(team)
        assert cand is not None
        teams.append(cand)
    cov = compute_coverage(teams)
    assert cov.element_coverage == 5
    assert cov.uncovered_opposing_elements == []


def test_compute_coverage_uncovered():
    from nikke_optimizer.optimizer.coverage import compute_coverage

    # All 5 teams are pure Fire — Fire counters Wind, so Wind is covered, but
    # the other 4 elements (Water counters Fire, etc.) aren't.
    teams = []
    for i in range(2):
        team = [
            _view(f"F{i}1", BurstType.I, Element.FIRE),
            _view(f"F{i}2", BurstType.II, Element.FIRE),
            _view(f"F{i}3", BurstType.III, Element.FIRE),
            _view(f"F{i}4", BurstType.III, Element.FIRE),
            _view(f"F{i}5", BurstType.III, Element.FIRE),
        ]
        cand = score_team(team)
        teams.append(cand)
    cov = compute_coverage(teams)
    # Fire only counters Wind — so 1 element covered, 4 uncovered.
    assert cov.element_coverage == 1
    assert Element.WIND in cov.covered_opposing_elements
    assert Element.FIRE in cov.uncovered_opposing_elements
    assert cov.notes  # should warn about uncovered elements


def test_recommend_champions_end_to_end():
    """Champions Arena returns 5 pairwise-disjoint teams (≤25 unique Nikkes)."""
    from nikke_optimizer.optimizer.champions import recommend_champions

    engine = _real_db_engine()
    with get_session(engine) as session:
        rec = recommend_champions(session, beam_width=80, min_power=100_000)

    # Some users won't have 25 eligible characters; assert what we have.
    assert 1 <= len(rec.teams) <= 5
    seen: set[str] = set()
    for team in rec.teams:
        names = [m.name for m in team.members]
        assert len(set(names)) == 5, f"within-team uniqueness: {names}"
        assert seen.isdisjoint(names), (
            f"champions teams must be disjoint; collision in {names}"
        )
        seen.update(names)
    # If pool is large enough, expect 5 teams.
    if len(rec.teams) < 5:
        # The solver should have explained why.
        assert rec.notes, "expected a note when fewer than 5 teams returned"


def test_recommend_sp_arena_end_to_end():
    """SP Arena returns 3 disjoint defense teams + 3 disjoint attack teams.

    Attack and defense are searched separately with role-specific weights,
    so the two lists may surface different Nikkes.
    """
    from nikke_optimizer.optimizer.sp_arena import recommend_sp_arena

    engine = _real_db_engine()
    with get_session(engine) as session:
        rec = recommend_sp_arena(session, beam_width=80, min_power=100_000)

    # Defense lineup: hard pairwise-disjoint (uniqueness is a game rule).
    # Attack lineup: MMR-diversified per slice #107 — overlap allowed in-game,
    # so we only require each team is internally unique + the 3 teams are
    # pairwise distinct compositions (no duplicate team).
    seen: set[str] = set()
    for team in rec.defense:
        names = [m.name for m in team.members]
        assert len(set(names)) == 5, f"defense team has duplicate members: {names}"
        assert seen.isdisjoint(names), (
            f"defense teams must be pairwise disjoint; collision in {names}"
        )
        seen.update(names)
    assert len(rec.defense) == 3
    # Attack: each team unique members, 3 distinct compositions.
    attack_sets = []
    for team in rec.attack:
        names = [m.name for m in team.members]
        assert len(set(names)) == 5, f"attack team has duplicate members: {names}"
        attack_sets.append(frozenset(names))
    assert len(rec.attack) == 3
    assert len(set(attack_sets)) == 3, "attack teams must be 3 distinct compositions"


def test_recommend_sp_counter_against_real_capture():
    """SP-counter on the real captured rookie defense should produce 3
    distinct round counters."""
    from sqlmodel import select
    from nikke_optimizer.data.models import ArenaMatch
    from nikke_optimizer.optimizer.sp_counter import recommend_sp_counter

    engine = _real_db_engine()
    with get_session(engine) as session:
        cap = session.exec(
            select(ArenaMatch).where(ArenaMatch.mode == "rookie")
        ).first()
        if cap is None or not cap.opponent_team:
            pytest.skip("no rookie capture with opponent_team")
        # Re-use the same capture's opponent team three times to simulate
        # 3 rounds — the search will return the SAME counter all three
        # times since defenses are identical, which is fine for testing.
        defenses = [
            [n for n in cap.opponent_team if n] for _ in range(3)
        ]
        rec = recommend_sp_counter(
            session, defenses, top_k=1, beam_width=80, min_power=100_000
        )
    assert len(rec.rounds) == 3
    for round_rec in rec.rounds:
        assert round_rec.opponent.opponent_members
        assert round_rec.teams, "each round must have at least one counter"
        team = round_rec.teams[0]
        assert len(team.members) == 5


def test_explain_character_existing():
    """Explain mode on a known character returns a valid team containing
    them and a finite score delta."""
    from nikke_optimizer.optimizer.explain import explain_character

    engine = _real_db_engine()
    with get_session(engine) as session:
        # Pick a character we know is in the roster — Helm is a canonical
        # defender.
        result = explain_character(
            session, "Helm", role="defense", beam_width=80, min_power=100_000
        )

    if result.best_with_target is None:
        pytest.skip("Helm not in dev roster")
    assert any(m.name == "Helm" for m in result.best_with_target.members)
    assert result.global_top is not None
    assert result.score_delta is not None
    # If Helm makes the global top defense team, delta is 0; otherwise
    # negative. Either way, finite.
    import math
    assert math.isfinite(result.score_delta)


def test_explain_character_not_found():
    """Explain mode on an unknown name returns no results."""
    from nikke_optimizer.optimizer.explain import explain_character

    engine = _real_db_engine()
    with get_session(engine) as session:
        result = explain_character(
            session, "NotARealCharacter12345", role="attack", min_power=100_000
        )
    assert result.best_with_target is None
    assert result.score_delta is None


def test_synergy_table_under_represented_count_below_threshold():
    """Regression guard against silent regressions in SYNERGY_PAIRS
    coverage. As we encode more characters, ensure at least N% of
    encoded chars have 2+ synergy pairs. Threshold is 'half', generous
    enough to allow encoding faster than synergy fills."""
    from nikke_optimizer.optimizer.scoring import SYNERGY_PAIRS
    from nikke_optimizer.optimizer.synergy_audit import audit_synergy_coverage
    from nikke_optimizer.simulator.registry import all_encoded_names

    encoded = all_encoded_names()
    report = audit_synergy_coverage(encoded, SYNERGY_PAIRS)
    under = len(report.under_represented)
    # Slice #132 — tightened threshold. We hit 0 under-represented in
    # slice #126; raising the bar so any new encoding either ships with
    # ≥2 synergy pairs or fails the test loudly. Tolerance of 5 so a
    # single PR adding 6 chars without pairs surfaces immediately.
    threshold = 5
    assert under <= threshold, (
        f"{under} of {len(encoded)} encoded chars have 0-1 synergy "
        f"pairs (threshold {threshold}). Add pairings to "
        f"SYNERGY_PAIRS in scoring.py for the most-frequently-fielded "
        f"missing chars: {report.under_represented[:10]}..."
    )


def test_synergy_pairs_contain_no_unknown_character_names():
    """Guard against typos in SYNERGY_PAIRS — every name in the table
    must resolve to a known DB character, or be on the explicit allowlist
    for hypothetical / unreleased chars."""
    from nikke_optimizer.optimizer.scoring import SYNERGY_PAIRS

    engine = _real_db_engine()
    with get_session(engine) as session:
        db_names = {c.name for c in session.exec(select(Character)).all()}

    # Names that may legitimately appear in SYNERGY_PAIRS without
    # being in the DB — e.g., chars added to the table in anticipation
    # of an upcoming release that wasn't scraped yet. Empty by default.
    allowlist: set[str] = set()

    unknown: set[str] = set()
    for pair in SYNERGY_PAIRS.keys():
        for name in pair:
            if name not in db_names and name not in allowlist:
                unknown.add(name)
    assert not unknown, (
        f"SYNERGY_PAIRS references {len(unknown)} character name(s) not in "
        f"the DB: {sorted(unknown)}. Likely typos; either fix the spelling "
        f"or add to the explicit allowlist."
    )


def test_synergy_audit_counts_pairs_per_character():
    """``audit_synergy_coverage`` returns the right per-character pair
    count and groups characters into tiers."""
    from nikke_optimizer.optimizer.synergy_audit import audit_synergy_coverage

    encoded = ["Crown", "Liter", "Red Hood", "Modernia", "Lonely"]
    pairs = {
        frozenset(("Crown", "Red Hood")): 8.0,
        frozenset(("Crown", "Modernia")): 7.0,
        frozenset(("Liter", "Red Hood")): 5.0,
        frozenset(("Liter", "Modernia")): 5.0,
        frozenset(("Crown", "NotEncoded")): 1.0,  # counts for Crown
        frozenset(("Modernia", "Modernia")): 0.0,  # ignored — bonus 0
    }
    report = audit_synergy_coverage(encoded, pairs)
    # Crown appears in 3 nonzero pairs (Red Hood, Modernia, NotEncoded).
    # Pairs with unencoded partners still count because the table entry
    # exists — useful for the maintainer auditing "are there gaps in
    # the synergy table I should fill?".
    assert report.counts["Crown"] == 3
    assert report.counts["Liter"] == 2
    assert report.counts["Red Hood"] == 2
    assert report.counts["Modernia"] == 2
    # Lonely has no entries.
    assert report.counts["Lonely"] == 0
    # Under-represented = 0 or 1 pairs.
    assert report.under_represented == ["Lonely"]


def test_select_diverse_top_k_zero_lambda_takes_top_scores():
    """``mmr_lambda=0`` means no diversity penalty — take top-K by score
    among distinct teams (dedup is always applied to avoid returning
    identical compositions multiple times)."""
    from nikke_optimizer.optimizer.search import select_diverse_top_k
    from nikke_optimizer.optimizer.models import ScoreBreakdown, TeamCandidate

    a = _view("A", BurstType.I); b = _view("B", BurstType.I)
    c = _view("C", BurstType.II); d = _view("D", BurstType.III)
    e = _view("E", BurstType.III)
    f = _view("F", BurstType.I); g = _view("G", BurstType.I)
    h = _view("H", BurstType.II); i = _view("I", BurstType.III)
    j = _view("J", BurstType.III)

    cand1 = TeamCandidate(
        members=(a, b, c, d, e), breakdown=ScoreBreakdown(total=20.0),
    )
    cand2 = TeamCandidate(
        members=(f, g, h, i, j), breakdown=ScoreBreakdown(total=18.0),
    )
    cand3 = TeamCandidate(
        members=(a, b, c, d, e), breakdown=ScoreBreakdown(total=15.0),
    )
    # cand3 is a duplicate of cand1 by member-set; should be deduped.
    out = select_diverse_top_k(
        [cand1, cand2, cand3], top_k=3, mmr_lambda=0.0
    )
    # Only 2 distinct teams exist after dedup.
    assert len(out) == 2
    assert [c.score for c in out] == [20.0, 18.0]


def test_select_diverse_top_k_high_lambda_prefers_disjoint():
    """High ``mmr_lambda`` should prefer a lower-score team if the
    higher-score team shares all members with one already chosen."""
    from nikke_optimizer.optimizer.search import select_diverse_top_k
    from nikke_optimizer.optimizer.models import ScoreBreakdown, TeamCandidate

    a = _view("A", BurstType.I); b = _view("B", BurstType.I)
    c = _view("C", BurstType.II); d = _view("D", BurstType.III)
    e = _view("E", BurstType.III)
    f = _view("F", BurstType.I); g = _view("G", BurstType.I)
    h = _view("H", BurstType.II); i = _view("I", BurstType.III)
    j = _view("J", BurstType.III)

    cand1 = TeamCandidate(  # team #1
        members=(a, b, c, d, e), breakdown=ScoreBreakdown(total=20.0),
    )
    cand2 = TeamCandidate(  # near-duplicate of cand1, slightly lower
        members=(a, b, c, d, e), breakdown=ScoreBreakdown(total=18.0),
    )
    cand3 = TeamCandidate(  # disjoint from cand1, but lower base score
        members=(f, g, h, i, j), breakdown=ScoreBreakdown(total=15.0),
    )
    out = select_diverse_top_k([cand1, cand2, cand3], top_k=2, mmr_lambda=10.0)
    # cand1 wins first; cand2 has 5 shared members → 18 - 50 = -32 mmr
    # cand3 has 0 shared → 15 mmr → wins #2.
    assert [c.members[0].name for c in out] == ["A", "F"]


def test_select_diverse_top_k_moderate_lambda_allows_partial_overlap():
    """λ=2.0: a team with 1 shared member at +5 over a disjoint team
    should still beat the disjoint one."""
    from nikke_optimizer.optimizer.search import select_diverse_top_k
    from nikke_optimizer.optimizer.models import ScoreBreakdown, TeamCandidate

    # Pre-build views so ScoringWeights validation isn't tripped on them.
    a = _view("A", BurstType.I); b = _view("B", BurstType.I)
    c = _view("C", BurstType.II); d = _view("D", BurstType.III)
    e = _view("E", BurstType.III)
    f = _view("F", BurstType.I); g = _view("G", BurstType.I)
    h = _view("H", BurstType.II); i = _view("I", BurstType.III)
    j = _view("J", BurstType.III)

    cand1 = TeamCandidate(
        members=(a, b, c, d, e), breakdown=ScoreBreakdown(total=20.0),
    )
    # Shares 1 member (a) with cand1, +5 base score over disjoint cand3.
    cand2 = TeamCandidate(
        members=(a, f, g, h, i), breakdown=ScoreBreakdown(total=20.0),
    )
    cand3 = TeamCandidate(
        members=(f, g, h, i, j), breakdown=ScoreBreakdown(total=15.0),
    )
    out = select_diverse_top_k(
        [cand1, cand2, cand3], top_k=2, mmr_lambda=2.0
    )
    # cand1 wins #1. cand2: 20 - 2.0*1 = 18 mmr. cand3: 15 mmr.
    # cand2 should still win #2 despite the overlap.
    assert out[0] is cand1
    assert out[1] is cand2


def test_recommend_rookie_end_to_end():
    engine = _real_db_engine()
    with get_session(engine) as session:
        rec = recommend_rookie(session, top_k=3, beam_width=80, min_power=100_000)
    assert len(rec.attack) == 3
    for t in rec.attack:
        assert len(t.members) == 5
        # Burst chain is the headline hard constraint.
        from nikke_optimizer.optimizer.constraints import has_burst_chain
        assert has_burst_chain(list(t.members))
        assert t.score > 0
        # Members must be unique within a team.
        assert len({m.name for m in t.members}) == 5
