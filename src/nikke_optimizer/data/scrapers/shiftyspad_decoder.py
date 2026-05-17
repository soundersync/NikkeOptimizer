"""ShiftyPad data decoder — turn raw API responses into game-meaning.

The BlablaLink API exposes raw tids and option_ids; the in-game UI
renders them via a handful of static lookup tables hosted on the CDN.
This module loads cached copies of those tables and provides
high-level helpers that the importer can call.

Tables (all cached under ``<user_data_dir>/blablalink/tables/``):

  - ``equipment_definitions.json`` (yu-75): every OL gear tid → name,
    tier, base ATK/HP/DEF.
  - ``state_effect_groups.json`` (bl-25): groups option_ids 5-at-a-time
    by bonus type ("Increase ATK" group has 5 progressive option_ids).
    Not strictly needed for percent decoding (state_effects in each
    detail response carries the percent directly) but useful for the
    canonical English bonus_type name.
  - ``bond_levels.json`` (qe-66): per-class flat HP/ATK/DEF buff per
    bond rank 1-40.
  - ``cubes/<tid>.json`` (per-cube; e.g. qx-26, te-95): each cube's
    per-level ATK/HP/DEF arrays.
  - ``favorite_items/<tid>.json`` (per-doll/treasure; e.g. hs-19):
    each item's per-level ATK/HP/DEF arrays + grade.

Cache files are populated automatically by the scraper when their
underlying CDN responses fire during normal page navigation (see
``ShiftyPadFetcher`` — extended in this slice to persist them).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from platformdirs import user_data_dir

from ..enums import OLBonusType

log = logging.getLogger(__name__)


def tables_dir() -> Path:
    base = Path(user_data_dir("NikkeOptimizer", appauthor=False)) / "blablalink" / "tables"
    base.mkdir(parents=True, exist_ok=True)
    (base / "cubes").mkdir(exist_ok=True)
    (base / "favorite_items").mkdir(exist_ok=True)
    return base


@lru_cache(maxsize=1)
def _equipment_table() -> dict[int, dict[str, Any]]:
    path = tables_dir() / "equipment_definitions.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    out: dict[int, dict[str, Any]] = {}
    for r in data.get("records") or []:
        try:
            out[int(r["id"])] = r
        except (KeyError, TypeError, ValueError):
            continue
    return out


@lru_cache(maxsize=1)
def _bond_table() -> dict[int, dict[str, int]]:
    path = tables_dir() / "bond_levels.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    return {int(r["attractive_level"]): r for r in data.get("records") or []}


def _load_per_tid(subdir: str, tid: int) -> Optional[dict[str, Any]]:
    path = tables_dir() / subdir / f"{tid}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Function type → OLBonusType mapping
# ---------------------------------------------------------------------------

# BlablaLink's state_effects use machine-readable function_type names.
# Map these to our existing OLBonusType enum so we stay consistent with
# what the CSV importer produces.
_FUNCTION_TYPE_TO_BONUS: dict[str, OLBonusType] = {
    "StatAtk": OLBonusType.ATK,
    "IncElementDmg": OLBonusType.ELEMENT_DAMAGE,
    "StatChargeTime": OLBonusType.CHARGE_SPEED,
    "StatChargeDamage": OLBonusType.CHARGE_DAMAGE,
    "StatAmmoLoad": OLBonusType.MAX_AMMUNITION_CAPACITY,
    "StatCriticalDamage": OLBonusType.CRITICAL_DAMAGE,
    "StatCritical": OLBonusType.CRITICAL_RATE,
    "StatAccuracyCircle": OLBonusType.HIT_RATE,
    "StatDef": OLBonusType.DEFENSE,
    "StatHp": OLBonusType.HP,
}

# Human-readable label used by the CSV format (kept in raw_label).
_FUNCTION_TYPE_TO_LABEL: dict[str, str] = {
    "StatAtk": "Increase ATK",
    "IncElementDmg": "Increase Element Damage Dealt",
    "StatChargeTime": "Increase Charge Speed",
    "StatChargeDamage": "Increase Charge Damage",
    "StatAmmoLoad": "Increase Max Ammunition Capacity",
    "StatCriticalDamage": "Increase Critical Damage",
    "StatCritical": "Increase Critical Rate",
    "StatAccuracyCircle": "Increase Hit Rate",
    "StatDef": "Increase DEF",
    "StatHp": "Increase HP",
}


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------


@dataclass
class GearPieceInfo:
    tid: int
    lv: int
    name: str
    tier: str             # "T1".."T10"
    base_hp: int
    base_atk: int
    base_def: int

    @property
    def scale(self) -> float:
        """Level scaling factor — validated against in-game stats:
        ``displayed = round(base × (1 + lv × 0.1))``.
        """
        return 1 + self.lv * 0.1

    def leveled(self) -> dict[str, int]:
        # Game uses half-up rounding (not Python's default banker's
        # rounding). Validated against screenshot: V Matter Boots HP
        # 36887 × 1.5 = 55330.5 displays as 55331.
        # Multiplying first by 10 keeps everything integer.
        m = 10 + self.lv  # 10..15
        return {
            "hp": (self.base_hp * m + 5) // 10,
            "atk": (self.base_atk * m + 5) // 10,
            "def": (self.base_def * m + 5) // 10,
        }


@dataclass
class GearBonus:
    option_id: int
    bonus_type: Optional[OLBonusType]
    raw_label: str
    percent: Optional[float]   # signed; e.g. -3.45 for charge time

    @property
    def is_known(self) -> bool:
        return self.bonus_type is not None


def decode_gear_piece(tid: int, lv: int) -> Optional[GearPieceInfo]:
    """Resolve an equipment tid + level to its name + leveled stats.

    Returns ``None`` if the tid isn't in the local equipment table —
    add the entry by re-scraping (the CDN file will land in cache
    automatically when navigating to a Nikke that has this piece).
    """
    table = _equipment_table()
    rec = table.get(tid)
    if rec is None:
        return None
    stats = {s["stat_type"]: s["stat_value"]
             for s in rec.get("stat") or []
             if s.get("stat_type") and s["stat_type"] != "None"}
    return GearPieceInfo(
        tid=tid,
        lv=lv,
        name=rec.get("name_localkey") or f"tid={tid}",
        tier=rec.get("item_rare") or "?",
        base_hp=stats.get("Hp", 0),
        base_atk=stats.get("Atk", 0),
        base_def=stats.get("Defence", 0),  # British spelling in source
    )


def decode_gear_bonus(option_id: int, state_effects: list[dict]) -> Optional[GearBonus]:
    """Find ``option_id`` in the response's ``state_effects`` array and
    extract its bonus type + signed percent.

    ``state_effects`` is the top-level field returned alongside
    ``character_details`` — each entry has ``id`` (state_effect_id ==
    option_id) and ``function_details`` carrying the percent.

    Returns ``None`` when the option_id isn't in state_effects (an
    empty/unrolled gear slot) or when the function_type can't be
    mapped to a known OLBonusType.
    """
    if not option_id:
        return None
    for se in state_effects:
        if str(se.get("id")) != str(option_id):
            continue
        fd = (se.get("function_details") or [None])[0]
        if fd is None:
            return None
        ftype = fd.get("function_type") or ""
        fvalue = fd.get("function_value")
        if fvalue is None:
            return None
        bonus_type = _FUNCTION_TYPE_TO_BONUS.get(ftype)
        label = _FUNCTION_TYPE_TO_LABEL.get(ftype, ftype)
        # Encoded as integer × 100; charge time is stored negative
        # (means "less charge time" = faster) — flip sign so positive =
        # better, matching how the CSV records "Increase Charge Speed".
        percent = abs(fvalue) / 100.0
        return GearBonus(
            option_id=option_id,
            bonus_type=bonus_type,
            raw_label=label,
            percent=percent,
        )
    return None


@dataclass
class CubeInfo:
    tid: int
    lv: int
    name: str
    rarity: str
    cls: str
    atk: int
    hp: int
    def_: int


def decode_cube(tid: int, lv: int) -> Optional[CubeInfo]:
    """Resolve a harmony cube tid + level → name + leveled stats.

    Cube definitions ship per-tid JSON files (one per cube). The
    scraper persists them to cache when they load during navigation —
    so cubes equipped by any previously-scraped character become
    decodable.
    """
    if not tid:
        return None
    raw = _load_per_tid("cubes", tid)
    if raw is None:
        return None
    # arrays are 0-indexed by level; clamp to range.
    idx = max(0, min(lv, len(raw.get("atk", [])) - 1))
    return CubeInfo(
        tid=tid,
        lv=lv,
        name=raw.get("name_localkey") or f"cube tid={tid}",
        rarity=raw.get("item_rare") or "?",
        cls=raw.get("class") or "All",
        atk=(raw.get("atk") or [0])[idx] if raw.get("atk") else 0,
        hp=(raw.get("hp") or [0])[idx] if raw.get("hp") else 0,
        def_=(raw.get("def") or [0])[idx] if raw.get("def") else 0,
    )


@dataclass
class FavoriteItemInfo:
    tid: int
    lv: int
    name: str
    rarity: str  # SSR = Treasure, SR/R = Doll
    kind: str    # "Treasure" or "Doll"
    grade: int   # 0-3 (Treasure) or 0+ (Doll)
    atk: int
    hp: int
    def_: int


def decode_favorite_item(tid: int, lv: int) -> Optional[FavoriteItemInfo]:
    """Resolve a favorite item (Treasure/Doll) tid + level → info."""
    if not tid:
        return None
    raw = _load_per_tid("favorite_items", tid)
    if raw is None:
        return None
    idx = max(0, min(lv, len(raw.get("atk", [])) - 1))
    rarity = raw.get("favorite_rare") or "?"
    kind = "Treasure" if rarity == "SSR" else "Doll"
    grade_arr = raw.get("grade") or [0]
    return FavoriteItemInfo(
        tid=tid,
        lv=lv,
        name=raw.get("name_localkey") or f"favorite tid={tid}",
        rarity=rarity,
        kind=kind,
        grade=grade_arr[idx] if idx < len(grade_arr) else 0,
        atk=(raw.get("atk") or [0])[idx] if raw.get("atk") else 0,
        hp=(raw.get("hp") or [0])[idx] if raw.get("hp") else 0,
        def_=(raw.get("def") or [0])[idx] if raw.get("def") else 0,
    )


def decode_bond_buff(rank: int, char_class: str) -> dict[str, int]:
    """Look up the per-class flat HP/ATK/DEF buff from bond rank.

    ``char_class`` is "Attacker" / "Defender" / "Supporter" — matches
    ``Character.role_tags[0]`` in our schema. Returns ``{hp, atk, def}``
    integers (zero if rank or class unknown).
    """
    if not rank:
        return {"hp": 0, "atk": 0, "def": 0}
    rec = _bond_table().get(rank)
    if rec is None:
        return {"hp": 0, "atk": 0, "def": 0}
    cls = (char_class or "").lower()
    prefix = cls if cls in ("attacker", "defender", "supporter") else None
    if prefix is None:
        return {"hp": 0, "atk": 0, "def": 0}
    return {
        "hp": rec.get(f"{prefix}_hp_rate", 0),
        "atk": rec.get(f"{prefix}_attack_rate", 0),
        "def": rec.get(f"{prefix}_defence_rate", 0),
    }


# ---------------------------------------------------------------------------
# Cache-writer (used by ShiftyPadFetcher when CDN files fire)
# ---------------------------------------------------------------------------


def maybe_persist_table_response(url: str, payload: Any) -> Optional[str]:
    """If ``payload`` is one of the known static tables, save it to
    cache and return the cache-relative path. Otherwise return None.

    This lets ``ShiftyPadFetcher`` opportunistically persist any
    relevant CDN file that loads during a normal page navigation,
    without the caller needing to know about specific URL patterns.
    """
    if not isinstance(payload, dict):
        # The list-shape master tables (ug-00, kx-19, kw-85, etc.) are
        # already mirrored elsewhere or aren't load-bearing for the
        # decoder — skip.
        return None
    # Per-cube definition.
    if payload.get("item_type") == "HarmonyCube":
        tid = payload.get("id")
        if isinstance(tid, int):
            path = tables_dir() / "cubes" / f"{tid}.json"
            if not path.exists():
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                log.info("cached cube tid=%s → %s", tid, path)
            return str(path)
    # Per-favorite-item (Doll / Treasure) definition.
    if payload.get("favorite_type"):
        tid = payload.get("id")
        if isinstance(tid, int):
            path = tables_dir() / "favorite_items" / f"{tid}.json"
            if not path.exists():
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                log.info("cached favorite_item tid=%s → %s", tid, path)
            return str(path)
    # Static master tables (records + version).
    records = payload.get("records")
    if isinstance(records, list) and records:
        sample = records[0] if isinstance(records[0], dict) else {}
        if "item_type" in sample and sample.get("item_type") == "Equip":
            target = tables_dir() / "equipment_definitions.json"
        elif "attractive_level" in sample:
            target = tables_dir() / "bond_levels.json"
        else:
            return None
        if not target.exists():
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            log.info("cached %s (%d records)", target.name, len(records))
        return str(target)
    return None
