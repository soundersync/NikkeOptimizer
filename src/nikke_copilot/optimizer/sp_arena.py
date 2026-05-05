"""SP Arena solver — 3 attack teams + 3 defense teams.

SP Arena rules (verified from in-game UI + community resources):

  * **Defense:** 3 teams of 5. Each Nikke can appear in **at most one**
    defense team — pairwise-disjoint across the 3 defense teams. Top-4
    finishers advance to Champions Arena.
  * **Attack:** 3 teams of 5. Nikkes **may repeat** across attack teams.
    Best-of-3 sub-matches; attacker wins the overall on 2+ team-battle wins.

For Phase-2 alpha we treat both as "top-3 distinct teams via lockout" — the
defense uniqueness is then a hard guarantee, and the same 3 teams are
offered as attack picks (the user can repeat any of them since the attack
rule allows it). A future slice will add "given opponent's defense, pick
the best 3 attack teams" using the existing counter-pick scorer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session

from .constraints import effective_min_skill_sum
from .loader import filter_eligible, load_owned
from .models import CharacterView, TeamCandidate
from .scoring import (
    ATTACK_WEIGHTS,
    DEFENSE_WEIGHTS,
    ScoringWeights,
)
from .search import beam_search_top_teams, local_search_improve, select_diverse_top_k


SP_TEAM_COUNT = 3


@dataclass
class SPArenaDiagnostics:
    """Roster utilization + constraint diagnostics (slice #83)."""

    eligible_pool_size: int = 0  # roster chars passing min-power+min-skill filter
    attack_unique_count: int = 0  # distinct Nikkes across the 3 attack teams
    defense_unique_count: int = 0  # distinct Nikkes across the 3 defense teams
    overlap_attack_defense: int = 0  # Nikkes appearing on both sides
    defense_uniqueness_violated: bool = False  # safety check
    warnings: list[str] = field(default_factory=list)


@dataclass
class SPArenaRecommendation:
    attack: list[TeamCandidate] = field(default_factory=list)
    defense: list[TeamCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    diagnostics: Optional["SPArenaDiagnostics"] = None


def _lockout_distinct(
    pool: list[CharacterView],
    n: int,
    *,
    beam_width: int,
    weights: ScoringWeights,
    polish: bool,
    notes: list[str],
    label: str,
) -> list[TeamCandidate]:
    """Pick ``n`` pairwise-disjoint teams via iterative lockout search.

    Used for the defense lineup where SP arena enforces uniqueness as a
    hard game rule. Attack is now MMR-diversified (slice #107) to allow
    intentional overlap when the user actually wants to field shared
    cores across attempts.
    """
    teams: list[TeamCandidate] = []
    locked_out: set[str] = set()
    for slot in range(n):
        sub_pool = [c for c in pool if c.name not in locked_out]
        if len(sub_pool) < 5:
            notes.append(
                f"{label} slot {slot + 1}: only {len(sub_pool)} eligible "
                "characters left; lower --min-power to expand"
            )
            break
        raw = beam_search_top_teams(
            sub_pool, top_k=8, beam_width=beam_width, weights=weights
        )
        if polish:
            raw = [local_search_improve(c, sub_pool, weights=weights) for c in raw]
        if not raw:
            notes.append(f"{label} slot {slot + 1}: search returned no valid team")
            break
        best = max(raw, key=lambda t: t.score)
        teams.append(best)
        locked_out.update(m.name for m in best.members)
    teams.sort(key=lambda t: -t.score)
    return teams


def _mmr_distinct(
    pool: list[CharacterView],
    n: int,
    *,
    beam_width: int,
    weights: ScoringWeights,
    polish: bool,
    notes: list[str],
    label: str,
    mmr_lambda: float = 2.0,
) -> list[TeamCandidate]:
    """Pick ``n`` distinct teams with permissive overlap (MMR).

    Slice #107 — SP arena attack is reuse-allowed in-game; surfacing 3
    fully-disjoint cores forces the bottom slots into weaker fillers.
    MMR with default lambda=2.0 keeps the strongest team intact and
    permits 1-2 shared members on lower slots when the base score is
    significantly higher than a fully-disjoint alternative. Falls back
    to lockout when the candidate set isn't diverse enough.
    """
    if len(pool) < 5:
        notes.append(
            f"{label}: only {len(pool)} eligible characters; "
            "lower --min-power to expand"
        )
        return []
    raw = beam_search_top_teams(
        pool, top_k=max(n * 8, 32), beam_width=beam_width, weights=weights,
    )
    if polish:
        raw = [local_search_improve(c, pool, weights=weights) for c in raw]
    raw.sort(key=lambda t: -t.score)
    selected = select_diverse_top_k(raw, top_k=n, mmr_lambda=mmr_lambda)
    if len(selected) < n:
        # Lockout fallback for the remaining slots.
        locked: set[str] = set()
        for cand in selected:
            locked.update(m.name for m in cand.members)
        while len(selected) < n:
            sub_pool = [c for c in pool if c.name not in locked]
            if len(sub_pool) < 5:
                break
            extra = beam_search_top_teams(
                sub_pool, top_k=8, beam_width=beam_width, weights=weights,
            )
            if polish:
                extra = [local_search_improve(c, sub_pool, weights=weights) for c in extra]
            if not extra:
                break
            best = max(extra, key=lambda t: t.score)
            selected.append(best)
            locked.update(m.name for m in best.members)
    selected.sort(key=lambda t: -t.score)
    return selected


def recommend_sp_arena(
    session: Session,
    *,
    beam_width: int = 200,
    min_power: int = 50_000,
    polish: bool = True,
    override_weights: Optional[ScoringWeights] = None,
) -> SPArenaRecommendation:
    """Return 3 attack + 3 defense teams.

    The two searches use **different** weight presets:

      * **Defense** (DEFENSE_WEIGHTS) — strict lockout: defense uniqueness
        is a hard game rule, and durability is heavily weighted.
      * **Attack** (ATTACK_WEIGHTS) — diverse picks via lockout (the game
        actually allows attack reuse, but presenting 3 distinct candidates
        gives the user options; they can repeat any of them).

    ``override_weights`` (slice #104) — when supplied, replaces BOTH
    attack and defense weight presets so the web UI's custom-weight
    panel can tune SP search the same way rookie does.
    """
    owned = load_owned(session)
    pool = filter_eligible(owned, min_power=min_power, min_skill_sum=effective_min_skill_sum())

    defense_w = override_weights or DEFENSE_WEIGHTS
    attack_w = override_weights or ATTACK_WEIGHTS

    notes: list[str] = []
    defense = _lockout_distinct(
        pool, SP_TEAM_COUNT,
        beam_width=beam_width, weights=defense_w,
        polish=polish, notes=notes, label="defense",
    )
    # Slice #107 — attack uses MMR (overlap allowed) since the game lets
    # users repeat Nikkes across attack attempts. Defense keeps lockout
    # because uniqueness is a hard game rule.
    attack = _mmr_distinct(
        pool, SP_TEAM_COUNT,
        beam_width=beam_width, weights=attack_w,
        polish=polish, notes=notes, label="attack",
    )
    diagnostics = _diagnose(pool, attack, defense)
    if diagnostics.warnings:
        notes.extend(diagnostics.warnings)

    return SPArenaRecommendation(
        attack=attack, defense=defense, notes=notes, diagnostics=diagnostics
    )


def _diagnose(
    pool: list[CharacterView],
    attack: list[TeamCandidate],
    defense: list[TeamCandidate],
) -> "SPArenaDiagnostics":
    """Compute roster utilization counters + constraint sanity checks."""
    attack_names: set[str] = set()
    for t in attack:
        for m in t.members:
            attack_names.add(m.name)
    # For defense, also verify the hard uniqueness rule (each Nikke in
    # at most one defense team).
    defense_names: set[str] = set()
    seen_in_team: dict[str, int] = {}
    violated = False
    for idx, t in enumerate(defense):
        for m in t.members:
            if m.name in seen_in_team:
                violated = True
            seen_in_team[m.name] = idx
            defense_names.add(m.name)

    overlap = attack_names & defense_names
    pool_size = len(pool)

    warnings: list[str] = []
    if violated:
        warnings.append(
            "DEFENSE UNIQUENESS VIOLATED — same Nikke in 2+ defense teams "
            "(should not happen; report this bug)"
        )
    if pool_size < 25:
        warnings.append(
            f"eligible pool only {pool_size} Nikkes — SP Arena ideally "
            "wants ≥15 unique-defense + ≥5 attack reuses (≥25 ideal); "
            "lower --min-power or invest in more characters"
        )
    if len(defense_names) < SP_TEAM_COUNT * 5:
        warnings.append(
            f"defense lineup only {len(defense_names)} unique Nikkes "
            f"(expected {SP_TEAM_COUNT * 5}) — uniqueness constraint "
            "or pool size forced incomplete defense"
        )
    if overlap:
        # Not a violation — attack reuse is allowed and can include
        # defense Nikkes — but worth surfacing in case the user wants
        # to keep them disjoint for safety.
        warnings.append(
            f"{len(overlap)} Nikkes appear on both attack and defense "
            "(allowed by SP rules, but consider keeping them disjoint)"
        )

    return SPArenaDiagnostics(
        eligible_pool_size=pool_size,
        attack_unique_count=len(attack_names),
        defense_unique_count=len(defense_names),
        overlap_attack_defense=len(overlap),
        defense_uniqueness_violated=violated,
        warnings=warnings,
    )
