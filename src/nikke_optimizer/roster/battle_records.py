"""Battle Records screen extractor (Champions Arena, per-round details).

Layout (calibrated against 2732x2048 iPad captures):

  ┌─────────────────────────────────────────┐
  │            Battle Records               │  ← title strip ~y 0.10–0.18
  │  ┌──────────────┐  ┌──────────────┐     │
  │  │ My pick 1    │  │ Opp pick 1   │     │  ← row 1, ~y 0.22–0.34
  │  ├──────────────┤  ├──────────────┤
  │  │   ... 5 rows ...                     │
  │  └──────────────┘  └──────────────┘     │
  └─────────────────────────────────────────┘

Each row is one *matchup*: the user's pick at index N versus the opponent's
pick at index N. The two columns are MIRRORED:

  LEFT cell                       RIGHT cell
  [portrait]  Name                Name  [portrait]
              stat icons + values     stat icons + values  ←  cell
              [win-icon]              [win-icon]

In-game portrait thumbnails inside Battle Records are tiny and the right
column's portrait sits flush with the right edge of the cell; portrait-
based recognition is unreliable here. We instead OCR the cell text and
look for tokens that match a known Character name (the DB has 200+
entries — false positives are vanishingly rare for stylized in-game
names like 'Centi' or 'Rapunzel: Pure Grace'). This is dramatically more
robust than the portrait approach for BR specifically.

The right column may show "DISCONNECTED" as a status overlay when the
opponent didn't connect for that matchup; in that case we record the
opposing Nikke (by name) but leave numeric fields None.

Numeric values per cell are stored as a positional ``raw_numbers`` list
because the stat-icon → field mapping is not yet locked down across NIKKE
seasons (heuristic mapping happens in the validator).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image

from .arena import detect_title
from .ocr import recognize
from .portrait_matcher import PortraitMatcher

log = logging.getLogger(__name__)


# Region geometry — calibrated against the example
# `match_round_*_details.PNG` fixtures (Champions, 2732x2048 iPad).
# Coordinates are proportional to the FULL image, not the dialog.
_BR_REGIONS = {
    "dialog": (0.22, 0.07, 0.67, 0.83),
    "title_strip": (0.22, 0.10, 0.67, 0.18),
    # The two-column area where matchups live.
    "rows_band": (0.24, 0.21, 0.65, 0.80),
    # Within rows_band, the column boundaries (left = my picks, right = opp).
    # Expressed as fractions of the rows_band's *width*.
    "col_left": (0.00, 0.49),
    "col_right": (0.51, 1.00),
}

# Per-cell sub-crops (within one half-row cell). Mirrored for left vs right
# because the right column flips the whole layout horizontally — name is on
# the LEFT of the card, portrait is on the RIGHT.
_CELL_PORTRAIT_BOX_LEFT = (0.30, 0.45, 0.60, 0.98)   # portrait on left side of the card
_CELL_PORTRAIT_BOX_RIGHT = (0.65, 0.45, 0.95, 0.98)  # portrait on right side (mirrored)
# Text region — covers the name + stat block. We OCR the whole cell as a
# single text region because the name + numbers + DISCONNECTED overlay all
# need to be picked up; positional sub-cropping isn't reliable when the
# row strip's vertical alignment shifts a few pixels per row.
_CELL_TEXT_BOX_LEFT = (0.30, 0.05, 1.00, 0.95)
_CELL_TEXT_BOX_RIGHT = (0.00, 0.05, 0.70, 0.95)

# Number of matchup rows per Battle Records screen (always 5 in Champions).
_ROWS_PER_SCREEN = 5

# Numeric values in NIKKE UI use comma grouping ("1,234,567") and may be
# rendered in scientific-ish "1.2M" form for very large damages. We only
# accept the comma form for now — exhaustive coverage is a follow-up.
_NUMBER_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{4,})\b")


@dataclass
class BattleRecordsMatchup:
    """One matchup row from a Battle Records screen.

    Fields default to None when OCR couldn't extract them — either the
    cell rendered "DISCONNECTED" or the OCR confidence was too low.
    Numeric values are kept in a positional ``raw_numbers`` list because
    the stat-icon → field mapping is not yet locked down across NIKKE
    seasons (heuristic mapping happens in the validator).
    """

    my_nikke: Optional[str] = None
    opponent_nikke: Optional[str] = None
    my_disconnected: bool = False
    opponent_disconnected: bool = False
    my_raw_numbers: list[int] = field(default_factory=list)
    opponent_raw_numbers: list[int] = field(default_factory=list)
    # Best-guess stat assignments derived from magnitude order. Largest
    # number → damage_dealt; second-largest → damage_taken; third → healing;
    # small int (≤20) → burst_uses. None when not enough numbers extracted.
    my_damage_dealt: Optional[int] = None
    my_damage_taken: Optional[int] = None
    my_healing: Optional[int] = None
    my_burst_uses: Optional[int] = None
    opponent_damage_dealt: Optional[int] = None
    opponent_damage_taken: Optional[int] = None
    opponent_healing: Optional[int] = None
    opponent_burst_uses: Optional[int] = None
    # Inferred winner of this matchup. None when undetermined (typical when
    # one side disconnected — then the connected side wins by default).
    winner: Optional[str] = None  # 'me' | 'opponent' | None

    def to_dict(self) -> dict:
        return {
            "my_nikke": self.my_nikke,
            "opponent_nikke": self.opponent_nikke,
            "my_disconnected": self.my_disconnected,
            "opponent_disconnected": self.opponent_disconnected,
            "my_raw_numbers": self.my_raw_numbers,
            "opponent_raw_numbers": self.opponent_raw_numbers,
            "my_damage_dealt": self.my_damage_dealt,
            "my_damage_taken": self.my_damage_taken,
            "my_healing": self.my_healing,
            "my_burst_uses": self.my_burst_uses,
            "opponent_damage_dealt": self.opponent_damage_dealt,
            "opponent_damage_taken": self.opponent_damage_taken,
            "opponent_healing": self.opponent_healing,
            "opponent_burst_uses": self.opponent_burst_uses,
            "winner": self.winner,
        }


@dataclass
class BattleRecordsRound:
    """One Battle Records screen — represents the result of one Champions round."""

    mode: str = "champion_battle_record"
    round_index: Optional[int] = None
    matchups: list[BattleRecordsMatchup] = field(default_factory=list)
    raw_title_ocr: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "round_index": self.round_index,
            "matchups": [m.to_dict() for m in self.matchups],
        }


def _crop_proportional(
    image: Image.Image, box: tuple[float, float, float, float]
) -> Image.Image:
    w, h = image.size
    x1, y1, x2, y2 = box
    return image.crop((int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)))


def _split_rows(band: Image.Image, n: int = _ROWS_PER_SCREEN) -> list[Image.Image]:
    """Split a vertical band into ``n`` evenly-sized rows."""
    bw, bh = band.size
    row_h = bh // n
    return [band.crop((0, i * row_h, bw, (i + 1) * row_h)) for i in range(n)]


def _split_columns(row: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Split one row into (left=my pick, right=opp pick) cells."""
    rw, rh = row.size
    lx1, lx2 = _BR_REGIONS["col_left"]
    rx1, rx2 = _BR_REGIONS["col_right"]
    left = row.crop((int(lx1 * rw), 0, int(lx2 * rw), rh))
    right = row.crop((int(rx1 * rw), 0, int(rx2 * rw), rh))
    return left, right


