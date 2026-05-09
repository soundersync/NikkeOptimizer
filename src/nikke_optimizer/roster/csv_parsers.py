"""Parsers for the cell-formats used in `nikke_roster_data.csv`.

Each function returns either a structured value or `None` when the cell is
blank/unrecognized. Parsers never raise on malformed input — instead they
return None and let the caller decide whether that row is salvageable.
"""

import re
from typing import Optional

from ..data.enums import OLBonusType


# OLBonusType lookup keyed by lowercased canonical label (with "Increase " prefix removed).
_BONUS_LOOKUP: dict[str, OLBonusType] = {b.value.lower(): b for b in OLBonusType}
# Aliases / synonyms encountered in the CSV.
_BONUS_ALIASES: dict[str, OLBonusType] = {
    "max ammunition capacity": OLBonusType.MAX_AMMUNITION_CAPACITY,
    "ammunition capacity": OLBonusType.AMMUNITION_CAPACITY,
    "atk": OLBonusType.ATK,
    "attack": OLBonusType.ATK,
    "hp": OLBonusType.HP,
    "defense": OLBonusType.DEFENSE,
    "def": OLBonusType.DEFENSE,
    "element damage dealt": OLBonusType.ELEMENT_DAMAGE,
    "elemental damage dealt": OLBonusType.ELEMENT_DAMAGE,
    "hit rate": OLBonusType.HIT_RATE,
    "critical rate": OLBonusType.CRITICAL_RATE,
    "critical damage": OLBonusType.CRITICAL_DAMAGE,
    "charge speed": OLBonusType.CHARGE_SPEED,
    "charge damage": OLBonusType.CHARGE_DAMAGE,
}

_NUMERIC_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_EFFECT_RE = re.compile(r"^(?:Increase\s+)?(.+?)\s+(-?\d[\d,]*(?:\.\d+)?)\s*%\s*$", re.I)


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    m = _NUMERIC_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    m = _NUMERIC_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_cooldown(value: Optional[str]) -> Optional[float]:
    """Parse "40.0s" → 40.0."""
    return parse_float(value)


_BURST_COOLDOWN_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s\b", re.I)


def parse_burst_cooldown_from_description(value: Optional[str]) -> Optional[float]:
    """Extract burst cooldown from a Burst Description prefix.

    The user's roster CSV embeds the cooldown as a leading "20.0 s" or
    similar prefix on the burst description, e.g.:

        "20.0 s■ Affects all allies. ATK ▲ 66% for 5 sec."

    Returns the float value (seconds) or ``None`` if no prefix is found.
    """
    if not value:
        return None
    m = _BURST_COOLDOWN_PREFIX_RE.match(value)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def strip_burst_cooldown_prefix(value: Optional[str]) -> Optional[str]:
    """Return the description with the leading "X.X s" cooldown removed.

    Useful when the description text is being stored separately from the
    cooldown — keeps the description prose clean.
    """
    if not value:
        return value
    return _BURST_COOLDOWN_PREFIX_RE.sub("", value, count=1).strip()


def parse_phase(value: Optional[str]) -> Optional[int]:
    """Parse "Phase 15" → 15."""
    return parse_int(value)


def lookup_bonus_type(label: str) -> Optional[OLBonusType]:
    key = label.strip().lower()
    if key.startswith("increase "):
        key = key[len("increase ") :]
    if key in _BONUS_ALIASES:
        return _BONUS_ALIASES[key]
    if key in _BONUS_LOOKUP:
        return _BONUS_LOOKUP[key]
    return None


def parse_effect(value: Optional[str]) -> Optional[tuple[Optional[OLBonusType], str, Optional[float]]]:
    """Parse "Increase Element Damage Dealt 27.16%" → (ELEMENT_DAMAGE, raw_label, 27.16).

    Returns None for blank or "No Effects". The first element may be None
    when the label doesn't map to a known OLBonusType (caller can still log
    the raw_label).
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    normalized = re.sub(r"[\s\-_]+", "", s.lower())
    if normalized.startswith("noeffect"):
        return None
    m = _EFFECT_RE.match(s)
    if not m:
        return (lookup_bonus_type(s), s, None)
    label = m.group(1).strip()
    pct = float(m.group(2).replace(",", ""))
    return (lookup_bonus_type(label), s, pct)


_SUMMARY_SPLITTER_RE = re.compile(r"\s*[|;]\s*")


def parse_effect_summary(value: Optional[str]) -> list[tuple[Optional[OLBonusType], str, Optional[float]]]:
    """Parse "Increase X 1.2% | Increase Y 3.4%" → list of effect tuples.

    Both ``|`` and ``;`` are accepted as separators — the legacy CSV
    format used ``|``, the current format uses ``;``.
    """
    if not value:
        return []
    parts = [p.strip() for p in _SUMMARY_SPLITTER_RE.split(value) if p.strip()]
    out: list[tuple[Optional[OLBonusType], str, Optional[float]]] = []
    for p in parts:
        eff = parse_effect(p)
        if eff:
            out.append(eff)
    return out


# Stats blocks come in three flavors across CSV exports:
#   Legacy:   "HP 73772 / ATK 9021"
#   2026-04:  "HP 73772; ATK 9021"
#   2026-05+: "HP 73772, ATK 9021"
# Treat all three separators as equivalent.
_STATS_SPLITTER_RE = re.compile(r"\s*[/;,]\s*")


def parse_stats_block(value: Optional[str]) -> dict[str, int]:
    """Parse "HP 73772 / ATK 9021" → {'hp': 73772, 'atk': 9021}.

    Recognized labels: HP, ATK, DEF (case-insensitive). Both ``/`` and
    ``;`` are accepted as separators — the legacy CSV used ``/``, the
    current export uses ``;``. Unlabeled trailing numbers are tolerated
    for cube stats: "ATK 2780 / DEF 552 / 83400" puts 83400 into 'hp'
    (cube convention — third value is HP).
    """
    if not value:
        return {}
    out: dict[str, int] = {}
    parts = [p.strip() for p in _STATS_SPLITTER_RE.split(value) if p.strip()]
    unlabeled_targets = ["hp", "atk", "def"]
    for part in parts:
        m = re.match(r"^([A-Za-z]+)\s+(-?\d[\d,]*)$", part)
        if m:
            key = m.group(1).lower()
            try:
                out[key] = int(m.group(2).replace(",", ""))
            except ValueError:
                continue
            if key in unlabeled_targets:
                unlabeled_targets.remove(key)
        else:
            n = parse_int(part)
            if n is None:
                continue
            if unlabeled_targets:
                target = unlabeled_targets.pop(0)
                out.setdefault(target, n)
    return out


def parse_cube_stats(value: Optional[str]) -> dict[str, int]:
    """Same as parse_stats_block but tuned for the cube format.

    Cube stats appear as e.g. "ATK 2780 / DEF 552 / 83400" — the trailing
    unlabeled value is HP.
    """
    return parse_stats_block(value)
