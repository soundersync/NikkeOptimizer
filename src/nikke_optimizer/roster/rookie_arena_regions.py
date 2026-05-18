"""Coord schema for Rookie Arena captures.

Three image kinds, all 1510×2013:

* ``rookie_opponent`` — opponent.png (the Arena Group selection screen
  shown BEFORE picking a match). Captures the user's own player level
  (the badge under their avatar) plus 3 candidate opponents × {name,
  level}. Only the most-recent run carries this; older runs will not
  have an opponent.png file.

* ``rookie_loadout`` — loadout.png (the Rookie Arena pre-battle popup
  with opponent + my team). Layout differs meaningfully from the
  Champions Arena popup:
    - 1 team per player (not 5)
    - Nikke levels NOT capped at 400
    - No per-Nikke CP (only team total)
    - Opponent team on top + my team on bottom (always)
    - Asymmetric team-CP placement (opponent CP under opponent team,
      my CP above my team — different x positions too)

* ``results_duel`` (NOT rookie-specific) — results.png. Reuses the
  Champion Duel ``results_duel`` schema because the Rookie Arena
  Battle Records screen IS the same in-game popup (verified pixel-
  for-pixel). ``rookie_arena_ingest`` registers ``results.png`` with
  ``kind="results_duel"``.

**Coord normalization.** Per-slot picker output drifts (some slots
picked tighter than others — e.g. opponent slots 3 & 4 of lb_core had
x1 ~20px right of the canonical position). To eliminate that drift,
we derive ONE canonical within-tile offset per field group from the
median of the picker output, then apply it uniformly across all 5
slots using each slot's tile origin. The portrait/tile region uses
the same ``(170, 317)`` dimensions as the Champions ``PLAYER_LOADOUT``
schema for visual consistency across modes.
"""

from __future__ import annotations

from typing import Iterable

# Kind strings + slot counts defined BEFORE the Region import so they're
# visible during circular import. promo_tournament_regions' module-level
# _BY_KIND construction calls back into this module via a lazy
# importlib hop; if these constants land after the Region import, that
# callback hits a partially-initialized module and fails. Cheap fix:
# define the constants up top.
ROOKIE_OPPONENT_KIND = "rookie_opponent"
ROOKIE_LOADOUT_KIND = "rookie_loadout"
OPPONENT_CARD_COUNT = 3   # Arena Group page shows 3 candidate opponents
ROOKIE_TEAM_SIZE = 5      # always 5 Nikkes per team

from .promo_tournament_regions import REFERENCE_IMAGE_SIZE, Region

