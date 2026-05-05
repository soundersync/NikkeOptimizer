"""Counter-pick mode — pick the best attack team to beat a known opponent.

Given an opponent's defense lineup (5 character names), score attack
candidates from the user's roster with an additional element-advantage
component on top of the standard scorer:

  Fire > Wind > Iron > Electric > Water > Fire (cyclic, +10% dmg on weakness)

Each member of the user's attack team that has element advantage against
ANY opponent contributes a small bonus; element advantage from MULTIPLE
opponents stacks. The result is a team that hits the opponent's weak
elements first.

Element advantage is a soft signal — synergies, power, and burst chain
still dominate the score. The opponent context just tilts ties toward
elementally-favored picks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlmodel import Session

from ..data.enums import Element
from .constraints import effective_min_skill_sum
from .loader import OptimizerContext, filter_eligible, load_owned, load_all
from .models import CharacterView, ScoreBreakdown, TeamCandidate
from .scoring import ATTACK_WEIGHTS, ScoringWeights, score_team
from .search import beam_search_top_teams, local_search_improve, select_diverse_top_k


# Cyclic element advantage: ATTACKER element → element it beats.
# In NIKKE the wheel is Fire ↦ Wind ↦ Iron ↦ Electric ↦ Water ↦ Fire.
_ADVANTAGE: dict[Element, Element] = {
    Element.FIRE: Element.WIND,
    Element.WIND: Element.IRON,
    Element.IRON: Element.ELECTRIC,
    Element.ELECTRIC: Element.WATER,
    Element.WATER: Element.FIRE,
}


def has_element_advantage(attacker: Element, defender: Element) -> bool:
    """True iff ``attacker`` deals weakness damage to ``defender``."""
    return _ADVANTAGE.get(attacker) is defender


def element_coverage(
    team: list["CharacterView"],
    opponent_members: list["CharacterView"],
) -> tuple[int, int]:
    """Return ``(covered, distinct)`` opponent elements.

    ``covered`` = how many distinct opponent elements at least one
    team member has element advantage over.
    ``distinct`` = how many distinct elements the opponent fields.

    Display as "X/Y" on the team card so users can spot-check whether
    a recommendation actually exploits the opponent's weaknesses.
    Slice #116.
    """
    opp_elements = {m.element for m in opponent_members}
    covered_elements: set[Element] = set()
    for m in team:
        for opp in opp_elements:
            if has_element_advantage(m.element, opp):
                covered_elements.add(opp)
    return (len(covered_elements), len(opp_elements))


@dataclass(frozen=True)
class CounterContext:
    """Frozen description of an opponent's lineup for counter-pick scoring."""

    opponent_members: tuple[CharacterView, ...]

    @property
    def elements(self) -> tuple[Element, ...]:
        return tuple(m.element for m in self.opponent_members)


def _element_advantage_bonus(
    team: list[CharacterView], context: CounterContext
) -> tuple[float, list[str]]:
    """Bonus = sum over (my member × opponent member) of weakness matchups.

    Each weakness matchup adds 1.0. A 5-vs-5 fully-favored matchup hits 25;
    a typical favorable lineup is 4-7 points.
    """
    bonus = 0.0
    notes: list[str] = []
    for mine in team:
        countered: list[str] = []
        for opp in context.opponent_members:
            if has_element_advantage(mine.element, opp.element):
                bonus += 1.0
                countered.append(opp.name)
        if countered:
            notes.append(
                f"{mine.name} ({mine.element.value}) counters: {', '.join(countered)}"
            )
    return bonus, notes


def score_counter(
    team: list[CharacterView],
    context: CounterContext,
    *,
    weights: ScoringWeights = ATTACK_WEIGHTS,
    element_weight: float = 1.5,
) -> Optional[TeamCandidate]:
    """Score a candidate team against a specific opponent.

    Wraps the base ``score_team`` and folds in element-advantage bonus
    weighted by ``element_weight`` (default 1.5 — comparable to the role
    balance weight, deliberately not dominant so meta synergies still win
    when element coverage is even).
    """
    base = score_team(team, weights=weights)
    if base is None:
        return None
    bonus, bonus_notes = _element_advantage_bonus(team, context)
    weighted_bonus = element_weight * bonus
    new_breakdown = ScoreBreakdown(
        burst_feasibility=base.breakdown.burst_feasibility,
        power_sum=base.breakdown.power_sum,
        element_diversity=base.breakdown.element_diversity + weighted_bonus,
        role_balance=base.breakdown.role_balance,
        synergy_pairs=base.breakdown.synergy_pairs,
        investment=base.breakdown.investment,
        total=base.breakdown.total + weighted_bonus,
    )
    notes = list(base.notes)
    if bonus_notes:
        notes.append(f"element advantage: +{weighted_bonus:.1f}")
        notes.extend(bonus_notes)
    return TeamCandidate(
        members=base.members, breakdown=new_breakdown, notes=notes
    )


