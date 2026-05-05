"""Tests for the Phase 4 genetic-algorithm team search."""

from __future__ import annotations

import pytest

from nikke_optimizer.data.enums import (
    BurstType, Element, Manufacturer, Rarity, WeaponClass,
)
from nikke_optimizer.optimizer.genetic import (
    GASearchResult, genetic_search, _crossover, _mutate, _random_valid_team,
)
from nikke_optimizer.optimizer.models import CharacterView
from nikke_optimizer.optimizer.scoring import ATTACK_WEIGHTS, score_team


def _v(name: str, burst: BurstType, element: Element = Element.IRON, power: int = 200_000) -> CharacterView:
    return CharacterView(
        name=name,
        rarity=Rarity.SSR,
        element=element,
        weapon_class=WeaponClass.AR,
        burst_type=burst,
        manufacturer=Manufacturer.ELYSION,
        role_tags=("Attacker",),
        owned=True,
        power=power,
        skill1_level=10, skill2_level=10, burst_skill_level=10,
    )


def _diverse_pool(n: int = 12) -> list[CharacterView]:
    """Pool with at least one B1, one B2, three B3 so valid teams exist."""
    pool: list[CharacterView] = []
    pool.append(_v("B1a", BurstType.I, Element.WIND))
    pool.append(_v("B1b", BurstType.I, Element.IRON))
    pool.append(_v("B2a", BurstType.II, Element.IRON))
    pool.append(_v("B2b", BurstType.II, Element.WATER))
    for i in range(8):
        pool.append(_v(f"B3{i}", BurstType.III, Element.ELECTRIC, power=150_000 + i * 5_000))
    return pool


def test_random_valid_team_returns_valid_5_member_team():
    import random
    pool = _diverse_pool()
    team = _random_valid_team(pool, random.Random(0))
    assert team is not None
    assert len(team) == 5
    assert score_team(team, weights=ATTACK_WEIGHTS) is not None


def test_genetic_search_returns_top_k_distinct_teams():
    pool = _diverse_pool(12)
    result = genetic_search(
        pool, weights=ATTACK_WEIGHTS, population_size=30,
        generations=10, top_k=3, seed=42,
    )
    assert isinstance(result, GASearchResult)
    assert len(result.teams) <= 3
    # Each returned team is valid + 5 unique members.
    for cand in result.teams:
        assert len(cand.members) == 5
        assert len({m.name for m in cand.members}) == 5
    # Compositions in top-K are pairwise distinct.
    sets = [frozenset(m.name for m in t.members) for t in result.teams]
    assert len(sets) == len(set(sets))


def test_genetic_search_score_is_monotonic_non_decreasing_with_elitism():
    """With elitism > 0, best-score-per-generation never decreases."""
    pool = _diverse_pool(12)
    result = genetic_search(
        pool, weights=ATTACK_WEIGHTS, population_size=30,
        generations=15, top_k=3, elitism=2, seed=1,
    )
    trace = result.best_score_per_generation
    assert len(trace) == 15
    for prev, curr in zip(trace, trace[1:]):
        assert curr >= prev - 1e-6  # tolerance for float noise


def test_genetic_search_too_small_pool_returns_empty():
    pool = _diverse_pool(4)[:4]  # only 4 chars
    result = genetic_search(pool, generations=5, population_size=10)
    assert result.teams == []


def test_genetic_search_seed_reproducibility():
    """Same seed → same final top-K (composition identity)."""
    pool = _diverse_pool(12)
    r1 = genetic_search(pool, population_size=20, generations=8, seed=7, top_k=3)
    r2 = genetic_search(pool, population_size=20, generations=8, seed=7, top_k=3)
    sets1 = [frozenset(m.name for m in t.members) for t in r1.teams]
    sets2 = [frozenset(m.name for m in t.members) for t in r2.teams]
    assert sets1 == sets2


def test_crossover_produces_valid_team_or_none():
    import random
    pool = _diverse_pool(12)
    rng = random.Random(0)
    a = _random_valid_team(pool, rng)
    b = _random_valid_team(pool, rng)
    assert a is not None and b is not None
    child = _crossover(a, b, pool, rng)
    if child is not None:
        assert len(child) == 5
        assert len({m.name for m in child}) == 5
        assert score_team(child) is not None


def test_mutate_swaps_one_member_or_returns_unchanged():
    import random
    pool = _diverse_pool(12)
    rng = random.Random(0)
    team = _random_valid_team(pool, rng)
    assert team is not None
    mutated = _mutate(team, pool, rng)
    # Either no change, or exactly one swap (4/5 members preserved).
    common = {m.name for m in team} & {m.name for m in mutated}
    assert len(common) >= 4
