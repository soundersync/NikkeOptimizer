"""Coord schema for League leaderboard.png screenshots.

Twelve regions: 4 ranks × {synchro level, player name, combat power}.
Both **size and position** are normalized in these constants:

* Size — every field family has a fixed ``(width, height)`` shared by
  all 4 ranks: synchro 68×29, name 263×48, cp 287×52. Coord-picker
  drift is removed at the constants level.
* Position — each field family has a single ``x_min``/``x_max`` shared
  by all 4 ranks (the in-game UI puts each column at a fixed x). The
  ``y_min`` per rank is encoded explicitly (4 anchors per field).

**Rank 1 banner exception.** The leader's row carries a "qualified
for the Promotion Tournament" banner above the name + cp fields,
pushing both lines down ~20 px below where the rank 2/3/4 row template
would put them. The banner doesn't extend over the synchro column
(left side), so synchro y_min stride is uniform 251 px for every
rank; the name + cp strides are uniform from rank 2 onward, with a
one-time +20 px shift between rank 1 and rank 2. The constants honor
the actual on-screen positions — do not "stride-correct" rank 1 back
to flat. ``test_rank1_name_cp_offset_by_banner`` pins this invariant.

Reuses ``Region`` from ``promo_tournament_regions`` so the OCR helpers
(``regions_for_kind``, ``extract_region``) handle this format with no
new schema. Coords are absolute pixel ``(x1, y1, x2, y2)`` against
``REFERENCE_IMAGE_SIZE`` (1080-wide leaderboard screen).
"""

from __future__ import annotations

from .promo_tournament_regions import Bbox, Region

REFERENCE_IMAGE_SIZE: tuple[int, int] = (1080, 2400)

# Per-field x range — constant across all 4 ranks. Picked from the
# mode of the user's coord-picker clicks; the UI puts each column at
# a fixed x so per-rank x variance is just click jitter.
SYNCHRO_X: tuple[int, int] = (312, 380)   # width 68
NAME_X:    tuple[int, int] = (430, 693)   # width 263
CP_X:      tuple[int, int] = (440, 727)   # width 287

# Canonical heights — applied to every rank for the matching field.
SYNCHRO_H: int = 29
NAME_H:    int = 48
CP_H:      int = 52

# Inter-rank stride for the league leaderboard's row template.
RANK_STRIDE: int = 251

# Per-rank y_min, per field. Stride-locked at exactly RANK_STRIDE
# everywhere except rank-1's name + cp, which sit ~20 px below the
# template because of the "qualified for Promotion Tournament" banner
# above rank 1 (banner doesn't extend over the synchro column, so
# synchro is fully uniform). Do not "fix" rank 1's name/cp y — see
# the module docstring + test_rank1_name_cp_offset_by_banner.
SYNCHRO_Y_MIN_BY_RANK: tuple[int, int, int, int] = (848, 1099, 1350, 1601)
NAME_Y_MIN_BY_RANK:    tuple[int, int, int, int] = (776, 1008, 1259, 1510)
CP_Y_MIN_BY_RANK:      tuple[int, int, int, int] = (849, 1080, 1331, 1582)


def _bbox(x_range: tuple[int, int], y_min: int, height: int) -> Bbox:
    return (x_range[0], y_min, x_range[1], y_min + height)


def _build_leaderboard_regions() -> tuple[Region, ...]:
    rows: list[Region] = []
    for rank_idx in range(4):
        rank = rank_idx + 1
        g = f"rank{rank}"
        rows.append(Region(
            f"{g}_synchro",
            f"Rank {rank} — Synchro Level",
            _bbox(SYNCHRO_X, SYNCHRO_Y_MIN_BY_RANK[rank_idx], SYNCHRO_H),
            group=g,
        ))
        rows.append(Region(
            f"{g}_name",
            f"Rank {rank} — Player Name",
            _bbox(NAME_X, NAME_Y_MIN_BY_RANK[rank_idx], NAME_H),
            group=g,
        ))
        rows.append(Region(
            f"{g}_cp",
            f"Rank {rank} — Combat Power",
            _bbox(CP_X, CP_Y_MIN_BY_RANK[rank_idx], CP_H),
            group=g,
        ))
    return tuple(rows)


LEADERBOARD_REGIONS: tuple[Region, ...] = _build_leaderboard_regions()


def regions_by_rank() -> dict[int, dict[str, Region]]:
    """Return ``{rank: {field: Region}}`` for callers that want to walk
    the leaderboard by (rank, field) instead of a flat tuple. ``field``
    is one of ``"synchro"`` / ``"name"`` / ``"cp"``.
    """
    out: dict[int, dict[str, Region]] = {}
    for region in LEADERBOARD_REGIONS:
        rank_str, field = region.slug.split("_", 1)
        rank = int(rank_str.removeprefix("rank"))
        out.setdefault(rank, {})[field] = region
    return out


def crop_filename(region: Region) -> str:
    """Canonical on-disk filename for a leaderboard crop."""
    return f"leaderboard__{region.slug}__crop.png"
