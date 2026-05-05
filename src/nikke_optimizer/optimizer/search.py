"""Search strategies for picking the top-K 5-Nikke teams.

The owned roster has ~180 characters → C(180, 5) ≈ 1.5 billion combinations.
Brute force is out. We use **beam search** keyed on a partial-team prefix:

  1. Seed: every single-member partial team.
  2. Expand: for each partial team, try adding each remaining character.
  3. Prune: keep the top-W (beam width) partial teams by partial score.
  4. Repeat until partial teams have 5 members.
  5. Score the final candidates and return the top-K complete teams.

For Phase-2 alpha this lands around the right neighborhood quickly. A
follow-up local-search pass (1-swap improvement) refines the top result.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from .constraints import has_burst_chain
from .models import CharacterView, TeamCandidate
from .scoring import DEFAULT_WEIGHTS, ScoringWeights, score_team

log = logging.getLogger(__name__)


_DURABILITY_TAGS = {"Defender", "Shielder", "Healer", "Cover Heal", "Taunter"}
_BURST_GEN_TAGS = {"Burst CD Reduction", "Re-Enter Burst Stage"}

# Sentinel value applied to partials that have wandered into a burst-chain-
# infeasible state — they can't produce a valid 5-member team regardless of
# what's added next. Without this, beam search can converge on durability
# partials that all lack a B1 slot and final scoring returns 0 teams.
_INFEASIBLE_PENALTY = -1e6


def _burst_chain_feasible(partial: tuple[CharacterView, ...]) -> bool:
    """Could this partial still complete a valid B1+B2+B3 chain?

    Counts each bucket's coverage; remaining slots must be enough to cover
    the deficit (after FLEX members fill what they can).
    """
    have = {"1": 0, "2": 0, "3": 0}
    flex = 0
    for m in partial:
        pos = m.burst_position
        if pos in have:
            have[pos] += 1
        else:
            flex += 1
    deficit = sum(max(0, 1 - have[k]) for k in have)
    effective_deficit = max(0, deficit - flex)
    remaining = 5 - len(partial)
    return remaining >= effective_deficit


def _precompute_contributions(
    pool: list[CharacterView],
) -> dict[str, tuple[int, float, float, float, object]]:
    """Precompute per-character static contributions to ``_partial_score``.

    Slice #98 — beam search calls ``_partial_score`` ~90k times per run.
    Without precomputation, each call re-scans ``role_tags`` and
    re-computes the skill/cube investment for every member of the
    partial team. Caching the per-character contribution upfront gives
    a 2-3× speedup on ~200-character pools.

    Returns a mapping ``name -> (power, invest, durability, burst_gen,
    element)`` keyed on the character's name. ``element`` stays as the
    enum object so the partial-set membership (for diversity counting)
    works without an extra hash hop.
    """
    out: dict[str, tuple[int, float, float, float, object]] = {}
    for c in pool:
        skills = (c.skill1_level + c.skill2_level + c.burst_skill_level) / 3
        invest = skills / 10
        if c.arena_cube_name:
            invest += 0.3
        member_dur = sum(1 for tag in c.role_tags if tag in _DURABILITY_TAGS)
        dur = float(min(member_dur, 2))
        burst_gen = sum(1.0 for tag in c.role_tags if tag in _BURST_GEN_TAGS)
        out[c.name] = (c.power, invest, dur, burst_gen, c.element)
    return out


def _partial_score(
    partial: tuple[CharacterView, ...],
    weights: ScoringWeights,
    contribs: Optional[dict[str, tuple]] = None,
) -> float:
    """Cheap estimate used for beam-search pruning of partial teams.

    We can't run the full ``score_team`` on a partial because it requires
    the burst-chain hard constraint to pass. Instead we accumulate the
    *additive* per-character components — power, element diversity,
    investment, durability, burst-gen — using the same weights as the
    final scorer. This lets beam search keep role-relevant partials alive
    when role weights diverge from balanced (e.g. defense pruning kills
    high-power but low-durability cores otherwise).

    ``contribs`` is the optional precomputed per-character table from
    :func:`_precompute_contributions` — when provided, we look up
    static contributions instead of re-walking ``role_tags`` per call.
    """
    if not partial:
        return 0.0
    if not _burst_chain_feasible(partial):
        return _INFEASIBLE_PENALTY
    import math
    power = 0
    invest = 0.0
    durability = 0.0
    burst_gen = 0.0
    elements: set = set()
    if contribs is not None:
        for m in partial:
            entry = contribs.get(m.name)
            if entry is None:
                # Member not in the precomputed pool (e.g., outside the
                # set passed to beam_search_top_teams). Fall through to
                # the slow path for this member only.
                pwr = m.power
                inv_v = ((m.skill1_level + m.skill2_level + m.burst_skill_level) / 3) / 10
                if m.arena_cube_name:
                    inv_v += 0.3
                dur_v = float(min(
                    sum(1 for tag in m.role_tags if tag in _DURABILITY_TAGS), 2
                ))
                bg_v = sum(1.0 for tag in m.role_tags if tag in _BURST_GEN_TAGS)
                elem = m.element
            else:
                pwr, inv_v, dur_v, bg_v, elem = entry
            power += pwr
            invest += inv_v
            durability += dur_v
            burst_gen += bg_v
            elements.add(elem)
    else:
        for m in partial:
            power += m.power
            elements.add(m.element)
            skills = (m.skill1_level + m.skill2_level + m.burst_skill_level) / 3
            invest += skills / 10
            if m.arena_cube_name:
                invest += 0.3
            member_dur = sum(1 for tag in m.role_tags if tag in _DURABILITY_TAGS)
            durability += min(member_dur, 2)
            for tag in m.role_tags:
                if tag in _BURST_GEN_TAGS:
                    burst_gen += 1.0

    # Slice #122 — synergy now contributes to the partial-score heuristic.
    # Without this, beam search prunes Crown-comp partials before assembly
    # (Crown alone has the same partial-score as any other B2) and the
    # genetic-algorithm feasibility test (slice #122a) revealed beam was
    # missing the canonical Crown comp by a 25-point gap. Counting
    # already-realized pairs in the partial team biases the search toward
    # high-synergy completions.
    synergy_bonus = 0.0
    if len(partial) >= 2 and weights.synergy_pairs > 0:
        from .scoring import SYNERGY_PAIRS, _meta_tier_for
        names = [m.name for m in partial]
        tier_by_name: dict[str, float] = {}
        for m in partial:
            tier_by_name[m.name] = _meta_tier_for(m.name, tuple(m.role_tags))
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                key = frozenset((names[i], names[j]))
                base = SYNERGY_PAIRS.get(key, 0.0)
                if base > 0:
                    mult = min(tier_by_name[names[i]], tier_by_name[names[j]])
                    synergy_bonus += base * mult

    return (
        weights.power_sum * (math.log10(power) if power > 0 else 0.0)
        + weights.element_diversity * len(elements)
        + weights.investment * invest
        + weights.durability * durability
        + weights.burst_gen * burst_gen
        + weights.synergy_pairs * synergy_bonus
    )


def beam_search_top_teams(
    pool: list[CharacterView],
    *,
    top_k: int = 5,
    beam_width: int = 200,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> list[TeamCandidate]:
    """Return up to ``top_k`` highest-scoring 5-Nikke teams from ``pool``.

    ``beam_width`` trades search breadth for speed; 200 is a reasonable
    default for ~200-character pools and finishes in well under a second.
    """
    if len(pool) < 5:
        return []

    # Sort the pool by per-character desirability so the early beam levels
    # see the most promising members first. Doesn't change correctness but
    # speeds up convergence.
    pool = sorted(
        pool,
        key=lambda c: (
            -c.power,
            -((c.skill1_level + c.skill2_level + c.burst_skill_level) / 3),
        ),
    )
    # Precompute per-character contributions once — _partial_score reads
    # from this dict on every call instead of re-scanning role_tags etc.
    contribs = _precompute_contributions(pool)

    # State: a set of partial teams (each a sorted tuple of names so the same
    # partial picked in different orders dedups).
    beam: list[tuple[tuple[CharacterView, ...], float]] = [((c,), 0.0) for c in pool]

    for level in range(2, 6):
        next_beam: dict[frozenset[str], tuple[tuple[CharacterView, ...], float]] = {}
        for partial, _ in beam:
            partial_names = {m.name for m in partial}
            for c in pool:
                if c.name in partial_names:
                    continue
                new_partial = partial + (c,)
                key = frozenset(m.name for m in new_partial)
                if key in next_beam:
                    continue
                score = _partial_score(new_partial, weights, contribs)
                next_beam[key] = (new_partial, score)
        # Prune to beam_width
        beam = sorted(next_beam.values(), key=lambda x: -x[1])[:beam_width]
        log.debug("beam level %d: %d partials kept", level, len(beam))

    # Score every full team properly (passes through ``score_team`` which
    # enforces the burst-chain hard constraint).
    scored: list[TeamCandidate] = []
    seen: set[frozenset[str]] = set()
    for partial, _ in beam:
        key = frozenset(m.name for m in partial)
        if key in seen:
            continue
        seen.add(key)
        candidate = score_team(list(partial), weights=weights)
        if candidate is not None:
            scored.append(candidate)
    scored.sort(key=lambda t: -t.score)
    return scored[:top_k]


def select_diverse_top_k(
    candidates: list[TeamCandidate],
    *,
    top_k: int,
    mmr_lambda: float = 2.0,
) -> list[TeamCandidate]:
    """Pick ``top_k`` teams with a Maximal Marginal Relevance penalty.

    Pre-slice-#98, the rookie + counter solvers used hard lockout —
    once a member appeared in team #1 they couldn't appear again,
    forcing later picks to use weaker substitutes. This produced
    fully-disjoint top-K cores that diverged from real PvP usage
    (where users field the same Nikke across multiple attack attempts
    with 1-2 swap-outs).

    MMR re-ranks on the fly:

        score(team_i) = base_score(team_i) − λ × shared_count_with_chosen

    Where ``shared_count_with_chosen`` is summed across already-chosen
    teams (so a member shared with 2 prior teams is double-penalized).

    ``mmr_lambda``:
      * 0.0       — equivalent to "take top-K by score, no diversity"
      * 1.0–2.0   — permissive, allows 2-3 shared members for a strong team
      * 4.0+      — aggressive, prefers near-disjoint teams
      * ``inf``   — equivalent to hard lockout

    The candidate list should already be sorted by base score (descending).
    """
    if top_k <= 0 or not candidates:
        return []
    # Dedupe by member-set first — beam search + local-search polish
    # can converge multiple seeds to the same composition. Without
    # this, MMR picks identical teams in slots #2-#K because the
    # "shared with already-chosen" penalty is computed per-composition
    # not per-input-row.
    seen: set[frozenset[str]] = set()
    deduped: list[TeamCandidate] = []
    for c in candidates:
        key = frozenset(m.name for m in c.members)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    chosen: list[TeamCandidate] = []
    chosen_member_counts: dict[str, int] = {}
    pool = deduped
    while pool and len(chosen) < top_k:
        # Compute mmr-adjusted score for every remaining candidate.
        best_index = -1
        best_score = float("-inf")
        for i, cand in enumerate(pool):
            shared = sum(
                chosen_member_counts.get(m.name, 0) for m in cand.members
            )
            mmr_score = cand.score - mmr_lambda * shared
            if mmr_score > best_score:
                best_score = mmr_score
                best_index = i
        if best_index < 0:
            break
        winner = pool.pop(best_index)
        chosen.append(winner)
        for m in winner.members:
            chosen_member_counts[m.name] = chosen_member_counts.get(m.name, 0) + 1
    return chosen


def local_search_improve(
    candidate: TeamCandidate,
    pool: list[CharacterView],
    *,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
    max_iter: int = 20,
) -> TeamCandidate:
    """1-swap hill-climb: try replacing each member with each non-member and
    keep the swap if it improves the score. Repeats until no swap helps or
    ``max_iter`` is hit.

    Cheap polish on top of beam search — beam search finds neighborhoods,
    local search finds local optima within them.
    """
    current = candidate
    for _ in range(max_iter):
        improved = False
        current_names = {m.name for m in current.members}
        for i in range(5):
            for c in pool:
                if c.name in current_names:
                    continue
                new_team = list(current.members)
                new_team[i] = c
                rescored = score_team(new_team, weights=weights)
                if rescored is not None and rescored.score > current.score:
                    current = rescored
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return current
