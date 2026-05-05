"""Phase 4 feasibility — genetic-algorithm team search.

The Phase-2 heuristic uses beam search + local search to find top-K
teams under a hand-tuned score function. Beam search converges quickly
on familiar comps (Crown / Liter / SBS / etc.) but its single-direction
greediness can miss non-obvious team compositions that score similarly.

This GA explores the team space stochastically:

  * **Population** — N random valid 5-Nikke teams from the pool.
  * **Fitness** — ``score_team(team).score``; invalid teams get 0.
  * **Selection** — tournament of size K (K=5 default) — pick K random
    teams, return the highest-scoring.
  * **Crossover** — combine two parents' member sets, dedupe, drop or
    fill to 5 unique members, verify burst-chain feasibility.
  * **Mutation** — small probability per child of swapping one member
    for a random pool member.
  * **Elitism** — top-E teams pass to next generation unchanged.

Returns top-K final teams (by fitness) plus a convergence trace.

Compared to beam search, GA is roughly equivalent in wall-clock time
on typical pools (~60 characters) but explores different neighborhoods
each run (seedable for reproducibility). The initial test is whether
GA's top-K shows meaningfully different teams from beam's top-K — if
yes, that's evidence Phase 4 ML can find compositions the heuristic
misses.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from .constraints import is_valid_team
from .models import CharacterView, TeamCandidate
from .scoring import DEFAULT_WEIGHTS, ScoringWeights, score_team


@dataclass
class GASearchResult:
    """Output of :func:`genetic_search`."""

    teams: list[TeamCandidate] = field(default_factory=list)
    best_score_per_generation: list[float] = field(default_factory=list)
    mean_score_per_generation: list[float] = field(default_factory=list)
    generations_run: int = 0
    pool_size: int = 0
    final_population_unique_compositions: int = 0


def _random_valid_team(
    pool: list[CharacterView], rng: random.Random, attempts: int = 50
) -> Optional[list[CharacterView]]:
    """Sample a random 5-member team that passes ``is_valid_team``.

    Burst-chain feasibility is not satisfied by uniform random sampling
    most of the time — bias toward picking 1× B1, 1× B2, 3× any. Falls
    back to fully-uniform if biased sampling can't find a valid team.
    """
    by_pos: dict[str, list[CharacterView]] = {"1": [], "2": [], "3": [], "flex": []}
    for c in pool:
        by_pos.setdefault(c.burst_position, []).append(c)
    for _ in range(attempts):
        # Try the canonical 1/1/3 chain first.
        if by_pos["1"] and by_pos["2"] and len(by_pos["3"]) >= 3:
            picks: list[CharacterView] = [
                rng.choice(by_pos["1"]),
                rng.choice(by_pos["2"]),
            ]
            picks.extend(rng.sample(by_pos["3"], 3))
            if is_valid_team(picks):
                return picks
        # Fall through: pick 5 random from full pool.
        candidates = rng.sample(pool, 5) if len(pool) >= 5 else None
        if candidates and is_valid_team(candidates):
            return candidates
    return None


def _fitness(team: list[CharacterView], weights: ScoringWeights) -> float:
    cand = score_team(team, weights=weights)
    return cand.score if cand is not None else 0.0


def _tournament_select(
    population: list[tuple[list[CharacterView], float]],
    rng: random.Random,
    k: int,
) -> list[CharacterView]:
    contenders = rng.sample(population, min(k, len(population)))
    return max(contenders, key=lambda t: t[1])[0]


def _crossover(
    parent_a: list[CharacterView],
    parent_b: list[CharacterView],
    pool: list[CharacterView],
    rng: random.Random,
) -> Optional[list[CharacterView]]:
    """Blend two parents' members into a new team.

    Uniformly pick each slot from one of the two parents, dedupe, then
    fill any missing slots from the pool. Returns ``None`` when no
    valid burst chain can be assembled within a few retries.
    """
    seen: set[str] = set()
    child: list[CharacterView] = []
    for i in range(5):
        chosen = parent_a[i] if rng.random() < 0.5 else parent_b[i]
        if chosen.name not in seen:
            child.append(chosen)
            seen.add(chosen.name)
    # Fill remaining slots from the pool (unbiased), prefer slots that
    # complete the burst chain.
    remaining_pool = [c for c in pool if c.name not in seen]
    rng.shuffle(remaining_pool)
    for c in remaining_pool:
        if len(child) >= 5:
            break
        child.append(c)
    if len(child) != 5 or not is_valid_team(child):
        return None
    return child


def _mutate(
    team: list[CharacterView],
    pool: list[CharacterView],
    rng: random.Random,
) -> list[CharacterView]:
    """Swap one team member for a random pool member, keeping validity."""
    member_names = {m.name for m in team}
    candidates = [c for c in pool if c.name not in member_names]
    if not candidates:
        return team
    for _ in range(10):
        idx = rng.randrange(5)
        replacement = rng.choice(candidates)
        new_team = list(team)
        new_team[idx] = replacement
        if is_valid_team(new_team):
            return new_team
    return team


def genetic_search(
    pool: list[CharacterView],
    *,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
    population_size: int = 100,
    generations: int = 50,
    top_k: int = 5,
    tournament_size: int = 5,
    mutation_rate: float = 0.15,
    crossover_rate: float = 0.7,
    elitism: int = 2,
    seed: Optional[int] = None,
) -> GASearchResult:
    """Run a genetic algorithm over the team space, return top-K.

    All probabilities are per-child. ``elitism`` ensures the top-E
    teams of each generation pass through unchanged so the best score
    is monotonic non-decreasing.
    """
    if len(pool) < 5:
        return GASearchResult(pool_size=len(pool))
    rng = random.Random(seed)

    # Initialize population.
    population: list[tuple[list[CharacterView], float]] = []
    init_attempts = 0
    while len(population) < population_size and init_attempts < population_size * 4:
        init_attempts += 1
        team = _random_valid_team(pool, rng)
        if team is None:
            continue
        population.append((team, _fitness(team, weights)))
    if not population:
        return GASearchResult(pool_size=len(pool))

    best_trace: list[float] = []
    mean_trace: list[float] = []

    for _gen in range(generations):
        population.sort(key=lambda t: -t[1])
        best_trace.append(population[0][1])
        mean_trace.append(sum(t[1] for t in population) / len(population))

        # Elitism — top-E unchanged.
        next_pop: list[tuple[list[CharacterView], float]] = list(population[:elitism])

        while len(next_pop) < population_size:
            parent_a = _tournament_select(population, rng, tournament_size)
            parent_b = _tournament_select(population, rng, tournament_size)
            if rng.random() < crossover_rate:
                child = _crossover(parent_a, parent_b, pool, rng)
            else:
                child = list(parent_a)
            if child is None:
                continue
            if rng.random() < mutation_rate:
                child = _mutate(child, pool, rng)
            next_pop.append((child, _fitness(child, weights)))
        population = next_pop

    population.sort(key=lambda t: -t[1])
    # Dedupe by member-set and pull top-K candidates.
    seen: set[frozenset[str]] = set()
    out_teams: list[TeamCandidate] = []
    for team, _score in population:
        key = frozenset(m.name for m in team)
        if key in seen:
            continue
        seen.add(key)
        cand = score_team(team, weights=weights)
        if cand is not None:
            out_teams.append(cand)
        if len(out_teams) >= top_k:
            break

    return GASearchResult(
        teams=out_teams,
        best_score_per_generation=best_trace,
        mean_score_per_generation=mean_trace,
        generations_run=generations,
        pool_size=len(pool),
        final_population_unique_compositions=len(seen),
    )
