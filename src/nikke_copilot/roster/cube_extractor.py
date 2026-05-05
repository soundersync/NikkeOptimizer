"""Extract cube info from a 'Harmony Cube' detail screenshot.

Each screenshot shows ONE cube with its name, level, stats, and the
'Cube Equipping Status [equipped / owned]' line that tells the optimizer how
many copies the user has. The 14 sample screenshots in
``tests/fixtures/screenshots/Cubes/`` cover the user's full cube inventory.

Geometry: heights vary across screenshots (the user cropped them differently),
so we don't use proportional crops — we just OCR the bottom ~55% of the image
and pattern-match the resulting text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

from .ocr import TextRegion, recognize

log = logging.getLogger(__name__)


def _recognize_for_cube(image: Image.Image) -> list[TextRegion]:
    """OCR tuned for the cube info dialog.

    Two key deviations from the default `recognize()` config:

      * **No upscale preprocess** — cube text is already large (~30 px tall on
        a 2732-wide screenshot); the default 2x upscale blurs the numerals
        and makes Vision misread "790" as "190" and "27300" as "2/300".
      * **Language correction enabled** — without it, Vision sometimes
        outputs "9IU" for "910"; correction folds those back to digits.
    """
    try:
        from ._apple_vision import AppleVisionEngine

        engine = AppleVisionEngine(uses_language_correction=True)
        return recognize(image, engine=engine, preprocess=False)
    except ImportError:
        # Non-macOS fallback: default engine, default config.
        return recognize(image, preprocess=False)


@dataclass
class CubeExtraction:
    """Structured result of running the extractor on one cube screenshot."""

    name: Optional[str] = None
    level: Optional[int] = None
    atk: Optional[int] = None
    hp: Optional[int] = None
    def_: Optional[int] = None
    equipping_count_equipped: Optional[int] = None
    equipping_count_owned: Optional[int] = None
    rarity_scope: Optional[str] = None  # "Universal" or future variants
    raw_ocr_lines: list[str] = field(default_factory=list)
    source_path: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        return (
            self.name is not None
            and self.level is not None
            and self.atk is not None
            and self.hp is not None
            and self.def_ is not None
            and self.equipping_count_owned is not None
        )


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

# "Assault Cube LV.7" — capture the full name (anything ending in "Cube") and
# the level. Tolerant of "Lv 7", "LV. 7", "LV  7" etc.
_TITLE_RE = re.compile(r"^(.+?Cube)\s+L[Vv]\.?\s*(\d+)\s*$")

# Standalone "ATK 910", "HP 27,300", "DEF 180". OCR routinely prepends the
# stat's icon glyph as "EE " (ammo icon → "EE"), "* " (HP icon → "*"),
# or "•" (bullet) before the label. We accept any short non-digit run as a
# leading noise prefix. OCR sometimes splits the label and value across
# regions — handled by the adjacent-region assembler below.
_NOISE_PREFIX = r"(?:[A-Za-z\*\•\.\-\s]{0,4}\s+)?"
_STAT_RE = re.compile(rf"^{_NOISE_PREFIX}(ATK|HP|DEF)\s+(-?\d[\d,]*)\s*$", re.I)
_STAT_LABEL_RE = re.compile(rf"^{_NOISE_PREFIX}(ATK|HP|DEF)\s*$", re.I)
# Tolerate leading bullet/punctuation: OCR sometimes prepends "• " to values
# when the icon column bleeds into the value region.
_STAT_VALUE_RE = re.compile(r"^[\*\•\.\-\s]*(-?\d[\d,]*)\s*$")

# "Cube Equipping Status [ 4 / 4 ]" — OCR routinely renders brackets as ( ) or
# { }, and sometimes loses the closing ] / ) entirely (read as "1" or just
# absent). We accept any trailing junk after the second number.
_EQUIP_RE = re.compile(
    r"Equipping\s*Status\s*[\[\(\{\s]*(\d+)\s*/\s*(\d+)",
    re.I,
)
# Last-ditch fallback: any "N / M" on a line containing 'Status'.
_EQUIP_FALLBACK_RE = re.compile(r"(\d+)\s*/\s*(\d+)")

# "•N• Universal" or "N Universal" — capture the scope only.
_SCOPE_RE = re.compile(r"\bUniversal\b|\bElement\b|\bWeapon\b", re.I)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_cube(image_path: Path) -> CubeExtraction:
    """Run the full extractor on a cube screenshot."""
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    # Dialog always sits in the lower portion of the image. Heights vary
    # (1206-1317 across our 14 fixtures), so use a generous bottom slice.
    crop = image.crop((0, int(h * 0.45), w, h))
    regions = _recognize_for_cube(crop)
    return _parse_regions(regions, source=str(image_path))


def _parse_regions(
    regions: list[TextRegion], *, source: Optional[str] = None
) -> CubeExtraction:
    """Run all field-parsers over an OCR result list."""
    # Sort top-to-bottom, left-to-right so adjacent label/value pairs are next
    # to each other in the list — needed for the split-region stat assembler.
    regions = sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0]))
    lines = [r.text for r in regions]

    out = CubeExtraction(raw_ocr_lines=list(lines), source_path=source)

    for line in lines:
        if out.name is None and (m := _TITLE_RE.match(line.strip())):
            out.name = m.group(1).strip()
            try:
                out.level = int(m.group(2))
            except ValueError:
                pass
        if out.rarity_scope is None and (m := _SCOPE_RE.search(line)):
            out.rarity_scope = m.group(0).capitalize()
        if (m := _EQUIP_RE.search(line)):
            try:
                eq = int(m.group(1))
                ow = int(m.group(2))
            except ValueError:
                continue
            # ')' → '1' OCR artifact: when the line lacks a real closing
            # bracket the misread '1' gets glued onto the second number
            # ("4 / 4)" reads as "4 / 41"). Strip the spurious trailing '1'.
            tail = line[m.end():]
            has_closer = any(c in tail for c in ")]}")
            if not has_closer and ow > 9 and ow % 10 == 1 and ow // 10 <= max(eq, 1) * 10:
                ow = ow // 10
            out.equipping_count_equipped = eq
            out.equipping_count_owned = ow

    # Equipping fallback: any line mentioning "status" with two numbers
    if out.equipping_count_owned is None:
        for line in lines:
            if "status" in line.lower():
                m = _EQUIP_FALLBACK_RE.search(line)
                if m:
                    out.equipping_count_equipped = int(m.group(1))
                    out.equipping_count_owned = int(m.group(2))
                    break

    # Stats — first try lines with both label+value, then assemble from
    # adjacent label-only and value-only regions.
    stats = {"atk": None, "hp": None, "def": None}
    for line in lines:
        m = _STAT_RE.match(line.strip())
        if m:
            label = m.group(1).lower()
            try:
                value = int(m.group(2).replace(",", ""))
            except ValueError:
                continue
            stats[label] = value

    # Adjacent-region assembly (DEF often gets split as 'DEF' + '180'). Only
    # search within ~200 px to the right on the same row — anything further
    # is a different UI column (skill icons live ~500 px away).
    _MAX_HORIZONTAL_GAP = 220
    for i, r in enumerate(regions):
        m = _STAT_LABEL_RE.match(r.text.strip())
        if not m:
            continue
        label = m.group(1).lower()
        if stats[label] is not None:
            continue
        ry = r.bbox[1]
        rh = r.bbox[3]
        for other in regions:
            if other is r:
                continue
            ox, oy, ow, oh = other.bbox
            same_row = abs((oy + oh / 2) - (ry + rh / 2)) < max(rh, oh) * 0.7
            horizontal_gap = ox - (r.bbox[0] + r.bbox[2])
            # Tolerate small negative overlaps — Vision sometimes reports
            # adjacent value bboxes that overlap the label by a few pixels.
            close_to_right = -20 <= horizontal_gap < _MAX_HORIZONTAL_GAP and ox > r.bbox[0]
            if not (same_row and close_to_right):
                continue
            mv = _STAT_VALUE_RE.match(other.text.strip())
            if mv:
                try:
                    stats[label] = int(mv.group(1).replace(",", ""))
                except ValueError:
                    pass
                break

    out.atk = stats["atk"]
    out.hp = stats["hp"]
    out.def_ = stats["def"]
    return out
