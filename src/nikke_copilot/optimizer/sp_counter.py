"""SP Arena counter-pick — three attack teams, one per opposing defense.

In SP Arena, a sub-match is decided by team-vs-team in slot order: your
attack team N fights the opponent's defense team N. The simplest sound
strategy is to *counter-pick each defense* with an attack team optimized
against that specific opponent.

This module orchestrates three independent ``recommend_counter`` calls,
one per defense team, and returns them as a structured set. Defense
slots are processed left-to-right; the user assigns recommendations to
attack slots however they prefer.

Attack teams in SP Arena may repeat Nikkes — we don't enforce uniqueness
across the three returned teams. The counter scorer naturally produces
distinct picks because each defense has a different element / archetype
profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from sqlmodel import Session

from .counter import CounterRecommendation, recommend_counter
from .scoring import ATTACK_WEIGHTS, ScoringWeights


@dataclass
class SPCounterRecommendation:
    """Three counter-pick recommendations, one per opposing defense team."""

    rounds: list[CounterRecommendation] = field(default_factory=list)


def recommend_sp_counter(
    session: Session,
    defenses: Sequence[Sequence[str]],
    *,
    top_k: int = 1,
    beam_width: int = 200,
    min_power: int = 50_000,
    weights: ScoringWeights = ATTACK_WEIGHTS,
    element_weight: float = 1.5,
) -> SPCounterRecommendation:
    """Counter-pick each of ``defenses`` independently.

    ``defenses`` is a sequence of 3 lists of opponent character names —
    typically pulled from three ``ArenaMatch`` rows captured before the
    SP Arena match. ``top_k`` is the number of counter teams returned
    PER defense (1 is sufficient for slot assignment; >1 lets the user
    audit alternatives).
    """
    rounds: list[CounterRecommendation] = []
    for defense_names in defenses:
        rec = recommend_counter(
            session,
            defense_names,
            top_k=top_k,
            beam_width=beam_width,
            min_power=min_power,
            weights=weights,
            element_weight=element_weight,
        )
        rounds.append(rec)
    return SPCounterRecommendation(rounds=rounds)


def resolve_defenses_from_capture_ids(
    session: Session, capture_ids: Iterable[int]
) -> list[list[str]]:
    """Pull each capture's ``opponent_team`` for use as a defense input.

    Skips captures with no opponent_team (Champion 'Arena Info' captures
    only store one team — they're not usable as SP-counter defenses).
    Raises if a requested ID doesn't exist.
    """
    from ..data.models import ArenaMatch

    out: list[list[str]] = []
    for cap_id in capture_ids:
        cap = session.get(ArenaMatch, cap_id)
        if cap is None:
            raise ValueError(f"capture {cap_id} not found")
        if not cap.opponent_team:
            raise ValueError(
                f"capture {cap_id} has no opponent_team — Champion captures "
                "store only one team and can't be used as SP-counter defenses"
            )
        out.append([n for n in cap.opponent_team if n])
    return out
