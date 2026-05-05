"""Rookie Arena solver — pick the best attack team and best defense team.

Rookie Arena is the simplest mode:
  * 1 attack team + 1 defense team
  * No uniqueness constraint between them (a Nikke can appear in both)
  * 5 free attack attempts per day → daily ranking rewards

This solver returns the top-K candidate teams via beam search + local search
polish. Attack and defense use **different** weight presets (ATTACK_WEIGHTS
vs DEFENSE_WEIGHTS) so the two recommendations diverge — a defense pick
prefers Helm/Centi/Blanc-style sustain while an attack pick prefers
Liter/Crown-style burst-gen + DPS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session

from .constraints import effective_min_skill_sum
from .loader import filter_eligible, load_owned
from .models import CharacterView, TeamCandidate
from .scoring import (
    ATTACK_WEIGHTS,
    BALANCED_WEIGHTS,
    DEFENSE_WEIGHTS,
    Role,
    ScoringWeights,
    weights_for_role,
)
from .search import beam_search_top_teams, local_search_improve, select_diverse_top_k


@dataclass
class RookieRecommendation:
    attack: list[TeamCandidate]
    defense: list[TeamCandidate]


def _top_distinct(
    pool: list[CharacterView],
    *,
    top_k: int,
    beam_width: int,
    weights: ScoringWeights,
    polish: bool,
    mmr_lambda: float = 2.0,
) -> list[TeamCandidate]:
    """Pick top-K teams with diversity. Slice #98 introduced an MMR
    penalty so attack-mode top-K can show "5 strong teams that share
    1-2 members" instead of fully-disjoint cores; previously a hard
    lockout forced later teams to use weaker substitutes.

    ``mmr_lambda``:
      * 0.0  — pure top-K, no diversity (rare; mostly for tests)
      * 2.0  — default, permissive overlap (1-2 shared members allowed
              when base score is significantly higher)
      * inf  — hard lockout (== pre-slice-#98 behavior)

    Run beam search once on the FULL pool, polish, then MMR-select.
    """
    if len(pool) < 5:
        return []
    # Pull a wide candidate set so MMR has options after dedup. Polish
    # converges multiple seeds onto the same composition; we need more
    # raw candidates than top_k to end up with top_k distinct teams.
    raw = beam_search_top_teams(
        pool,
        top_k=max(top_k * 8, 32),
        beam_width=beam_width,
        weights=weights,
    )
    if polish:
        raw = [local_search_improve(c, pool, weights=weights) for c in raw]
    raw.sort(key=lambda t: -t.score)
    selected = select_diverse_top_k(raw, top_k=top_k, mmr_lambda=mmr_lambda)
    # Fallback to lockout when MMR can't find top_k distinct teams from
    # a single beam pass — typical when min_power is high or the pool
    # is concentrated around one dominant comp. Re-runs beam search
    # with locked-out members to force diversity.
    if len(selected) < top_k:
        locked: set[str] = set()
        for cand in selected:
            locked.update(m.name for m in cand.members)
        while len(selected) < top_k:
            sub_pool = [c for c in pool if c.name not in locked]
            if len(sub_pool) < 5:
                break
            extra_raw = beam_search_top_teams(
                sub_pool, top_k=8, beam_width=beam_width, weights=weights
            )
            if polish:
                extra_raw = [
                    local_search_improve(c, sub_pool, weights=weights)
                    for c in extra_raw
                ]
            if not extra_raw:
                break
            best = max(extra_raw, key=lambda t: t.score)
            selected.append(best)
            locked.update(m.name for m in best.members)
    return selected


def recommend_rookie(
    session: Session,
    *,
    top_k: int = 5,
    beam_width: int = 200,
    min_power: int = 50_000,
    polish: bool = True,
    weights: Optional[ScoringWeights] = None,
    mmr_lambda: float = 2.0,
) -> RookieRecommendation:
    """Return the top-K attack and defense team recommendations.

    Attack and defense are scored with role-specific weight presets — the
    two outputs are computed independently and may surface different
    Nikkes. Pass ``weights`` to override both with a single weight set
    (used by tests that want deterministic scoring).

    ``min_power`` filters out characters the user has barely invested in;
    50k keeps the search pool to genuinely fielded units (a freshly-rolled
    SR with no levels sits around 30-40k).
    """
    owned = load_owned(session)
    pool = filter_eligible(owned, min_power=min_power, min_skill_sum=effective_min_skill_sum())

    if weights is not None:
        # Caller-supplied weights apply to BOTH role searches — used by
        # tests that want deterministic scoring.
        attack_w = defense_w = weights
    else:
        attack_w = ATTACK_WEIGHTS
        defense_w = DEFENSE_WEIGHTS

    attack = _top_distinct(
        pool, top_k=top_k, beam_width=beam_width, weights=attack_w,
        polish=polish, mmr_lambda=mmr_lambda,
    )
    defense = _top_distinct(
        pool, top_k=top_k, beam_width=beam_width, weights=defense_w,
        polish=polish, mmr_lambda=mmr_lambda,
    )
    return RookieRecommendation(attack=attack, defense=defense)
