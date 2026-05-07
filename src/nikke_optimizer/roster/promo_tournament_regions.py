"""Coord schema for Champions Arena Promotion Tournament screenshots.

Three image kinds, all 1510×2013:

* ``player_loadout`` — player_top/round_N.png and player_bottom/round_N.png
  share the same schema. Captures player name, team CP, and 5 character
  cards (portrait, doll/treasure icon, character CP).
* ``results_overview`` — results/overview.png. Captures winner name,
  left/right player names, and 5 round-result strips.
* ``results_duel`` — results/duel_N.png (N=1..5). Captures 5 characters
  per side × 5 fields (name / attack damage / defense / heal / HP%).

Coords are absolute pixel ``(x1, y1, x2, y2)`` against
``REFERENCE_IMAGE_SIZE``. They came from
``Promotion_Tournament_Match.pdf`` and may need refinement against
real screenshots — the overlay debug page surfaces misalignment.
"""

from __future__ import annotations

from dataclasses import dataclass

REFERENCE_IMAGE_SIZE: tuple[int, int] = (1510, 2013)

Bbox = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Region:
    """A labelled crop region.

    ``slug`` is a stable identifier (used in URL fragments + DB rows).
    ``label`` is the human-readable label for the right-pane viewer.
    ``bbox`` is absolute pixel ``(x1, y1, x2, y2)`` against the source.
    ``group`` is an optional grouping key the UI can use to section
    related regions (e.g. ``"char1"`` for all char-1 fields).
    """

    slug: str
    label: str
    bbox: Bbox
    group: str | None = None


# ---------------------------------------------------------------------------
# Player loadout — shared by player_top/round_N.png and player_bottom/round_N.png
# ---------------------------------------------------------------------------

# Per-character card coords. Strides are *not* exactly parametric (the
# PDF has small per-character drift); store five explicit tuples.
_PLAYER_CHAR_PORTRAIT: tuple[Bbox, ...] = (
    (306, 1047, 476, 1364),
    (488, 1047, 658, 1363),
    (670, 1047, 840, 1363),
    (852, 1047, 1022, 1363),
    (1035, 1047, 1203, 1363),
)
_PLAYER_CHAR_DOLL: tuple[Bbox, ...] = (
    (312, 1192, 345, 1229),
    (494, 1192, 527, 1228),
    (676, 1191, 709, 1229),
    (858, 1191, 891, 1229),
    (1040, 1190, 1074, 1230),
)
_PLAYER_CHAR_CP: tuple[Bbox, ...] = (
    (318, 1375, 464, 1413),
    (502, 1372, 647, 1414),
    (680, 1373, 829, 1412),
    (862, 1371, 1011, 1414),
    (1047, 1373, 1193, 1414),
)


def _build_player_loadout() -> tuple[Region, ...]:
    rows: list[Region] = [
        Region("player_name", "Player Name", (514, 815, 854, 851), group="header"),
        Region("team_cp", "Team CP", (1043, 732, 1208, 787), group="header"),
    ]
    for i in range(5):
        n = i + 1
        g = f"char{n}"
        rows.append(Region(f"{g}.portrait", f"Char {n} — Portrait", _PLAYER_CHAR_PORTRAIT[i], group=g))
        rows.append(Region(f"{g}.doll", f"Char {n} — Doll/Treasure", _PLAYER_CHAR_DOLL[i], group=g))
        rows.append(Region(f"{g}.cp", f"Char {n} — CP", _PLAYER_CHAR_CP[i], group=g))
    return tuple(rows)


PLAYER_LOADOUT: tuple[Region, ...] = _build_player_loadout()


# ---------------------------------------------------------------------------
# Match results overview — results/overview.png
# ---------------------------------------------------------------------------

_OVERVIEW_ROUND_STRIPS: tuple[Bbox, ...] = (
    (318, 1121, 917, 1180),
    (318, 1201, 909, 1264),
    (322, 1289, 888, 1345),
    (325, 1377, 889, 1430),
    (338, 1457, 889, 1523),
)


def _build_overview() -> tuple[Region, ...]:
    rows: list[Region] = [
        Region("winner_name", "Winner Name", (512, 661, 832, 710), group="header"),
        Region("left_name", "Left Player Name", (472, 1031, 655, 1062), group="header"),
        Region("right_name", "Right Player Name", (734, 1029, 920, 1061), group="header"),
    ]
    for i in range(5):
        n = i + 1
        rows.append(Region(f"round{n}_strip", f"Round {n} Result", _OVERVIEW_ROUND_STRIPS[i], group=f"round{n}"))
    return tuple(rows)


OVERVIEW: tuple[Region, ...] = _build_overview()