__all__ = (
    "REFERENCE_IMAGE_SIZE",
    "ROOKIE_OPPONENT",
    "ROOKIE_LOADOUT",
    "ROOKIE_OPPONENT_KIND",
    "ROOKIE_LOADOUT_KIND",
    "OPPONENT_CARD_COUNT",
    "ROOKIE_TEAM_SIZE",
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _normalize_group(
    picks: tuple[tuple[int, int, int, int], ...],
) -> tuple[tuple[int, int, int, int], ...]:
    """Normalize a group of coord-picker bboxes to a single max W × max H
    anchored at each pick's x1/y1. Used for groups whose picks share a
    common shape but the user's per-element picks vary in size by a
    few pixels (e.g. the 3 opponent.png candidate cards)."""
    max_w = max(x2 - x1 for x1, _, x2, _ in picks)
    max_h = max(y2 - y1 for _, y1, _, y2 in picks)
    return tuple(
        (x1, y1, x1 + max_w, y1 + max_h) for x1, y1, _, _ in picks
    )


def _median(values: Iterable[int]) -> int:
    vals = sorted(values)
    return vals[len(vals) // 2]


def _canonical_field_geometry(
    picks: tuple[tuple[int, int, int, int], ...],
    tile_origins: tuple[tuple[int, int, int, int], ...],
) -> tuple[int, int, int, int]:
    """Derive ``(dx1, y1, dx2, y2)`` for a per-slot field group.

    Why this split: the per-tile **x** drifts because each slot's
    tile starts at a different x, so x must be tile-relative. But the
    per-tile **y** is essentially constant across slots — the picker's
    y values cluster tightly (e.g. doll y1 = 633-634 across all 5
    slots) even though tile y1 itself drifts 7px. Using a tile-relative
    dy + applying it would smear those 7px of tile drift INTO the
    field position, putting slot 5 below where the doll actually is.

    Solution: x uses median ``(px - tx)`` from each slot, y uses
    median ABSOLUTE y from the picks. Every slot then renders at the
    same absolute y.
    """
    dx1 = _median(p[0] - t[0] for p, t in zip(picks, tile_origins))
    dx2 = _median(p[2] - t[0] for p, t in zip(picks, tile_origins))
    y1 = _median(p[1] for p in picks)
    y2 = _median(p[3] for p in picks)
    return (dx1, y1, dx2, y2)


def _apply_field_geometry(
    tile_origins: Iterable[tuple[int, int, int, int]],
    geom: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int, int], ...]:
    """Project a canonical field geometry across all per-slot tile
    origins. dx1/dx2 are tile-relative; y1/y2 are absolute (uniform
    across slots).
    """
    dx1, y1, dx2, y2 = geom
    return tuple(
        (tx1 + dx1, y1, tx1 + dx2, y2)
        for tx1, _, _, _ in tile_origins
    )




# ---------------------------------------------------------------------------
# opponent.png — Arena Group selection screen
# ---------------------------------------------------------------------------

# My player level — the small badge tucked under my avatar at the top
# of the screen. Authoritative source for current synchro level since
# AccountState may drift.
_MY_PLAYER_LEVEL: tuple[int, int, int, int] = (452, 512, 517, 540)

# Per-card picker coords (verbatim from user picks). Normalized below
# to uniform W × H per field group.
_OPPONENT_CARD_NAME_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (449, 1088, 772, 1118),   # card 1
    (451, 1369, 702, 1400),   # card 2
    (451, 1649, 682, 1679),   # card 3
)
_OPPONENT_CARD_LEVEL_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (305, 1151, 373, 1180),
    (305, 1433, 373, 1461),
    (305, 1714, 373, 1742),
)


OPPONENT_CARD_NAME: tuple[tuple[int, int, int, int], ...] = _normalize_group(
    _OPPONENT_CARD_NAME_PICKED,
)
OPPONENT_CARD_LEVEL: tuple[tuple[int, int, int, int], ...] = _normalize_group(
    _OPPONENT_CARD_LEVEL_PICKED,
)


def _build_rookie_opponent() -> tuple[Region, ...]:
    rows: list[Region] = [
        Region(
            "my_player_level", "My Player Level", _MY_PLAYER_LEVEL,
            group="header",
        ),
    ]
    for i in range(OPPONENT_CARD_COUNT):
        n = i + 1
        g = f"opp{n}"
        rows.append(Region(f"{g}.name", f"Opponent {n} — Name", OPPONENT_CARD_NAME[i], group=g))
        rows.append(Region(f"{g}.level", f"Opponent {n} — Level", OPPONENT_CARD_LEVEL[i], group=g))
    return tuple(rows)


ROOKIE_OPPONENT: tuple[Region, ...] = _build_rookie_opponent()


# ---------------------------------------------------------------------------
# loadout.png — Rookie Arena pre-battle popup
# ---------------------------------------------------------------------------

# Header fields. Player labels at top; team CPs at asymmetric positions
# (opponent CP under their team on the LEFT, my CP above my team on the
# RIGHT).
_HEADER_OPPONENT_NAME: tuple[int, int, int, int] = (400, 395, 708, 429)
_HEADER_MY_NAME: tuple[int, int, int, int] = (801, 391, 1173, 431)
_HEADER_OPPONENT_TEAM_CP: tuple[int, int, int, int] = (384, 832, 595, 869)
_HEADER_MY_TEAM_CP: tuple[int, int, int, int] = (957, 1035, 1204, 1073)


