"""Build :class:`CharacterView` records from the local DB."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from sqlmodel import Session, select

from ..data.models import AccountState, Character, Cube, OwnedCharacter
from .models import CharacterView

log = logging.getLogger(__name__)

# Default investment assumption for unowned characters when predicting
# their stats (counter-pick scoring). Top-tier opponents are typically
# fully invested, so we model them as LV600 / MLB (grade 3) / Core 7
# with max skill levels.
_UNOWNED_DEFAULT_LEVEL = 600
_UNOWNED_DEFAULT_GRADE = 3
_UNOWNED_DEFAULT_CORE = 7
_UNOWNED_DEFAULT_SKILL_LEVEL = 10

# In-process cache for the character class lookup (BlablaLink ``class`` field).
_class_cache: dict[str, Optional[str]] = {}


def _lookup_char_class(name: str) -> Optional[str]:
    """Get a character's BlablaLink ``class`` (e.g. "Attacker") from the
    cached roledata JSON. Returns ``None`` if the character isn't mirrored.
    """
    if name in _class_cache:
        return _class_cache[name]
    from ..simulator.base_stats import BaseStats

    try:
        bs = BaseStats.from_name(name)
        _class_cache[name] = bs.char_class or None
    except (FileNotFoundError, KeyError):
        _class_cache[name] = None
    return _class_cache[name]


def _per_character_buffs(owned: OwnedCharacter) -> dict[str, dict[str, int]]:
    """Build the bond/class/mfr buff dicts from per-character CSV data."""
    return {
        "bond_buff": {
            "atk": owned.bond_atk or 0,
            "hp": owned.bond_hp or 0,
            "def": owned.bond_def or 0,
        },
        "class_buff": {
            "atk": owned.class_rank_atk or 0,
            "hp": owned.class_rank_hp or 0,
            "def": owned.class_rank_def or 0,
        },
        "manufacturer_buff": {
            "atk": owned.mfr_rank_atk or 0,
            "hp": owned.mfr_rank_hp or 0,
            "def": owned.mfr_rank_def or 0,
        },
    }


def _equipment_totals(owned: OwnedCharacter) -> dict[str, int]:
    """Sum the 4 OLGear slots' base stats."""
    out = {"atk": 0, "hp": 0, "def": 0}
    for g in (owned.ol_gear or []):
        out["atk"] += g.base_atk or 0
        out["hp"] += g.base_hp or 0
        out["def"] += g.base_def or 0
    return out


def _treasure_stats(owned: OwnedCharacter) -> dict[str, int]:
    return {
        "atk": owned.treasure_atk or 0,
        "hp": owned.treasure_hp or 0,
        "def": owned.treasure_def or 0,
    }


def _cube_stats(cube) -> dict[str, int]:
    if cube is None:
        return {"atk": 0, "hp": 0, "def": 0}
    return {
        "atk": cube.atk or 0,
        "hp": cube.hp or 0,
        "def": cube.def_ or 0,
    }


