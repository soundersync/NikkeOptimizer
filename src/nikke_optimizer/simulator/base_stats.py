"""Per-character base stat tables, sourced from BlablaLink's roledata.

BlablaLink's character pages compute live stats with this formula
(verified by reading the minified bundle and confirmed against their
displayed numbers):

For each stat ∈ {attack, hp, defence}::

    F = floor(level_<stat>[level - 1] * (1 + grade * grade_ratio * 1e-4)
              + grade * grade_<stat>)
    base = round(F * (1 + core * core_<stat> * 1e-4))

``level_<stat>`` is a 1200-element array per character; ``grade_*`` and
``core_*`` come from the character's ``stat_enhance_detail`` block.
The full formula adds equipment, harmony cube, treasure (favorite
item) and class/enterprise/recycle buffs on top — those are
*caller-supplied*, since they depend on user state that BlablaLink
doesn't know about. This module returns the pre-equipment baseline.

For the combat-power closed-form (the "Power" number BlablaLink shows)
see :meth:`BaseStats.compute_power`.

Data is loaded lazily from
``<user_data_dir>/blablalink/<lang>/roledata/<resource_id>-v2-<lang>.json``
populated by ``nikkeoptimizer fetch-roledata``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..data.scrapers.blablalink import (
    DEFAULT_LANG,
    cache_path_for_nikke_list,
    cache_path_for_roledata,
    default_cache_dir,
)

# Combat-power constants from the BlablaLink JS bundle. Names match
# the function-internal lookups (``ja``, ``Ba``, ``Ia``, ``Ea``, etc.)
# so the formula is easy to compare against the source.
_POWER_DEF_WEIGHT = 100      # ja: HP-side weight on DEF
_POWER_HP_FACTOR = 0.7       # Ba: outer factor on (HP + DEF*100)
_POWER_ATK_FACTOR = 18       # Ia: outer factor on crit-adjusted ATK
_POWER_BASE_MULT = 1.3       # Ea: base of the skill-level multiplier
_POWER_SKILL1 = 0.01         # $a: ATK-skill-1 contribution per level
_POWER_SKILL2 = 0.01         # Sa: ATK-skill-2 contribution per level
_POWER_ULTI = 0.02           # Ca: burst-skill contribution per level


@dataclass(frozen=True)
class BaseStats:
    """Pre-equipment base stats for a single character.

    Constructed via :meth:`from_roledata` (parsed JSON) or
    :meth:`from_cache` (resource_id + cache lookup). Use
    :meth:`compute` to apply level/grade/core; :meth:`compute_power`
    to get the combat-power readout.
    """

    resource_id: int
    name: str
    rare: str
    char_class: str

    # Per-level lists, length 1200. Index = level - 1.
    attack_list: tuple[int, ...]
    hp_list: tuple[int, ...]
    defence_list: tuple[int, ...]

    # Limit-break (grade) modifiers
    grade_ratio: int       # basis points; multiplicative on level base
    grade_attack: int      # flat per grade level
    grade_hp: int
    grade_defence: int

    # Core enhancement multipliers (basis points; per core level)
    core_attack: int
    core_hp: int
    core_defence: int

    # Crit (basis points: e.g. 1500 = 15%)
    critical_ratio: int
    critical_damage: int

    @property
    def max_level(self) -> int:
        return len(self.attack_list)

    @classmethod
    def from_roledata(cls, payload: dict) -> "BaseStats":
        """Build a :class:`BaseStats` from a parsed roledata JSON."""
        sed = payload["stat_enhance_detail"]
        name = payload.get("name_localkey")
        if isinstance(name, dict):
            name = name.get("name", "")
        return cls(
            resource_id=int(payload["resource_id"]),
            name=str(name or ""),
            rare=str(payload.get("original_rare", "")),
            char_class=str(payload.get("class", "")),
            attack_list=tuple(payload["character_level_attack_list"]),
            hp_list=tuple(payload["character_level_hp_list"]),
            defence_list=tuple(payload["character_level_defence_list"]),
            grade_ratio=int(sed["grade_ratio"]),
            grade_attack=int(sed["grade_attack"]),
            grade_hp=int(sed["grade_hp"]),
            grade_defence=int(sed["grade_defence"]),
            core_attack=int(sed["core_attack"]),
            core_hp=int(sed["core_hp"]),
            core_defence=int(sed["core_defence"]),
            critical_ratio=int(payload["critical_ratio"]),
            critical_damage=int(payload["critical_damage"]),
        )

    @classmethod
    def from_cache(
        cls,
        resource_id: int | str,
        *,
        lang: str = DEFAULT_LANG,
        cache_dir: Optional[Path] = None,
    ) -> "BaseStats":
        """Load from the on-disk cache populated by ``fetch-roledata``."""
        path = cache_path_for_roledata(str(resource_id), lang, cache_dir)
        if not path.is_file():
            raise FileNotFoundError(
                f"No roledata cached for resource_id={resource_id} (lang={lang}). "
                f"Run `nikkeoptimizer fetch-roledata {resource_id}` first."
            )
        return cls.from_roledata(json.loads(path.read_text()))

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        lang: str = DEFAULT_LANG,
        cache_dir: Optional[Path] = None,
    ) -> "BaseStats":
        """Load by character display name (case-insensitive exact match).

        Looks up the resource_id in the cached nikke_list, then loads
        that character's roledata. Raises :class:`KeyError` if the
        name doesn't resolve, :class:`FileNotFoundError` if the
        roledata isn't mirrored yet.
        """
        rid = resolve_resource_id_by_name(name, lang=lang, cache_dir=cache_dir)
        if rid is None:
            raise KeyError(f"No NIKKE matched name {name!r} in the nikke_list (lang={lang}).")
        return cls.from_cache(rid, lang=lang, cache_dir=cache_dir)

    def compute(self, level: int, grade: int = 0, core: int = 0) -> dict[str, int]:
        """Return ``{atk, hp, def}`` at the given level/grade/core.

        Excludes equipment, harmony cube, treasure (favorite item),
        and class/enterprise/recycle buffs — those layer on top in
        the caller, since they depend on user state.

        Args:
            level: 1..max_level (typically 1..1200)
            grade: 0..3 (limit-break stars; SR caps at 2, SSR at 3)
            core:  0..7 (Core Enhancement; SSR-only post-MLB)
        """
        if not 1 <= level <= self.max_level:
            raise ValueError(f"level {level} out of range [1, {self.max_level}]")
        if grade < 0:
            raise ValueError(f"grade {grade} cannot be negative")
        if core < 0:
            raise ValueError(f"core {core} cannot be negative")
        return {
            "atk": self._compute_one(
                self.attack_list[level - 1], self.grade_attack, self.core_attack, grade, core
            ),
            "hp": self._compute_one(
                self.hp_list[level - 1], self.grade_hp, self.core_hp, grade, core
            ),
            "def": self._compute_one(
                self.defence_list[level - 1],
                self.grade_defence,
                self.core_defence,
                grade,
                core,
            ),
        }

    def _compute_one(
        self,
        level_value: int,
        grade_flat: int,
        core_bp: int,
        grade: int,
        core: int,
    ) -> int:
        F = math.floor(
            level_value * (1 + grade * self.grade_ratio * 1e-4) + grade * grade_flat
        )
        return round(F * (1 + core * core_bp * 1e-4))

    def compute_full(
        self,
        level: int,
        grade: int = 0,
        core: int = 0,
        *,
        equip: Optional[dict[str, int]] = None,
        cube: Optional[dict[str, int]] = None,
        treasure: Optional[dict[str, int]] = None,
        class_buff: Optional[dict[str, int]] = None,
        manufacturer_buff: Optional[dict[str, int]] = None,
        recycle_buff: Optional[dict[str, int]] = None,
        bond_buff: Optional[dict[str, int]] = None,
    ) -> dict[str, int]:
        """Apply the complete BlablaLink formula and return the user-facing
        ATK/HP/DEF that NIKKE displays on the character page.

        All buff dicts are ``{atk, hp, def}`` integers. Any omitted dict
        defaults to zero.

        Verified against in-game numbers for Snow White: Heavy Arms,
        Rapi: Red Hood, and Moran (May 2026) — matches to the digit when
        all 7 inputs are supplied:

          - level, grade, core
          - equipment (sum of 4 gear-slot ATK/HP/DEF)
          - harmony cube (active loadout)
          - treasure / favorite-item / doll
          - bond-level buff (Attractive)
          - class buff (Attacker / Defender / Supporter research)
          - manufacturer buff (Pilgrim / Elysion / Tetra / Missilis research)
          - recycle buff (Recycle Room → General Research)
        """
        z = {"atk": 0, "hp": 0, "def": 0}
        equip = equip or z
        cube = cube or z
        treasure = treasure or z
        class_buff = class_buff or z
        manufacturer_buff = manufacturer_buff or z
        recycle_buff = recycle_buff or z
        bond_buff = bond_buff or z

        out = {}
        for stat, level_list, grade_flat, core_bp in (
            ("atk", self.attack_list,  self.grade_attack,  self.core_attack),
            ("hp",  self.hp_list,      self.grade_hp,      self.core_hp),
            ("def", self.defence_list, self.grade_defence, self.core_defence),
        ):
            if not 1 <= level <= self.max_level:
                raise ValueError(f"level {level} out of range [1, {self.max_level}]")
            F = math.floor(
                level_list[level - 1] * (1 + grade * self.grade_ratio * 1e-4)
                + grade * grade_flat
            )
            flat = math.floor(class_buff[stat] + manufacturer_buff[stat] + recycle_buff[stat])
            attr = round(bond_buff[stat])
            base = round((F + flat + attr) * (1 + core * core_bp * 1e-4))
            out[stat] = base + equip[stat] + cube[stat] + treasure[stat]
        return out

    def compute_power(
        self,
        level: int,
        grade: int = 0,
        core: int = 0,
        *,
        skill1_level: int = 1,
        skill2_level: int = 1,
        ulti_level: int = 1,
    ) -> int:
        """Return the closed-form Combat Power for this loadout.

        Excludes equipment / cube / treasure power buffs, which the
        caller can add separately (see ``docs/stat_formula.md`` if it
        gets written, or read the bundle excerpt in
        ``data/scrapers/blablalink.py``).
        """
        stats = self.compute(level, grade, core)
        atk, hp, defv = stats["atk"], stats["hp"], stats["def"]
        crit_r = self.critical_ratio * 1e-4
        crit_d = self.critical_damage * 1e-4 - 1
        hp_part = math.floor((hp + defv * _POWER_DEF_WEIGHT) * _POWER_HP_FACTOR)
        atk_part = math.floor(atk * (1 + crit_r * crit_d) * _POWER_ATK_FACTOR)
        skill_term = (
            skill1_level * _POWER_SKILL1
            + skill2_level * _POWER_SKILL2
            + ulti_level * _POWER_ULTI
        )
        return round((hp_part + atk_part) * (_POWER_BASE_MULT + skill_term) * 0.01)


def resolve_resource_id_by_name(
    name: str,
    *,
    lang: str = DEFAULT_LANG,
    cache_dir: Optional[Path] = None,
) -> Optional[int]:
    """Look up a NIKKE's resource_id by its display name (case-insensitive).

    Reads the cached ``nikke_list_<lang>_v2.json`` (populated by the
    first ``fetch-roledata`` run). Returns ``None`` if no match.
    """
    nl_path = cache_path_for_nikke_list(lang, cache_dir)
    if not nl_path.is_file():
        raise FileNotFoundError(
            f"No nikke_list cached at {nl_path}. "
            "Run `nikkeoptimizer fetch-roledata <anything>` once to populate it."
        )
    nikke_list = json.loads(nl_path.read_text())
    needle = name.strip().lower()
    for rec in nikke_list:
        rec_name = (rec.get("name_localkey") or {}).get("name")
        if isinstance(rec_name, str) and rec_name.lower() == needle:
            try:
                return int(rec["resource_id"])
            except (KeyError, ValueError, TypeError):
                return None
    return None


def list_cached_resource_ids(
    *, lang: str = DEFAULT_LANG, cache_dir: Optional[Path] = None
) -> list[int]:
    """Return resource_ids for which roledata is cached locally."""
    base = (cache_dir or default_cache_dir()) / lang / "roledata"
    if not base.is_dir():
        return []
    out: list[int] = []
    suffix = f"-v2-{lang}.json"
    for entry in base.iterdir():
        if entry.is_file() and entry.name.endswith(suffix):
            stem = entry.name[: -len(suffix)]
            try:
                out.append(int(stem))
            except ValueError:
                continue
    return sorted(out)


def load_all(
    *, lang: str = DEFAULT_LANG, cache_dir: Optional[Path] = None
) -> dict[int, BaseStats]:
    """Bulk-load every cached character's BaseStats, keyed by resource_id."""
    return {
        rid: BaseStats.from_cache(rid, lang=lang, cache_dir=cache_dir)
        for rid in list_cached_resource_ids(lang=lang, cache_dir=cache_dir)
    }