# Per-slot tile origins. Opponent on top (y ≈ 487-806), my team on
# bottom (y ≈ 1089-1408). Tile dimensions match Champions
# PLAYER_LOADOUT (170 × 317) — same visual layout, same pixel size.
_OPP_TILE: tuple[tuple[int, int, int, int], ...] = (
    (305, 487, 475, 806),
    (487, 488, 658, 806),
    (670, 489, 840, 806),
    (852, 490, 1022, 806),
    (1035, 494, 1206, 806),
)
_MY_TILE: tuple[tuple[int, int, int, int], ...] = (
    (300, 1089, 471, 1407),
    (485, 1103, 656, 1408),
    (670, 1106, 840, 1407),
    (854, 1094, 1025, 1407),
    (1038, 1099, 1209, 1407),
)


# Per-field picker coords from the PDF — opponent side. Used only to
# derive the canonical within-tile offset for each field group; the
# actual per-slot regions below all apply the median offset uniformly.
_OPP_NAME_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (358, 773, 471, 794),
    (541, 773, 653, 793),
    (724, 775, 835, 792),
    (905, 772, 1018, 793),
    (1087, 772, 1201, 794),
)
_OPP_LB_CORE_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (385, 738, 468, 767),
    (566, 737, 650, 767),
    (769, 747, 835, 768),
    (955, 745, 1018, 770),
    (1113, 737, 1198, 769),
)
_OPP_NIKKE_LEVEL_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (311, 743, 358, 794),
    (494, 743, 540, 794),
    (676, 742, 724, 794),
    (857, 740, 905, 794),
    (1041, 742, 1088, 794),
)
_OPP_DOLL_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (311, 633, 344, 673),
    (493, 634, 527, 672),
    (676, 634, 709, 671),
    (858, 634, 892, 672),
    (1040, 634, 1074, 673),
)

# My-team picker coords from the explicit user picks ("My Tiles.pdf").
# Layout is visually similar to opp but drifts ~10-12px UP relative
# to a naive mirror — the my-team UI evidently squeezes the row of
# badges slightly closer to the portrait. Always use explicit picks
# when available.
_MY_NAME_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (352, 1373, 466, 1393),
    (537, 1374, 650, 1394),
    (721, 1374, 835, 1393),
    (906, 1374, 1019, 1394),
    (1090, 1373, 1203, 1394),
)
_MY_LB_CORE_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (379, 1336, 464, 1370),
    (565, 1337, 648, 1368),
    (750, 1338, 832, 1368),
    (933, 1337, 1016, 1368),
    (1118, 1337, 1201, 1368),
)
_MY_NIKKE_LEVEL_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (308, 1345, 352, 1393),
    (492, 1344, 537, 1394),
    (678, 1344, 721, 1394),
    (862, 1345, 906, 1394),
    (1045, 1344, 1090, 1394),
)
_MY_DOLL_PICKED: tuple[tuple[int, int, int, int], ...] = (
    (307, 1234, 340, 1272),
    (492, 1234, 524, 1273),
    (676, 1234, 709, 1273),
    (860, 1234, 894, 1273),
    (1045, 1235, 1078, 1273),
)


# Canonical (dx1, y1, dx2, y2) geometries — x is tile-relative
# (eliminates per-slot pick drift), y is absolute (uniform across
# slots so every per-field crop in a row starts at the same y).
_GEOM_OPP_NAME = _canonical_field_geometry(_OPP_NAME_PICKED, _OPP_TILE)
_GEOM_OPP_LB_CORE = _canonical_field_geometry(_OPP_LB_CORE_PICKED, _OPP_TILE)
_GEOM_OPP_LEVEL = _canonical_field_geometry(_OPP_NIKKE_LEVEL_PICKED, _OPP_TILE)
_GEOM_OPP_DOLL = _canonical_field_geometry(_OPP_DOLL_PICKED, _OPP_TILE)
_GEOM_MY_NAME = _canonical_field_geometry(_MY_NAME_PICKED, _MY_TILE)
_GEOM_MY_LB_CORE = _canonical_field_geometry(_MY_LB_CORE_PICKED, _MY_TILE)
_GEOM_MY_LEVEL = _canonical_field_geometry(_MY_NIKKE_LEVEL_PICKED, _MY_TILE)
_GEOM_MY_DOLL = _canonical_field_geometry(_MY_DOLL_PICKED, _MY_TILE)

