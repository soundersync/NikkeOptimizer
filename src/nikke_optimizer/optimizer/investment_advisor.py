"""Investment advisor — "who should I level up next?"

For each owned-but-not-in-top-K Nikke, simulate "what if she had +N
skill levels?" and re-run the optimizer. If the upgrade pushes her
into top-K, she's a good ROI candidate. Rank by ROI: how much team
score increases per 'investment unit' applied.

Definition of "investment unit": +6 average skill levels (i.e. raise
all three skills from 1/1/1 to 7/7/7, or equivalent). One unit ≈ what
a player can realistically do in a few weeks of skill-book farming.

Output: a ranked list of (name, current_top_K_membership,
projected_top_K_after_upgrade, score_lift) tuples. Surfaced via the
``/roster/advisor`` web route + a CLI ``advisor`` command.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Optional

from sqlmodel import Session

from .constraints import effective_min_skill_sum
from .loader import filter_eligible, load_owned
from .models import CharacterView, TeamCandidate
from .scoring import ATTACK_WEIGHTS, ScoringWeights, score_team
from .search import beam_search_top_teams


@dataclass
class InvestmentRecommendation:
    name: str
    current_score_in_team: float  # 0 if not in baseline top-K
    projected_score_in_team: float  # if upgraded
    score_lift: float
    appears_in_baseline_top_k: bool
    appears_in_upgraded_top_k: bool
    roi_score: float  # higher = better; combined of lift × likelihood-of-use


def _upgrade(view: CharacterView, *, target_skill: int = 7) -> CharacterView:
    """Return a copy of the view with all 3 skills bumped to ``target_skill``."""
    return replace(
        view,
        skill1_level=max(view.skill1_level, target_skill),
        skill2_level=max(view.skill2_level, target_skill),
        burst_skill_level=max(view.burst_skill_level, target_skill),
    )


def _team_member_names(team: TeamCandidate) -> set[str]:
    return {m.name for m in team.members}


def recommend_investment(
    session: Session,
    *,
    weights: ScoringWeights = ATTACK_WEIGHTS,
    top_k: int = 5,
    beam_width: int = 200,
    min_power: int = 50_000,
    target_skill: int = 7,
    max_recommendations: int = 10,
    extended_top_k_multiplier: int = 2,
) -> list[InvestmentRecommendation]:
    """Rank under-invested Nikkes by upgrade ROI.

    Slice #127 (relaxed criteria) — surfaces a candidate when EITHER:
      (a) upgrading her pushes her into the baseline top-K, or
      (b) upgrading her pushes her into top-(K × multiplier) and the
          team containing her scores higher than the current top-K
          minimum.

    Strategy:
      1. Compute baseline top-K and top-(K × multiplier) team sets.
      2. Identify owned-but-undertrained Nikkes (skill_sum < floor).
      3. For each, simulate upgrading skills to ``target_skill``,
         re-run beam search at the wider top-K, check inclusion.
      4. Score by team-lift; rank by ROI.
    """
    floor = effective_min_skill_sum()
    owned = load_owned(session)
    baseline_pool = filter_eligible(
        owned, min_power=min_power, min_skill_sum=floor
    )
    extended_top_k = top_k * max(1, extended_top_k_multiplier)
    baseline = beam_search_top_teams(
        baseline_pool, top_k=extended_top_k, beam_width=beam_width, weights=weights
    )
    baseline_member_names: set[str] = set()
    baseline_total_score = sum(t.score for t in baseline[:top_k])
    baseline_top_k_min = (
        baseline[top_k - 1].score if len(baseline) >= top_k else 0.0
    )
    for t in baseline[:top_k]:
        baseline_member_names.update(_team_member_names(t))

    candidates_all = [
        v for v in owned
        if v.owned
        and v.power >= min_power
        and (v.skill1_level + v.skill2_level + v.burst_skill_level)
            < floor
    ]
    candidates = sorted(candidates_all, key=lambda v: -v.power)[:30]

    recommendations: list[InvestmentRecommendation] = []
    for cand in candidates:
        upgraded_view = _upgrade(cand, target_skill=target_skill)
        what_if_pool = []
        for v in owned:
            if v.name == cand.name:
                what_if_pool.append(upgraded_view)
            else:
                what_if_pool.append(v)
        what_if_filtered = filter_eligible(
            what_if_pool, min_power=min_power, min_skill_sum=floor
        )
        what_if_top = beam_search_top_teams(
            what_if_filtered, top_k=extended_top_k, beam_width=beam_width, weights=weights
        )
        # Find the best team containing the candidate (across the
        # extended top-K, not just primary top-K).
        teams_with_cand = [
            t for t in what_if_top if cand.name in _team_member_names(t)
        ]
        if not teams_with_cand:
            continue
        best_with = max(teams_with_cand, key=lambda t: t.score)
        in_top_k = any(
            cand.name in _team_member_names(t) for t in what_if_top[:top_k]
        )
        # Relaxed inclusion: in_top_k OR best_with's team beats the
        # baseline top-K floor (would crack the top-K with enough
        # adjacent slot tweaks).
        beats_baseline_floor = best_with.score > baseline_top_k_min
        if not in_top_k and not beats_baseline_floor:
            continue
        upgraded_total_score = sum(t.score for t in what_if_top[:top_k])
        score_lift = upgraded_total_score - baseline_total_score
        recommendations.append(
            InvestmentRecommendation(
                name=cand.name,
                current_score_in_team=0.0,
                projected_score_in_team=best_with.score,
                score_lift=score_lift,
                appears_in_baseline_top_k=False,
                appears_in_upgraded_top_k=in_top_k,
                roi_score=max(score_lift, best_with.score - baseline_top_k_min),
            )
        )

    recommendations.sort(key=lambda r: -r.roi_score)
    return recommendations[:max_recommendations]
