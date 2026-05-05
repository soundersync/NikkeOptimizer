"""Why-not explainer — "why isn't my favorite Nikke recommended?".

Given a character name, this finds the best valid 5-Nikke team that
*includes* them and reports the score gap vs the global top recommendation.
The breakdown contrast (which scoring components dropped, by how much)
explains *why* the optimizer didn't pick them: lower power, missing
synergies, weaker burst-gen, etc.

Pairs with the existing rookie / SP / Champions solvers — we re-use the
same beam search but seed the initial beam to ALL contain the requested
character.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session

from .loader import filter_eligible, load_owned
from .models import CharacterView, ScoreBreakdown, TeamCandidate
from .scoring import (
    ATTACK_WEIGHTS,
    BALANCED_WEIGHTS,
    DEFENSE_WEIGHTS,
    Role,
    ScoringWeights,
    weights_for_role,
)
from .search import beam_search_top_teams, local_search_improve


@dataclass
class ExplainResult:
    target: CharacterView
    role: Role
    best_with_target: Optional[TeamCandidate]
    global_top: Optional[TeamCandidate]
    score_delta: Optional[float]  # negative = target team is worse

    @property
    def component_deltas(self) -> dict[str, float]:
        if self.best_with_target is None or self.global_top is None:
            return {}
        a = self.best_with_target.breakdown.to_dict()
        b = self.global_top.breakdown.to_dict()
        # Per-component (with-target) - (global-top): negative means the
        # target's team is weaker on that component.
        return {k: a[k] - b[k] for k in a if k != "total"}


def _seed_beam_with_target(
    pool: list[CharacterView],
    target: CharacterView,
    *,
    weights: ScoringWeights,
    beam_width: int,
) -> list[TeamCandidate]:
    """Beam search constrained so every partial team includes ``target``.

    We exclude the target from the regular pool, then run a normal beam
    search on the remaining characters, treating each result as a 4-member
    partial that we extend with the target.
    """
    remaining_pool = [c for c in pool if c.name != target.name]

    # 1) Find the best 4-member combinations from the rest of the pool.
    # We use the existing beam_search_top_teams but stop at level 4 by
    # asking for top_k 4-member teams. There's no public API for that,
    # so we do a small variant inline.
    from .search import _partial_score, _burst_chain_feasible

    # Initial level: every 1-character partial.
    beam: list[tuple[tuple[CharacterView, ...], float]] = [
        ((c,), 0.0) for c in remaining_pool
    ]
    for level in range(2, 5):
        next_beam: dict[frozenset[str], tuple[tuple[CharacterView, ...], float]] = {}
        for partial, _ in beam:
            partial_names = {m.name for m in partial}
            for c in remaining_pool:
                if c.name in partial_names:
                    continue
                # When extended by ``target``, the final team must still
                # have a valid burst chain — pre-check using a
                # target-included variant of the partial.
                hypothetical = partial + (c, target)
                if not _burst_chain_feasible(hypothetical):
                    continue
                new_partial = partial + (c,)
                key = frozenset(m.name for m in new_partial)
                if key in next_beam:
                    continue
                score = _partial_score(new_partial, weights)
                next_beam[key] = (new_partial, score)
        beam = sorted(next_beam.values(), key=lambda x: -x[1])[:beam_width]

    # 2) Extend each 4-partial with target and re-score the full team.
    from .scoring import score_team

    candidates: list[TeamCandidate] = []
    seen: set[frozenset[str]] = set()
    for partial, _ in beam:
        team = list(partial) + [target]
        key = frozenset(m.name for m in team)
        if key in seen:
            continue
        seen.add(key)
        cand = score_team(team, weights=weights)
        if cand is not None:
            candidates.append(cand)
    candidates.sort(key=lambda t: -t.score)
    return candidates


def explain_character(
    session: Session,
    character_name: str,
    *,
    role: Role = "balanced",
    beam_width: int = 200,
    min_power: int = 50_000,
) -> ExplainResult:
    """Return the best valid team containing ``character_name`` plus the
    score gap to the global top recommendation under the same weights."""
    weights = weights_for_role(role)
    pool = filter_eligible(load_owned(session), min_power=min_power)

    # Find target character in the pool (case-insensitive exact match).
    target: Optional[CharacterView] = None
    lookup_pool = [c for c in pool if c.name.lower() == character_name.lower()]
    if not lookup_pool:
        # Fall back to substring match for convenience
        lookup_pool = [c for c in pool if character_name.lower() in c.name.lower()]
    if lookup_pool:
        target = lookup_pool[0]

    if target is None:
        return ExplainResult(
            target=CharacterView(  # type: ignore[arg-type]
                name=character_name, rarity=None, element=None,  # type: ignore[arg-type]
                weapon_class=None, burst_type=None,  # type: ignore[arg-type]
            ),
            role=role,
            best_with_target=None,
            global_top=None,
            score_delta=None,
        )

    # Best team containing the target.
    constrained = _seed_beam_with_target(
        pool, target, weights=weights, beam_width=beam_width
    )
    best_with_target = constrained[0] if constrained else None
    if best_with_target is not None:
        # Local-search polish (preserving target).
        polished = local_search_improve(best_with_target, [target] + [
            c for c in pool if c.name != target.name
        ], weights=weights)
        # If local search swapped the target out, fall back to the
        # constrained result.
        if any(m.name == target.name for m in polished.members):
            best_with_target = polished

    # Global top under the same weights.
    unconstrained = beam_search_top_teams(
        pool, top_k=3, beam_width=beam_width, weights=weights
    )
    global_top: Optional[TeamCandidate] = None
    if unconstrained:
        polished = local_search_improve(unconstrained[0], pool, weights=weights)
        global_top = polished

    delta: Optional[float] = None
    if best_with_target is not None and global_top is not None:
        delta = best_with_target.score - global_top.score

    return ExplainResult(
        target=target,
        role=role,
        best_with_target=best_with_target,
        global_top=global_top,
        score_delta=delta,
    )