# Portrait/tile region. Same dimensions as Champions PLAYER_LOADOUT
# (170 × 317) for visual consistency across capture modes. Anchored
# at each slot's tile origin x; y is fixed at the median tile y1 of
# each team (uniform across slots on each side).
_PORTRAIT_W, _PORTRAIT_H = 170, 317


def _portrait_regions(
    tile_origins: tuple[tuple[int, int, int, int], ...],
) -> tuple[tuple[int, int, int, int], ...]:
    y1 = _median(t[1] for t in tile_origins)
    y2 = y1 + _PORTRAIT_H
    return tuple(
        (tx1, y1, tx1 + _PORTRAIT_W, y2) for tx1, _, _, _ in tile_origins
    )


# Project to per-slot bboxes. ``_apply_field_geometry`` keeps y
# absolute (uniform across slots) and x tile-relative.
OPP_NAME = _apply_field_geometry(_OPP_TILE, _GEOM_OPP_NAME)
OPP_LB_CORE = _apply_field_geometry(_OPP_TILE, _GEOM_OPP_LB_CORE)
OPP_NIKKE_LEVEL = _apply_field_geometry(_OPP_TILE, _GEOM_OPP_LEVEL)
OPP_DOLL = _apply_field_geometry(_OPP_TILE, _GEOM_OPP_DOLL)
OPP_PORTRAIT = _portrait_regions(_OPP_TILE)

MY_NAME = _apply_field_geometry(_MY_TILE, _GEOM_MY_NAME)
MY_LB_CORE = _apply_field_geometry(_MY_TILE, _GEOM_MY_LB_CORE)
MY_NIKKE_LEVEL = _apply_field_geometry(_MY_TILE, _GEOM_MY_LEVEL)
MY_DOLL = _apply_field_geometry(_MY_TILE, _GEOM_MY_DOLL)
MY_PORTRAIT = _portrait_regions(_MY_TILE)


def _build_rookie_loadout() -> tuple[Region, ...]:
    rows: list[Region] = [
        Region("opponent_name", "Opponent Player Name", _HEADER_OPPONENT_NAME, group="header"),
        Region("my_name", "My Player Name", _HEADER_MY_NAME, group="header"),
        Region("opponent_team_cp", "Opponent Team CP", _HEADER_OPPONENT_TEAM_CP, group="header"),
        Region("my_team_cp", "My Team CP", _HEADER_MY_TEAM_CP, group="header"),
    ]
    # Opponent team — slug prefix "opp.charN.*" so the existing OCR
    # slug classifier routes "opp.char1.name" through the fuzzy
    # character matcher.
    for i in range(ROOKIE_TEAM_SIZE):
        n = i + 1
        g = f"opp.char{n}"
        rows.append(Region(f"{g}.portrait", f"Opponent {n} — Portrait", OPP_PORTRAIT[i], group=g))
        rows.append(Region(f"{g}.doll", f"Opponent {n} — Doll/Treasure", OPP_DOLL[i], group=g))
        rows.append(Region(f"{g}.lb_core", f"Opponent {n} — LB & Core", OPP_LB_CORE[i], group=g))
        rows.append(Region(f"{g}.level", f"Opponent {n} — Nikke Level", OPP_NIKKE_LEVEL[i], group=g))
        rows.append(Region(f"{g}.name", f"Opponent {n} — Name", OPP_NAME[i], group=g))
    # My team — same shape, "my.charN.*" slug prefix.
    for i in range(ROOKIE_TEAM_SIZE):
        n = i + 1
        g = f"my.char{n}"
        rows.append(Region(f"{g}.portrait", f"My {n} — Portrait", MY_PORTRAIT[i], group=g))
        rows.append(Region(f"{g}.doll", f"My {n} — Doll/Treasure", MY_DOLL[i], group=g))
        rows.append(Region(f"{g}.lb_core", f"My {n} — LB & Core", MY_LB_CORE[i], group=g))
        rows.append(Region(f"{g}.level", f"My {n} — Nikke Level", MY_NIKKE_LEVEL[i], group=g))
        rows.append(Region(f"{g}.name", f"My {n} — Name", MY_NAME[i], group=g))
    return tuple(rows)


ROOKIE_LOADOUT: tuple[Region, ...] = _build_rookie_loadout()