# ---------------------------------------------------------------------------
# Round duel results — results/duel_N.png. 5 chars × 5 fields × 2 sides = 50.
# ---------------------------------------------------------------------------

# Field order per character (columns of the PDF spec).
_DUEL_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Name"),
    ("atk", "Attack Damage"),
    ("def", "Defense"),
    ("heal", "Heal"),
    ("hp", "Remaining HP %"),
)

# Left side, indexed [char_idx][field_idx]. char_idx 0..4 ↔ Char 1..5.
_DUEL_LEFT: tuple[tuple[Bbox, ...], ...] = (
    # Char 1
    (
        (489, 598, 697, 629),
        (488, 641, 702, 676),
        (496, 676, 702, 712),
        (496, 716, 701, 750),
        (355, 722, 443, 743),
    ),
    # Char 2
    (
        (485, 791, 699, 829),
        (494, 837, 702, 875),
        (497, 875, 702, 909),
        (498, 914, 703, 948),
        (356, 918, 442, 939),
    ),
    # Char 3
    (
        (492, 990, 702, 1026),
        (493, 1033, 703, 1071),
        (496, 1070, 700, 1109),
        (495, 1110, 700, 1145),
        (356, 1116, 443, 1138),
    ),
    # Char 4
    (
        (495, 1187, 700, 1222),
        (495, 1231, 703, 1267),
        (496, 1269, 701, 1305),
        (496, 1307, 700, 1340),
        (356, 1313, 444, 1334),
    ),
    # Char 5
    (
        (494, 1384, 698, 1419),
        (495, 1427, 701, 1466),
        (496, 1466, 700, 1503),
        (496, 1506, 701, 1538),
        (357, 1510, 442, 1531),
    ),
)

# Right side, same shape. HP% columns sit on the *right* of each card
# (at x≈1060) instead of left of the card like on the left side.
_DUEL_RIGHT: tuple[tuple[Bbox, ...], ...] = (
    # Char 1
    (
        (808, 595, 1014, 630),
        (808, 639, 1013, 675),
        (807, 675, 1014, 712),
        (807, 716, 1016, 749),
        (1070, 718, 1165, 744),
    ),
    # Char 2
    (
        (807, 791, 1023, 829),
        (807, 837, 1023, 871),
        (808, 873, 1021, 910),
        (808, 911, 1023, 946),
        (1068, 915, 1166, 940),
    ),
    # Char 3
    (
        (808, 990, 1021, 1025),
        (807, 1033, 1022, 1068),
        (808, 1069, 1023, 1106),
        (807, 1109, 1021, 1142),
        (1061, 1114, 1168, 1137),
    ),
    # Char 4
    (
        (807, 1186, 1021, 1222),
        (808, 1231, 1019, 1265),
        (807, 1267, 1021, 1305),
        (807, 1306, 1020, 1339),
        (1059, 1310, 1167, 1335),
    ),
    # Char 5
    (
        (807, 1383, 1024, 1420),
        (807, 1428, 1024, 1464),
        (809, 1464, 1024, 1502),
        (810, 1503, 1024, 1536),
        (1063, 1504, 1169, 1533),
    ),
)


def _build_duel() -> tuple[Region, ...]:
    rows: list[Region] = []
    for side, side_label, by_char in (
        ("left", "Left", _DUEL_LEFT),
        ("right", "Right", _DUEL_RIGHT),
    ):
        for char_idx, fields in enumerate(by_char):
            char_no = char_idx + 1
            group = f"{side}.char{char_no}"
            for field_idx, (field_slug, field_label) in enumerate(_DUEL_FIELDS):
                rows.append(
                    Region(
                        slug=f"{side}.char{char_no}.{field_slug}",
                        label=f"{side_label} · Char {char_no} · {field_label}",
                        bbox=fields[field_idx],
                        group=group,
                    )
                )
    return tuple(rows)


DUEL: tuple[Region, ...] = _build_duel()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

KINDS: tuple[str, ...] = ("player_loadout", "results_overview", "results_duel")

_BY_KIND: dict[str, tuple[Region, ...]] = {
    "player_loadout": PLAYER_LOADOUT,
    "results_overview": OVERVIEW,
    "results_duel": DUEL,
}


def regions_for_kind(kind: str) -> tuple[Region, ...]:
    """Return the regions tuple for a screenshot kind, in display order."""
    try:
        return _BY_KIND[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown kind {kind!r}; expected one of {KINDS}") from exc


def region_by_slug(kind: str, slug: str) -> Region | None:
    """Look up a single region by slug within a kind."""
    for r in regions_for_kind(kind):
        if r.slug == slug:
            return r
    return None
