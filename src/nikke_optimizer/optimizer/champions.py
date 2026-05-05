"""Champions Arena solver — 5 teams locked at season start.

Champions Arena rules:

  * **5 teams of 5** — pairwise disjoint (25 unique Nikkes total).
  * Round format: 5 sub-matches per round, Team N vs opponent's Team N.
  * The user's role per sub-match is a **50/50 coin flip** — each team must
    be balanced for BOTH attack and defense play.
  * Teams are **locked at season start** (no swaps mid-season). Skill
    levels, OL gear, and Synchro Device matter; all Nikkes auto-level to
    400 in-match (CP penalty removed).

Phase-2 alpha implementation: top-5 distinct teams via lockout. Same
scoring weights as Rookie/SP for now. A future slice will add:

  * **role-balanced scoring** — currently both attack/defense use the same
    weights; Champions teams should score versatile picks higher
  * **matchup coverage** — across the 5 teams, the elements should cover
    all of the meta opponents' likely picks (Fire+Water+Wind+Iron+Electric)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session

from .constraints import effective_min_skill_sum
from .coverage import CoverageReport, compute_coverage
from .loader import filter_eligible, load_owned
from .models import CharacterView, TeamCandidate
from .scoring import BALANCED_WEIGHTS, ScoringWeights, score_team
from .search import beam_search_top_teams, local_search_improve


CHAMPIONS_TEAM_COUNT = 5
MIN_POOL_SIZE = 25  # 5 teams × 5 members


@dataclass
class ChampionsRecommendation:
    teams: list[TeamCandidate] = field(default_factory=list)
    coverage: Optional[CoverageReport] = None
    notes: list[str] = field(default_factory=list)


def _try_cross_team_swap(
    teams: list[TeamCandidate],
    pool: list[CharacterView],
    weights: ScoringWeights,
) -> tuple[list[TeamCandidate], bool]:
    """One pass of cross-team swap optimization.

    For each pair of teams (A, B) and each (member_a in A, member_b in B):
      * try swapping member_a ↔ member_b
      * keep the swap if it improves total per-team score AND total coverage
        without making any team invalid

    Returns (possibly-updated teams, did_any_swap_happen).
    """
    in_use = {m.name: (i, j) for i, t in enumerate(teams) for j, m in enumerate(t.members)}
    base_team_score = sum(t.score for t in teams)
    base_coverage = compute_coverage(teams).total_coverage
    improved = False

    for a in range(len(teams)):
        for b in range(a + 1, len(teams)):
            for ia in range(5):
                for ib in range(5):
                    candidate_a = list(teams[a].members)
                    candidate_b = list(teams[b].members)
                    candidate_a[ia], candidate_b[ib] = candidate_b[ib], candidate_a[ia]
                    new_a = score_team(candidate_a, weights=weights)
                    new_b = score_team(candidate_b, weights=weights)
                    if new_a is None or new_b is None:
                        continue
                    new_teams = list(teams)
                    new_teams[a] = new_a
                    new_teams[b] = new_b
                    new_team_score = sum(t.score for t in new_teams)
                    new_coverage = compute_coverage(new_teams).total_coverage
                    if (new_team_score + new_coverage) > (base_team_score + base_coverage):
                        teams = new_teams
                        base_team_score = new_team_score
                        base_coverage = new_coverage
                        improved = True
                        # Restart the outer loops — bookkeeping for ``in_use``
                        # gets stale otherwise and the next swap could unfix
                        # a beneficial change.
                        return teams, True
    return teams, improved


def recommend_champions(
    session: Session,
    *,
    beam_width: int = 200,
    min_power: int = 50_000,
    weights: ScoringWeights = BALANCED_WEIGHTS,
    polish: bool = True,
    coverage_swap_iterations: int = 5,
    override_weights: Optional[ScoringWeights] = None,
) -> ChampionsRecommendation:
    """Return 5 disjoint team recommendations for the season-locked plan.

    ``override_weights`` (slice #104) — when supplied, replaces the
    default ``weights`` argument so the web UI's custom-weight panel
    can tune Champions search the same way rookie + SP do.
    """
    if override_weights is not None:
        weights = override_weights
    owned = load_owned(session)
    pool = filter_eligible(owned, min_power=min_power, min_skill_sum=effective_min_skill_sum())

    notes: list[str] = []
    if len(pool) < MIN_POOL_SIZE:
        notes.append(
            f"Eligible pool has only {len(pool)} Nikkes — Champions Arena needs "
            f"≥ {MIN_POOL_SIZE} unique characters. Consider lowering --min-power."
        )

    teams: list[TeamCandidate] = []
    locked_out: set[str] = set()
    for slot in range(CHAMPIONS_TEAM_COUNT):
        sub_pool = [c for c in pool if c.name not in locked_out]
        if len(sub_pool) < 5:
            notes.append(
                f"slot {slot + 1}: not enough eligible characters left "
                f"(only {len(sub_pool)} available)"
            )
            break
        raw = beam_search_top_teams(
            sub_pool, top_k=8, beam_width=beam_width, weights=weights
        )
        if polish:
            raw = [local_search_improve(c, sub_pool, weights=weights) for c in raw]
        if not raw:
            notes.append(f"slot {slot + 1}: search returned no valid team")
            break
        best = max(raw, key=lambda t: t.score)
        teams.append(best)
        locked_out.update(m.name for m in best.members)

    # Cross-team swap pass: trade members between teams when the trade
    # improves total team score + matchup coverage. The lockout produces
    # local optima per slot; this pass finds globally better arrangements.
    for _ in range(coverage_swap_iterations):
        teams, improved = _try_cross_team_swap(teams, pool, weights)
        if not improved:
            break

    teams.sort(key=lambda t: -t.score)
    coverage = compute_coverage(teams) if teams else None
    if coverage:
        notes.extend(coverage.notes)
    return ChampionsRecommendation(teams=teams, coverage=coverage, notes=notes)