def _resolve_opponent(
    session: Session,
    names: Iterable[str],
    *,
    context: Optional[OptimizerContext] = None,
) -> CounterContext:
    """Look up each opponent name in the DB.

    Falls back to ``load_all`` (which includes unowned characters) — the
    opponent will likely have characters the user doesn't own. When a
    cached :class:`OptimizerContext` is supplied, reuses its
    pre-loaded ``all_views`` instead of re-querying.
    """
    all_views = context.all_views if context is not None else load_all(session)
    pool_by_name = {v.name: v for v in all_views}
    members: list[CharacterView] = []
    for name in names:
        if not name:
            continue
        view = pool_by_name.get(name)
        if view is None:
            # Fuzzy fallback for slight name variants like "Snow White" vs
            # "Snow White: Heavy Arms" — pick the first DB entry that
            # starts-with the requested name.
            for candidate_name, view in pool_by_name.items():
                if candidate_name.lower().startswith(name.lower()):
                    members.append(view)
                    break
            continue
        members.append(view)
    return CounterContext(opponent_members=tuple(members))


@dataclass
class CounterRecommendation:
    opponent: CounterContext
    teams: list[TeamCandidate] = field(default_factory=list)
    # Damage-formula resolution per team — parallel to ``teams`` when
    # populated. Each entry is a ``DamageResolution`` with predicted
    # win-margin vs the captured opponent. ``None`` for teams whose
    # members aren't all in the simulator's encoded library.
    damage_resolutions: list = field(default_factory=list)
    # Burst-time delta vs opponent (slice #82). Positive = your team's
    # FB opens before the opponent's; negative = you're slower.
    # Parallel to ``teams``. ``None`` when burst-timing is unavailable.
    burst_time_deltas: list = field(default_factory=list)
    # Opponent's own predicted FB-start time (for context display).
    opponent_full_burst_start_sec: Optional[float] = None
    # Element coverage per team (slice #116). Each entry is
    # ``(covered, distinct)`` where ``covered`` is how many distinct
    # opponent elements this team has element advantage over.
    element_coverages: list[tuple[int, int]] = field(default_factory=list)