def _predict_base_stats(
    name: str,
    *,
    level: int,
    grade: int,
    core: int,
    skill1_level: int,
    skill2_level: int,
    burst_skill_level: int,
    account_state: Optional[AccountState] = None,
    char_class: Optional[str] = None,
    manufacturer: Optional[str] = None,
    owned: Optional[OwnedCharacter] = None,
    battle_cube=None,
) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """Return (predicted_atk, hp, def, power) from BlablaLink stat tables.

    Three modes, picked by argument richness:

    1. **Owned + per-char rank stats** (``owned`` provided and
       ``owned.bond_rank`` populated): use compute_full() with
       per-character bond/class/mfr buffs from the v2 CSV import,
       account-wide general research from ``account_state``, and
       equipment + cube + treasure totals — this should reproduce
       the displayed in-game ATK/HP/DEF exactly.

    2. **AccountState only** (``account_state`` + ``char_class``):
       fall back to deriving class/mfr buffs from the user's research
       levels via ``account_buffs.*``. Used for unowned characters.

    3. **Base only**: no account state, no buffs — just level/grade/core
       scaling on the BlablaLink table.

    All four return values are ``None`` if the character isn't
    mirrored locally (collabs / Treasures with name mismatches).
    """
    from ..simulator.base_stats import BaseStats
    from ..simulator import account_buffs

    try:
        bs = BaseStats.from_name(name)
    except (FileNotFoundError, KeyError):
        return None, None, None, None
    try:
        if owned is not None and owned.bond_rank is not None:
            # Mode 1: full per-character data from v2 CSV
            buffs = _per_character_buffs(owned)
            recycle = (
                account_buffs.general_research_buff(account_state)
                if account_state is not None
                else {"atk": 0, "hp": 0, "def": 0}
            )
            stats = bs.compute_full(
                level=level,
                grade=grade,
                core=core,
                equip=_equipment_totals(owned),
                cube=_cube_stats(battle_cube),
                treasure=_treasure_stats(owned),
                bond_buff=buffs["bond_buff"],
                class_buff=buffs["class_buff"],
                manufacturer_buff=buffs["manufacturer_buff"],
                recycle_buff=recycle,
            )
        elif account_state is not None and char_class is not None:
            # Mode 2: AccountState-derived buffs (unowned characters)
            stats = bs.compute_full(
                level=level,
                grade=grade,
                core=core,
                class_buff=account_buffs.class_buff(account_state, char_class),
                manufacturer_buff=account_buffs.manufacturer_buff(account_state, manufacturer),
                recycle_buff=account_buffs.general_research_buff(account_state),
            )
        else:
            # Mode 3: base only
            stats = bs.compute(level=level, grade=grade, core=core)
    except ValueError:
        return None, None, None, None
    power = bs.compute_power(
        level=level,
        grade=grade,
        core=core,
        skill1_level=skill1_level,
        skill2_level=skill2_level,
        ulti_level=burst_skill_level,
    )
    return stats["atk"], stats["hp"], stats["def"], power


def load_owned(session: Session) -> list[CharacterView]:
    """Return one CharacterView per owned Nikke (omits unowned characters)."""
    rows = session.exec(
        select(OwnedCharacter, Character).where(
            OwnedCharacter.character_id == Character.id
        )
    ).all()
    cubes_by_id = {c.id: c for c in session.exec(select(Cube)).all()}
    account_state = session.get(AccountState, 1)  # may be None — predict will skip class/mfr buffs
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
        # Predict base stats from BlablaLink tables using the user's
        # actual investment state. After the v2 CSV import,
        # ``core`` is the proper 0-7 Core Enhancement and
        # ``limit_break`` is reliably populated.
        sync_lv = owned.sync_level or _UNOWNED_DEFAULT_LEVEL
        core_lv = owned.core or 0
        grade_lv = owned.limit_break if owned.limit_break is not None else (
            3 if core_lv >= 1 else 0
        )
        p_atk, p_hp, p_def, p_pow = _predict_base_stats(
            char.name,
            level=sync_lv,
            grade=grade_lv,
            core=core_lv,
            skill1_level=owned.skill1_level or 1,
            skill2_level=owned.skill2_level or 1,
            burst_skill_level=owned.burst_skill_level or 1,
            account_state=account_state,
            char_class=_lookup_char_class(char.name),
            manufacturer=char.manufacturer.value if char.manufacturer else None,
            owned=owned,
            battle_cube=battle_cube,
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
                predicted_base_atk=p_atk,
                predicted_base_hp=p_hp,
                predicted_base_def=p_def,
                predicted_power=p_pow,
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
    account_state = session.get(AccountState, 1)
    out: list[CharacterView] = []
    for char in chars:
        if char.name in owned_by_name:
            out.append(owned_by_name[char.name])
            continue
        # For unowned characters, predict at default high investment so
        # counter-pick scoring has something to compare against. ``power``
        # stays 0 (the user doesn't actually own them); ``predicted_power``
        # carries the predicted value.
        p_atk, p_hp, p_def, p_pow = _predict_base_stats(
            char.name,
            level=_UNOWNED_DEFAULT_LEVEL,
            grade=_UNOWNED_DEFAULT_GRADE,
            core=_UNOWNED_DEFAULT_CORE,
            skill1_level=_UNOWNED_DEFAULT_SKILL_LEVEL,
            skill2_level=_UNOWNED_DEFAULT_SKILL_LEVEL,
            burst_skill_level=_UNOWNED_DEFAULT_SKILL_LEVEL,
            account_state=account_state,
            char_class=_lookup_char_class(char.name),
            manufacturer=char.manufacturer.value if char.manufacturer else None,
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
                owned=False,
                predicted_base_atk=p_atk,
                predicted_base_hp=p_hp,
                predicted_base_def=p_def,
                predicted_power=p_pow,
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
