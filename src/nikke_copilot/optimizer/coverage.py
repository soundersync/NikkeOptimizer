"""Set-level analysis for Champions Arena's 5-team season plan.

A great Champions plan isn't just "5 strong teams" — it's "5 teams that
together can counter any opposing lineup". An all-Iron plan can be walled
by a single Wind specialist opponent, even if each individual team scores
high under per-team weights.

This module computes set-level coverage metrics:

  * **element_coverage** — for each of the 5 opposing elements, do we have
    at least one team that fields a member with element advantage? Two
    teams covering the same element get diminishing returns.
  * **archetype_spread** — are our 5 teams clustered around the same
    burst/role archetype, or do we have variety (carry / stall / sustain)?

The coverage score is purely additive on top of the per-team scores; the
solver can either expose it as a report (current behavior) or actively
optimize for it via cross-team swaps (future).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from ..data.enums import Element
from .counter import has_element_advantage
from .models import TeamCandidate


@dataclass
class CoverageReport:
    """Set-level summary of a Champions Arena plan."""

    element_coverage: float = 0.0  # 0..5, one point per covered opposing element
    covered_opposing_elements: list[Element] = field(default_factory=list)
    uncovered_opposing_elements: list[Element] = field(default_factory=list)
    team_primary_elements: list[Element] = field(default_factory=list)
    archetype_spread: float = 0.0  # 0..1, fraction of distinct archetypes
    notes: list[str] = field(default_factory=list)

    @property
    def total_coverage(self) -> float:
        return self.element_coverage + 2.0 * self.archetype_spread


def _team_primary_element(team: TeamCandidate) -> Element:
    """The element best representing this team's offensive output.

    Counts non-Supporter members (since Supporters aren't dealing damage),
    falling back to overall mode when every member is a Supporter.
    """
    attackers = [
        m for m in team.members if "Attacker" in m.role_tags
    ]
    pool = attackers or list(team.members)
    counts = Counter(m.element for m in pool)
    return counts.most_common(1)[0][0]


def _team_archetype(team: TeamCandidate) -> str:
    """Coarse archetype label: ``carry``, ``stall``, or ``balanced``.

    Carries lean on a single high-DPS attacker + boosters. Stalls have
    multiple defenders/healers to time out the attacker. Balanced is
    everything else (the meta middle ground).
    """
    n_attackers = sum(1 for m in team.members if "Attacker" in m.role_tags)
    n_durability = sum(
        1
        for m in team.members
        if any(t in m.role_tags for t in ("Defender", "Shielder", "Healer"))
    )
    if n_durability >= 3:
        return "stall"
    if n_attackers >= 2 and n_durability <= 1:
        return "carry"
    return "balanced"


def compute_coverage(teams: Iterable[TeamCandidate]) -> CoverageReport:
    """Score the matchup coverage of a list of teams (typically 5)."""
    teams = list(teams)
    report = CoverageReport()

    # Per-opposing-element: do any of our teams have a member with
    # element advantage? Score 1.0 per covered element.
    covered: list[Element] = []
    uncovered: list[Element] = []
    for opp_elem in Element:
        any_team_covers = False
        for team in teams:
            if any(has_element_advantage(m.element, opp_elem) for m in team.members):
                any_team_covers = True
                break
        if any_team_covers:
            covered.append(opp_elem)
        else:
            uncovered.append(opp_elem)
    report.element_coverage = float(len(covered))
    report.covered_opposing_elements = covered
    report.uncovered_opposing_elements = uncovered

    if uncovered:
        names = ", ".join(e.value for e in uncovered)
        report.notes.append(
            f"no team covers opposing {names} — those opponents will be tough"
        )

    # Per-team primary element + archetype distribution.
    primaries = [_team_primary_element(t) for t in teams]
    report.team_primary_elements = primaries
    archetypes = [_team_archetype(t) for t in teams]
    distinct_archetypes = len(set(archetypes))
    report.archetype_spread = distinct_archetypes / max(len(archetypes), 1)
    if distinct_archetypes < 2 and archetypes:
        report.notes.append(
            f"all teams share the {archetypes[0]} archetype — adding variety "
            "(stall + carry mix) protects against opponents who counter just one"
        )

    return report
