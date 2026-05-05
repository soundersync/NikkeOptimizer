"""Run the static team evaluator on optimizer-produced teams.

Used by the rookie / SP / Champions web routes to surface per-team
DSL-derived metrics (DPS / EHP / sustain / damage-type buff aggregates)
alongside the heuristic score. Teams whose members aren't all in the
encoded skill registry get a ``MissingEncoding`` placeholder instead so
the template can prompt the user to encode the missing characters.

When the team is fully encoded, ``rescored_teams_with_evaluations`` also
re-scores the candidate using simulator-derived signals (true-damage /
attack-damage / pierce / shield-damage / vs-high-DEF) so the optimizer's
displayed score reflects the DSL evaluator, not just the heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Union

from ..optimizer.models import TeamCandidate
from ..optimizer.scoring import (
    BALANCED_WEIGHTS,
    ScoringWeights,
    rescore_with_evaluator,
)
from ..simulator.evaluator import TeamEvaluation, evaluate_by_names
from ..simulator.registry import all_encoded_names
from ..simulator.timeline import (
    compute_burst_chain_offsets,
    _load_weapons,
)


@dataclass(frozen=True)
class MissingEncoding:
    """Returned when a team has members not in the skill registry."""

    missing: tuple[str, ...]

    def __bool__(self) -> bool:  # so templates can do {% if eval %}
        return False


EvaluationOrMissing = Union[TeamEvaluation, MissingEncoding]


def evaluations_for(
    teams: Iterable[TeamCandidate],
) -> list[EvaluationOrMissing]:
    """Return parallel evaluator results for ``teams``.

    For each team:
      * if all 5 members are encoded → ``TeamEvaluation``
      * else → ``MissingEncoding`` listing the un-encoded names
    """
    encoded = set(all_encoded_names())
    out: list[EvaluationOrMissing] = []
    for team in teams:
        names = [m.name for m in team.members]
        missing = tuple(n for n in names if n not in encoded)
        if missing:
            out.append(MissingEncoding(missing=missing))
            continue
        evaluation = evaluate_by_names(names)
        if evaluation is None:
            out.append(MissingEncoding(missing=tuple(names)))
        else:
            out.append(evaluation)
    return out


@dataclass(frozen=True)
class BurstTiming:
    """Predicted burst-chain timing for a 5-Nikke team (slice #79)."""

    first_burst_sec: float  # B1 fires
    full_burst_start_sec: float  # B3 chains in, FB window opens
    full_burst_end_sec: float  # FB window closes (10s after B3)

    @property
    def label(self) -> str:
        return (
            f"first burst @ {self.first_burst_sec:.1f}s · "
            f"FB {self.full_burst_start_sec:.1f}–"
            f"{self.full_burst_end_sec:.1f}s"
        )


def burst_timings_for(
    teams: Iterable[TeamCandidate],
) -> list[Optional[BurstTiming]]:
    """Return parallel burst-chain timing predictions for ``teams``.

    Auto-loads each team's weapons from the DB and runs them through
    ``compute_burst_chain_offsets`` with skill-bonus threading (slices
    #75 + #78). Returns ``None`` for rows where weapon lookup fails
    entirely (e.g. tests without DB) so the template can render a "—".
    """
    out: list[Optional[BurstTiming]] = []
    for team in teams:
        names = [m.name for m in team.members]
        weapons = _load_weapons(names)
        if not any(weapons):
            out.append(None)
            continue
        offsets = compute_burst_chain_offsets(weapons, member_names=names)
        first = offsets[0]
        fb_start = offsets[2]
        out.append(
            BurstTiming(
                first_burst_sec=first,
                full_burst_start_sec=fb_start,
                full_burst_end_sec=fb_start + 10.0,
            )
        )
    return out


def rescored_teams_with_evaluations(
    teams: Iterable[TeamCandidate],
    *,
    weights: ScoringWeights = BALANCED_WEIGHTS,
) -> tuple[list[TeamCandidate], list[EvaluationOrMissing]]:
    """Compute evaluations and rescore each fully-encoded team.

    Returns ``(rescored_teams, evaluations)`` — both lists parallel to
    the input. Teams with missing encodings are returned unchanged
    (heuristic score only). Teams that are fully encoded get a
    simulator-aware breakdown (with team_buff_amp + vs_high_def folded
    into total).

    Note: callers may want to re-sort by the new ``breakdown.total`` —
    this function preserves input order so the caller can choose.
    """
    teams_list = list(teams)
    evaluations = evaluations_for(teams_list)
    rescored: list[TeamCandidate] = []
    for team, ev in zip(teams_list, evaluations):
        if isinstance(ev, TeamEvaluation):
            rescored.append(rescore_with_evaluator(team, ev, weights=weights))
        else:
            rescored.append(team)
    return rescored, evaluations
