"""Per-cube data-quality warnings.

Surfaces likely-OCR-misreads by comparing each cube's stat values
against the median of same-level siblings. Real-world example: an OCR
pass produced "Assist Cube ATK 190" when same-level cubes (Endurance,
Healing) all read ~790 — the leading "7" was misread as "1". The
inconsistency is structural: in NIKKE, all cubes at a given level
share the same per-stat magnitudes (only which two of {ATK, HP, DEF}
are non-zero differs by cube type).

Usage:

    warnings_by_id = compute_cube_warnings(cubes)
    for cube in cubes:
        for w in warnings_by_id.get(cube.id, []):
            ...

Empty list when nothing's suspicious.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Iterable

from ..data.models import Cube


# Stats fields to cross-validate. A cube only contributes to a stat's
# median if it has a positive value for that stat — null/zero stats
# are the cube type opting out, not an outlier.
_STATS = ("atk", "hp", "def_")
_LABEL = {"atk": "ATK", "hp": "HP", "def_": "DEF"}

# Trigger a warning when a stat differs from the same-level median by
# more than this fraction. 0.4 = "differs by more than 40%". The
# Assist Cube 190 vs sibling 790 case is 76% off.
OUTLIER_FRACTION = 0.4


def compute_cube_warnings(cubes: Iterable[Cube]) -> dict[int, list[str]]:
    """Return a mapping of ``cube.id -> [warning, ...]`` for each cube
    with one or more outlier stats vs same-level siblings.

    A cube is only checked when:
      * It has a level set (level=None means the OCR couldn't read it).
      * At least one same-level sibling cube exists with a positive
        value for the same stat (otherwise we have no median to
        compare against).

    Cubes with no warnings get an empty list (or are simply absent
    from the dict — callers should use ``.get(id, [])``).
    """
    cubes = list(cubes)
    by_level: dict[int, list[Cube]] = defaultdict(list)
    for c in cubes:
        if c.level is None or c.id is None:
            continue
        by_level[c.level].append(c)

    out: dict[int, list[str]] = {}
    for level, group in by_level.items():
        if len(group) < 2:
            continue  # no same-level siblings to compare against
        # Per-stat median of positive values across the group.
        per_stat_median: dict[str, float] = {}
        for stat in _STATS:
            values = [
                getattr(c, stat) for c in group
                if getattr(c, stat) is not None and getattr(c, stat) > 0
            ]
            if values:
                per_stat_median[stat] = median(values)
        # Compare each cube's stats against the median.
        for c in group:
            for stat, med in per_stat_median.items():
                value = getattr(c, stat)
                if value is None or value <= 0:
                    continue
                if med <= 0:
                    continue
                deviation = abs(value - med) / med
                if deviation > OUTLIER_FRACTION:
                    msg = (
                        f"{_LABEL[stat]} {value:,} differs by {int(deviation * 100)}% "
                        f"from same-level median ({int(med):,}) — "
                        f"likely OCR misread"
                    )
                    out.setdefault(c.id, []).append(msg)
    return out