def _extract_cell(
    cell: Image.Image,
    *,
    side: str,  # 'left' or 'right'
    known_names: Optional[Iterable[str]] = None,
    matcher: Optional[PortraitMatcher] = None,
) -> tuple[Optional[str], bool, list[int]]:
    """Pull (nikke_name, disconnected_flag, list_of_numbers) from one half-cell.

    Recognition strategy (in order, first hit wins):
      1. OCR the cell's text region; scan tokens for an exact match
         against ``known_names`` (the Character DB). Fast, precise,
         no portrait-region tuning required.
      2. If a portrait matcher is provided, fall back to embedding-based
         portrait recognition on the mirrored portrait crop.
      3. None when neither path produced a name.

    ``disconnected`` is True when the cell text contains "DISCONNECTED".
    ``numbers`` is every comma-grouped (or 4+ digit) integer found in the
    OCR text, in document order.
    """
    cw, ch = cell.size
    portrait_box = (
        _CELL_PORTRAIT_BOX_LEFT if side == "left" else _CELL_PORTRAIT_BOX_RIGHT
    )
    text_box = (
        _CELL_TEXT_BOX_LEFT if side == "left" else _CELL_TEXT_BOX_RIGHT
    )
    px1, py1, px2, py2 = portrait_box
    portrait = cell.crop(
        (int(cw * px1), int(ch * py1), int(cw * px2), int(ch * py2))
    )
    tx1, ty1, tx2, ty2 = text_box
    text_area = cell.crop(
        (int(cw * tx1), int(ch * ty1), int(cw * tx2), int(ch * ty2))
    )

    regions = recognize(text_area)
    raw_text = " ".join(r.text for r in regions)
    disconnected = "disconnect" in raw_text.lower()

    nikke_name: Optional[str] = None
    if known_names:
        nikke_name = _scan_for_known_name(regions, known_names)
    if nikke_name is None and matcher is not None:
        match = matcher.match_best(portrait)
        if match is not None:
            nikke_name = match.character_name

    numbers: list[int] = []
    for m in _NUMBER_RE.finditer(raw_text.replace(" ", "")):
        try:
            numbers.append(int(m.group(1).replace(",", "")))
        except ValueError:
            continue
    return nikke_name, disconnected, numbers


