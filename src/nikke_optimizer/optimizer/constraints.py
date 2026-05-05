"""Hard constraints — a team that fails any of these is unrankable."""

from __future__ import annotations

import os
from typing import Iterable, Optional

from .models import CharacterView


TEAM_SIZE = 5


def has_burst_chain(team: Iterable[CharacterView]) -> bool:
    """True iff the team can chain B1 → B2 → B3 to enter Full Burst.

    Concretely: at least one member is in each of the three burst position
    buckets (1, 2, 3). FLEX members count for whichever bucket has a deficit.

    The check is bucket-existence only — it does NOT enforce a 1/1/3 vs
    2/1/2 split. Most meta teams use 1/1/3, but 2/1/2 is also valid (e.g.,
    Liter + Dorothy + Crown + Modernia + Red Hood).
    """
    have = {"1": 0, "2": 0, "3": 0}
    flex = 0
    for m in team:
        pos = m.burst_position
        if pos in have:
            have[pos] += 1
        else:
            flex += 1
    # Deficit per bucket
    deficit = sum(max(0, 1 - have[k]) for k in have)
    return flex >= deficit


def is_correct_size(team: Iterable[CharacterView]) -> bool:
    return len(list(team)) == TEAM_SIZE


def has_unique_members(team: Iterable[CharacterView]) -> bool:
    names = [m.name for m in team]
    return len(set(names)) == len(names)


# Minimum total skill investment per member — sum of (s1, s2, burst) levels.
# Mean of 6 (= 18 total) is the floor — captures "this character is at least
# moderately built." Below this, the soft `investment` scorer wasn't enough
# to keep undertrained Nikkes (Epinel 1/1/501, Rapunzel: PG 1/1/1, Dolla
# 4/4/4 — observed 2026-04-27) out of top recommendations. Configurable
# via NIKKE_OPTIMIZER_MIN_SKILL_SUM env var for power users.
DEFAULT_MIN_SKILL_SUM = 18


def effective_min_skill_sum() -> int:
    """Return the active investment floor, honoring the env override.

    Reads ``NIKKE_OPTIMIZER_MIN_SKILL_SUM`` at call time so power users can
    relax the floor (``=0`` to disable; ``=12`` to allow level-4 averages)
    or tighten it (``=21`` to require avg-7 skills) without code changes.
    Falls back to :data:`DEFAULT_MIN_SKILL_SUM` on missing/invalid values.
    """
    raw = os.environ.get("NIKKE_OPTIMIZER_MIN_SKILL_SUM")
    if raw is None or raw.strip() == "":
        return DEFAULT_MIN_SKILL_SUM
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MIN_SKILL_SUM
    return max(0, value)


def has_minimum_investment(
    team: Iterable[CharacterView],
    *,
    min_skill_sum: int = DEFAULT_MIN_SKILL_SUM,
) -> bool:
    """All members must have ``s1 + s2 + burst >= min_skill_sum``.

    Soft penalty was insufficient — undertrained Nikkes still landed in
    top-K because their power/synergy outweighed the investment penalty.
    Hard veto here removes them from consideration entirely.
    """
    for m in team:
        total = (m.skill1_level or 0) + (m.skill2_level or 0) + (m.burst_skill_level or 0)
        if total < min_skill_sum:
            return False
    return True


def is_valid_team(
    team: Iterable[CharacterView],
    *,
    enforce_minimum_investment: bool = True,
    min_skill_sum: Optional[int] = None,
) -> bool:
    """Run every hard check; True only if all pass.

    ``enforce_minimum_investment=False`` disables the skill-floor veto
    (used by tests + the explainer mode where we want to ask "why isn't
    this team in top-K" for ANY team, including invalid ones).

    ``min_skill_sum=None`` resolves to :func:`effective_min_skill_sum`,
    which honors the ``NIKKE_OPTIMIZER_MIN_SKILL_SUM`` env override.
    """
    members = list(team)
    base = (
        is_correct_size(members)
        and has_unique_members(members)
        and has_burst_chain(members)
    )
    if not base:
        return False
    floor = effective_min_skill_sum() if min_skill_sum is None else min_skill_sum
    if enforce_minimum_investment and not has_minimum_investment(
        members, min_skill_sum=floor
    ):
        return False
    return True
