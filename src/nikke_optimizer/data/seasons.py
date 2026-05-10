"""Beta season cadence for NIKKE PvP captures.

NIKKE's PvP modes (Promotion Tournament, Champions Duel, League) reset on
a roughly 14-day cadence. The user supplies season numbers and start
dates as the ground truth; this module records every known anchor and
extrapolates at the 14-day base cadence for seasons we haven't logged
yet.

Used by the capture archive layout (``<archive>/beta_season_<N>/...``)
so all captures from the same season cluster together regardless of the
day they were collected.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Final, Optional

# Anchor table. Source of truth: user message 2026-05-09.
# Sorted ascending by season number.
_ANCHORS: Final[tuple[tuple[int, date], ...]] = (
    (18, date(2025, 12, 4)),
    (19, date(2025, 12, 18)),
    (20, date(2026, 1, 1)),
    (21, date(2026, 1, 15)),
    (22, date(2026, 1, 29)),
    (23, date(2026, 2, 12)),
    (24, date(2026, 2, 26)),
    (25, date(2026, 3, 12)),
    (26, date(2026, 3, 25)),
    (27, date(2026, 4, 9)),
    (28, date(2026, 4, 23)),
    (29, date(2026, 5, 7)),
)

# Cadence used to extrapolate beyond the anchor table's range.
_BASE_CADENCE: Final[timedelta] = timedelta(days=14)

_SEASON_FOLDER_RE = re.compile(r"^beta_season_(\d+)$")
# Lenient form for staging names like ``beta_season_29_2026-05-07``.
_SEASON_PREFIX_RE = re.compile(r"beta_season_(\d+)")


def season_for_date(d: date) -> int:
    """Return the beta season number that contains ``d``.

    Anchored seasons resolve via table lookup. Dates after the latest
    anchor or before the earliest extrapolate at the 14-day cadence.
    """
    first_n, first_start = _ANCHORS[0]
    last_n, last_start = _ANCHORS[-1]

    if d >= last_start:
        return last_n + (d - last_start).days // _BASE_CADENCE.days

    if d < first_start:
        days_back = (first_start - d).days
        # ceil: a date one day before an anchor lives in the previous season.
        weeks_back = -(-days_back // _BASE_CADENCE.days)
        return first_n - weeks_back

    chosen = first_n
    for n, start in _ANCHORS:
        if start <= d:
            chosen = n
        else:
            break
    return chosen


def season_start(season_number: int) -> date:
    """Return the start date for ``season_number``.

    Looks up the anchor table; falls back to extrapolation when the
    requested season lies outside the table.
    """
    for n, start in _ANCHORS:
        if n == season_number:
            return start
    last_n, last_start = _ANCHORS[-1]
    first_n, first_start = _ANCHORS[0]
    if season_number > last_n:
        return last_start + (season_number - last_n) * _BASE_CADENCE
    return first_start - (first_n - season_number) * _BASE_CADENCE


def season_id(d: date) -> str:
    """Canonical folder slug for the season containing ``d``."""
    return f"beta_season_{season_for_date(d)}"


def season_id_for_number(season_number: int) -> str:
    return f"beta_season_{season_number}"


def parse_season_number(name: str) -> Optional[int]:
    """Extract the season number from any folder name that contains
    ``beta_season_<N>``. Used to recognize both archive folders
    (``beta_season_29``) and staging folders the user drops in
    (``beta_season_29_2026-05-07``).
    """
    m = _SEASON_PREFIX_RE.search(name)
    if m is None:
        return None
    return int(m.group(1))


def is_season_folder(name: str) -> bool:
    """Strict match for the canonical archive directory name."""
    return bool(_SEASON_FOLDER_RE.match(name))
