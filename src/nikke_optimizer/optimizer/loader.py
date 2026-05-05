"""Build :class:`CharacterView` records from the local DB."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from sqlmodel import Session, select

from ..data.models import Character, Cube, OwnedCharacter
from .models import CharacterView

log = logging.getLogger(__name__)


def load_owned(session: Session) -> list[CharacterView]:
    """Return one CharacterView per owned Nikke (omits unowned characters)."""
    rows = session.exec(
        select(OwnedCharacter, Character).where(
            OwnedCharacter.character_id == Character.id
        )
    ).all()
    cubes_by_id = {c.id: c for c in session.exec(select(Cube)).all()}
    out: list[CharacterView] = []
    for owned, char in rows:
        arena_cube = cubes_by_id.get(owned.arena_cube_id) if owned.arena_cube_id else None
        battle_cube = cubes_by_id.get(owned.battle_cube_id) if owned.battle_cube_id else None
        # Treasure (Favorite Item) unlocked iff Doll/Treasure rarity is
        # SSR (the explicit Treasure marker per the 2026-04-29 CSV
        # format) and phase >= 1.
        treasure_unlocked = (
            (owned.treasure_rarity or "").upper() == "SSR"
            and (owned.treasure_phase or 0) >= 1
        )
        out.append(
            CharacterView(
                name=char.name,
                rarity=char.rarity,
                element=char.element,
                weapon_class=char.weapon_class,
                burst_type=char.burst_type,
                manufacturer=char.manufacturer,
                role_tags=tuple(char.role_tags or ()),
                owned=True,
                power=owned.power or 0,
                sync_level=owned.sync_level,
                skill1_level=owned.skill1_level or 1,
                skill2_level=owned.skill2_level or 1,
                burst_skill_level=owned.burst_skill_level or 1,
                arena_cube_name=arena_cube.name if arena_cube else None,
                battle_cube_name=battle_cube.name if battle_cube else None,
                is_treasure_unlocked=treasure_unlocked,
            )
        )
    log.info("loaded %d owned character views", len(out))
    return out


def load_all(session: Session) -> list[CharacterView]:
    """Return every Character — owned and unowned. Useful for opponent
    counter-pick scoring where we know the opponent has access to characters
    the user doesn't own."""
    chars = session.exec(select(Character)).all()
    owned_by_name = {v.name: v for v in load_owned(session)}
    out: list[CharacterView] = []
    for char in chars:
        if char.name in owned_by_name:
            out.append(owned_by_name[char.name])
            continue
        out.append(
            CharacterView(
                name=char.name,
                rarity=char.rarity,
                element=char.element,
                weapon_class=char.weapon_class,
                burst_type=char.burst_type,
                manufacturer=char.manufacturer,
                role_tags=tuple(char.role_tags or ()),
                owned=False,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Optimizer context — cached pre-loaded views for repeated optimizer calls
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizerContext:
    """Pre-loaded roster snapshot for repeated optimizer calls.

    Building :class:`CharacterView` lists hits the DB and constructs
    ~200 dataclass instances (~30ms cold per call). Beam search itself
    dominates counter-pick latency (~1s for top-5), so caching view
    loading saves ~3% per call rather than the speculative 3× — the
    foundational benefit is keeping the call surface clean for future
    work that might cache more aggressively (e.g. precomputed pair-
    score table, per-pool partial-team enumeration).

    Construct once with :meth:`from_session` (or :func:`get_context`)
    and pass into ``recommend_counter`` / ``recommend_rookie`` as
    needed.
    """

    owned_views: list[CharacterView] = field(default_factory=list)
    all_views: list[CharacterView] = field(default_factory=list)

    @classmethod
    def from_session(cls, session: Session) -> "OptimizerContext":
        return cls(
            owned_views=load_owned(session),
            all_views=load_all(session),
        )


# Module-level cache of (db_path → (mtime, context)). The web app and
# CLI both call into the optimizer through a Session; we key on the
# resolved path of the DB file because that's what an external user
# would change to invalidate (e.g., re-importing the CSV).
_CONTEXT_CACHE: dict[Path, tuple[float, OptimizerContext]] = {}


def get_context(
    session: Session,
    *,
    db_path: Optional[Path] = None,
) -> OptimizerContext:
    """Return a cached :class:`OptimizerContext`, rebuilding when stale.

    ``db_path`` is the SQLite file backing the session — its mtime is
    the freshness signal. When omitted, no caching happens (fresh build
    every call) so tests with in-memory engines are unaffected. The
    cache invalidates on any mtime change (CSV re-import bumps it).
    """
    if db_path is None:
        return OptimizerContext.from_session(session)
    try:
        path = db_path.resolve()
        mtime = path.stat().st_mtime
    except (OSError, AttributeError):
        return OptimizerContext.from_session(session)
    cached = _CONTEXT_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    ctx = OptimizerContext.from_session(session)
    _CONTEXT_CACHE[path] = (mtime, ctx)
    return ctx


def invalidate_context_cache() -> None:
    """Drop all cached :class:`OptimizerContext` entries (used by tests)."""
    _CONTEXT_CACHE.clear()


def filter_eligible(
    views: Iterable[CharacterView],
    *,
    min_power: int = 0,
    min_skill_sum: int = 0,
    require_owned: bool = True,
    exclude: Optional[Iterable[str]] = None,
) -> list[CharacterView]:
    """Apply common pre-search filters.

    The optimizer can choke on hundreds of rarely-used characters; the
    ``min_power`` filter knocks out characters the user has barely invested
    in (usually low-rarity or never-leveled). ``min_skill_sum`` filters
    out undertrained Nikkes (skill1+skill2+burst < threshold) — the same
    floor enforced by ``constraints.has_minimum_investment``, applied
    pre-search so beam search doesn't fill its width with low-skill
    candidates and then have every full team fail validation.
    ``exclude`` is used by the Champions Arena solver to honor
    unique-Nikke constraints across teams.
    """
    excl = set(exclude or ())
    out: list[CharacterView] = []
    for v in views:
        if require_owned and not v.owned:
            continue
        if v.power < min_power:
            continue
        if min_skill_sum > 0:
            total = (v.skill1_level or 0) + (v.skill2_level or 0) + (v.burst_skill_level or 0)
            if total < min_skill_sum:
                continue
        if v.name in excl:
            continue
        out.append(v)
    return out