def _scan_for_known_name(
    regions: list, known_names: Iterable[str]
) -> Optional[str]:
    """Return the first OCR token that resolves to a known character name.

    Tries exact match first (case-insensitive); falls back to a fuzzy
    match (difflib cutoff 0.85) for slight OCR drift like 'Crowm' vs
    'Crown'. Multi-word tokens (e.g. 'Rapunzel: Pure Grace') are also
    reconstructed by joining adjacent OCR regions.
    """
    import difflib

    name_set = list(known_names)
    name_lower_to_canonical = {n.lower(): n for n in name_set}

    # Pass 1: per-region exact match.
    for r in regions:
        token = r.text.strip()
        if not token:
            continue
        canon = name_lower_to_canonical.get(token.lower())
        if canon:
            return canon

    # Pass 2: try joining consecutive regions (covers "Rapunzel: Pure" +
    # "Grace" splits).
    for i in range(len(regions)):
        for span in (2, 3):
            if i + span > len(regions):
                continue
            joined = " ".join(r.text.strip() for r in regions[i:i + span]).strip()
            if not joined:
                continue
            canon = name_lower_to_canonical.get(joined.lower())
            if canon:
                return canon

    # Pass 3: fuzzy match on each token (high cutoff to avoid false
    # positives — anything below 0.85 typically means we're matching
    # noise to an unrelated short name).
    candidate_lookup = {n.lower(): n for n in name_set}
    for r in regions:
        token = r.text.strip().lower()
        if len(token) < 3:
            continue
        matches = difflib.get_close_matches(
            token, list(candidate_lookup.keys()), n=1, cutoff=0.85,
        )
        if matches:
            return candidate_lookup[matches[0]]
    return None