def recommend_counter(
    session: Session,
    opponent_names: Iterable[str],
    *,
    top_k: int = 5,
    beam_width: int = 200,
    min_power: int = 50_000,
    weights: ScoringWeights = ATTACK_WEIGHTS,
    element_weight: float = 1.5,
    polish: bool = True,
    context: Optional[OptimizerContext] = None,
    mmr_lambda: float = 2.0,
) -> CounterRecommendation:
    """Return the top-K counter-pick teams against the named opponent.

    ``context`` is an optional cached :class:`OptimizerContext`. When
    supplied, reuses the pre-loaded ``owned_views`` / ``all_views``
    instead of hitting the DB.

    ``mmr_lambda`` controls top-K diversity vs raw score (slice #98):
      * 0.0  — pure top-K, no diversity (allows full overlap)
      * 2.0  — default, permissive overlap (1-2 shared members)
      * inf  — hard lockout (== pre-slice-#98 behavior)
    """
    opponent = _resolve_opponent(session, opponent_names, context=context)
    owned = context.owned_views if context is not None else load_owned(session)
    pool = filter_eligible(owned, min_power=min_power, min_skill_sum=effective_min_skill_sum())

    if len(pool) < 5:
        unique: list[TeamCandidate] = []
    else:
        # One beam pass on the full pool gives the candidate set; MMR
        # diversifies the top-K. Slice #98 replaced the per-iteration
        # lockout loop (which forced fully-disjoint cores). Pull more
        # raw candidates than top_k so MMR has options after dedup.
        raw = beam_search_top_teams(
            pool, top_k=max(top_k * 8, 32), beam_width=beam_width, weights=weights,
        )
        if polish:
            raw = [local_search_improve(c, pool, weights=weights) for c in raw]
        rescored = [
            score_counter(list(c.members), opponent, weights=weights, element_weight=element_weight)
            for c in raw
        ]
        rescored = [r for r in rescored if r is not None]
        rescored.sort(key=lambda t: -t.score)
        unique = select_diverse_top_k(rescored, top_k=top_k, mmr_lambda=mmr_lambda)
        # Fallback to lockout when MMR can't reach top_k distinct teams
        # (typical when one dominant comp + polish convergence eats the
        # candidate set). Re-runs beam search with locked-out members.
        if len(unique) < top_k:
            locked: set[str] = set()
            for cand in unique:
                locked.update(m.name for m in cand.members)
            while len(unique) < top_k:
                sub_pool = [c for c in pool if c.name not in locked]
                if len(sub_pool) < 5:
                    break
                extra = beam_search_top_teams(
                    sub_pool, top_k=8, beam_width=beam_width, weights=weights
                )
                if polish:
                    extra = [
                        local_search_improve(c, sub_pool, weights=weights)
                        for c in extra
                    ]
                extra = [
                    score_counter(list(c.members), opponent,
                                  weights=weights, element_weight=element_weight)
                    for c in extra
                ]
                extra = [r for r in extra if r is not None]
                if not extra:
                    break
                best = max(extra, key=lambda t: t.score)
                unique.append(best)
                locked.update(m.name for m in best.members)

    # Damage-formula resolution: for each team, predict win/loss + margin
    # against the captured opponent. Results land in
    # ``CounterRecommendation.damage_resolutions`` parallel to ``teams``.
    # Teams whose members aren't all in the encoded skill library get
    # ``None``.
    from ..simulator.damage import resolve_by_names
    resolutions: list = []
    for cand in unique:
        names = [m.name for m in cand.members]
        opp_names = [m.name for m in opponent.opponent_members]
        try:
            r = resolve_by_names(names, opp_names)
        except Exception:  # pragma: no cover - defensive
            r = None
        resolutions.append(r)
        if r is not None:
            mins = r.seconds_to_clear_defender / 60.0
            verdict = (
                f"predicted clear in {r.seconds_to_clear_defender:.0f}s "
                f"({mins:.1f}m), margin {r.win_margin:+.0f}s"
                if r.attacker_wins_within_5min
                else f"predicted timeout (would need {r.seconds_to_clear_defender:.0f}s)"
            )
            cand.notes.append(verdict)

    # Slice #100 — secondary re-rank by win-margin for ties / close calls.
    # When two teams have similar heuristic scores, prefer the one the
    # damage formula predicts will clear faster. Falls back to heuristic
    # ordering when the formula returns None (some member not encoded)
    # or when scores are clearly different. The combined key:
    #   primary    = heuristic_score + win_margin_bonus
    # where ``win_margin_bonus`` is bounded to +/-3 so it nudges close
    # calls without overwhelming a clearly-better heuristic team.
    def _combined_score(cand: TeamCandidate, res) -> float:
        base = cand.score
        if res is None:
            return base
        if res.attacker_wins_within_5min:
            # +0 to +3 based on clear time (faster = better).
            return base + min(3.0, max(0.0, res.win_margin / 60.0))
        # Predicted timeout: -2 (lower-priority, but not eliminated).
        return base - 2.0

    pairs = sorted(
        zip(unique, resolutions),
        key=lambda pr: -_combined_score(pr[0], pr[1]),
    )
    unique = [p[0] for p in pairs]
    resolutions = [p[1] for p in pairs]

    # Slice #82: per-team burst-time delta vs the opponent's FB-start.
    from ..simulator.timeline import compute_burst_chain_offsets
    opp_weapons = [
        m.weapon_class.value if m.weapon_class else None
        for m in opponent.opponent_members
    ]
    opp_names = [m.name for m in opponent.opponent_members]
    if any(opp_weapons):
        opp_fb_start = compute_burst_chain_offsets(
            opp_weapons, member_names=opp_names
        )[2]
    else:
        opp_fb_start = None

    burst_deltas: list = []
    for cand in unique:
        my_weapons = [
            m.weapon_class.value if m.weapon_class else None
            for m in cand.members
        ]
        my_names = [m.name for m in cand.members]
        if not any(my_weapons) or opp_fb_start is None:
            burst_deltas.append(None)
            continue
        my_fb_start = compute_burst_chain_offsets(
            my_weapons, member_names=my_names
        )[2]
        delta = opp_fb_start - my_fb_start  # positive = you're faster
        burst_deltas.append(delta)
        if abs(delta) >= 0.2:
            faster = "faster" if delta > 0 else "slower"
            cand.notes.append(
                f"burst-time {faster} than opponent by {abs(delta):.2f}s"
            )

    # Slice #116 — per-team element coverage badge.
    coverages = [
        element_coverage(list(cand.members), list(opponent.opponent_members))
        for cand in unique
    ]

    return CounterRecommendation(
        opponent=opponent,
        teams=unique,
        damage_resolutions=resolutions,
        burst_time_deltas=burst_deltas,
        opponent_full_burst_start_sec=opp_fb_start,
        element_coverages=coverages,
    )