def _assign_stats(numbers: list[int]) -> dict:
    """Heuristic mapping of an unordered number list to named stats.

    Sort descending; assume largest = damage_dealt, next = damage_taken,
    next = healing. Any small value ≤ 20 captured separately is treated as
    burst_uses.
    """
    out = {
        "damage_dealt": None,
        "damage_taken": None,
        "healing": None,
        "burst_uses": None,
    }
    big = sorted([n for n in numbers if n > 20], reverse=True)
    small = [n for n in numbers if n <= 20]
    if big:
        out["damage_dealt"] = big[0]
    if len(big) >= 2:
        out["damage_taken"] = big[1]
    if len(big) >= 3:
        out["healing"] = big[2]
    if small:
        out["burst_uses"] = small[0]
    return out


def extract_battle_records(
    image_path: Path,
    matcher: Optional[PortraitMatcher] = None,
    *,
    known_character_names: Optional[Iterable[str]] = None,
) -> Optional[BattleRecordsRound]:
    """Parse a Battle Records screenshot into a per-matchup data structure.

    ``known_character_names`` is the list of valid Character.name values
    the cell-text OCR matches against. When supplied this is the primary
    recognition path; the portrait matcher is the fallback. Without it,
    only portrait matching runs (less reliable on these tiny crops).

    Returns None when the title doesn't look like a Battle Records screen.
    Best-effort otherwise — partial extraction (some rows good, some not)
    still returns a round; downstream code should treat None values
    defensively.
    """
    image = Image.open(image_path).convert("RGB")
    mode, title_lines = detect_title(image)
    if mode != "champion_battle_record":
        return None

    # Round number — search the full image since the round badge sits
    # outside the modal in some captures.
    full_ocr = recognize(image)
    round_idx: Optional[int] = None
    for r in full_ocr:
        m = re.search(r"ROUND\s*0?(\d)", r.text, re.I)
        if m:
            round_idx = int(m.group(1))
            break

    band = _crop_proportional(image, _BR_REGIONS["rows_band"])
    rows = _split_rows(band)
    matchups: list[BattleRecordsMatchup] = []
    for row in rows:
        left_cell, right_cell = _split_columns(row)
        my_name, my_dc, my_nums = _extract_cell(
            left_cell, side="left",
            known_names=known_character_names, matcher=matcher,
        )
        opp_name, opp_dc, opp_nums = _extract_cell(
            right_cell, side="right",
            known_names=known_character_names, matcher=matcher,
        )
        my_stats = _assign_stats(my_nums) if not my_dc else {}
        opp_stats = _assign_stats(opp_nums) if not opp_dc else {}
        # Winner inference: if exactly one side disconnected, the other
        # wins. If both connected, the side with greater damage_dealt
        # generally wins (rough — real game uses HP-remaining tiebreakers
        # we can't see here).
        winner: Optional[str] = None
        if my_dc and not opp_dc:
            winner = "opponent"
        elif opp_dc and not my_dc:
            winner = "me"
        elif not my_dc and not opp_dc:
            md = my_stats.get("damage_dealt")
            od = opp_stats.get("damage_dealt")
            if md is not None and od is not None:
                if md > od:
                    winner = "me"
                elif od > md:
                    winner = "opponent"
        matchups.append(
            BattleRecordsMatchup(
                my_nikke=my_name,
                opponent_nikke=opp_name,
                my_disconnected=my_dc,
                opponent_disconnected=opp_dc,
                my_raw_numbers=my_nums,
                opponent_raw_numbers=opp_nums,
                my_damage_dealt=my_stats.get("damage_dealt"),
                my_damage_taken=my_stats.get("damage_taken"),
                my_healing=my_stats.get("healing"),
                my_burst_uses=my_stats.get("burst_uses"),
                opponent_damage_dealt=opp_stats.get("damage_dealt"),
                opponent_damage_taken=opp_stats.get("damage_taken"),
                opponent_healing=opp_stats.get("healing"),
                opponent_burst_uses=opp_stats.get("burst_uses"),
                winner=winner,
            )
        )

    return BattleRecordsRound(
        round_index=round_idx,
        matchups=matchups,
        raw_title_ocr=title_lines,
    )
