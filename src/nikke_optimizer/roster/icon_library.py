"""Build a CharacterIcon library from in-game roster grid screenshots.

Workflow:
  1. Crop the screenshot into a grid of cells (default 4 cols x N rows).
  2. For each cell, crop the name banner (bottom strip) and OCR it.
  3. Fuzzy-match the OCR'd name against the Character DB.
  4. Save the cell crop as the canonical icon for that character.
  5. Persist to the `character_icon` table; surface low-confidence matches
     to a `_review/` folder for manual sorting.

Default cell size is detected from the input image, but can be overridden
when the user provides screenshots at different resolutions / scroll states.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image
from sqlmodel import Session, select

from ..data.models import Character, CharacterIcon
from .ocr import recognize

log = logging.getLogger(__name__)

# Includes both the LV banner and the name; we filter the LV at parse time.
_NAME_STRIP_FRACTION_TOP = 0.88
_NAME_STRIP_FRACTION_BOT = 1.00

# Regex strippers applied to OCR'd name text in order.
_NOISE_PATTERNS = [
    re.compile(r"^L[Vv]?\s*\d+\s*[-:.]?\s*", re.IGNORECASE),  # "LV 652", "LV652-"
    re.compile(r"^\d{2,4}\s*[-:.]?\s*"),  # bare level numbers like "652-"
    # Noise prefix from misread LV (e.g. "L-", "C-", "6JL", "6JC-", "65")
    re.compile(r"^(?:6\w{0,3}|[A-Za-z]{1,2})\s*[-:.]+\s+(?=[A-Za-z])"),
    re.compile(r"^(?:6\w{0,3})\s+(?=[A-Za-z])"),
    re.compile(r"\s+\d+$"),  # trailing numbers
]
# Token rejection — entire cleaned text matches → discard.
_FULLY_NOISE = re.compile(r"^[\d\s\-:.]*$")


@dataclass
class IconExtraction:
    cell_index: tuple[int, int]  # (row, col)
    crop: Image.Image
    ocr_name_raw: str
    ocr_confidence: float
    matched_name: Optional[str]
    match_confidence: float  # 0..1 from difflib

    @property
    def is_confident(self) -> bool:
        return self.matched_name is not None and self.match_confidence >= 0.70


def _crop_cells(
    image: Image.Image, *, cols: int = 4, rows: Optional[int] = None
) -> list[tuple[tuple[int, int], Image.Image]]:
    width, height = image.size
    cell_w = width // cols
    if rows is None:
        # Reference image is 1040x2188 → 5 rows. Aspect of one cell ≈ 1.68:1.
        # Estimate rows from the same aspect; round to nearest integer.
        approx_cell_h = cell_w * 1.68
        rows = max(1, int(round(height / approx_cell_h)))
    cell_h = height // rows
    cells: list[tuple[tuple[int, int], Image.Image]] = []
    for r in range(rows):
        for c in range(cols):
            box = (c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h)
            cells.append(((r, c), image.crop(box)))
    return cells


def _clean_ocr_name(text: str) -> str:
    s = text.strip()
    for pat in _NOISE_PATTERNS:
        s = pat.sub("", s).strip()
    if _FULLY_NOISE.match(s):
        return ""
    # Drop solitary tokens that are pure numbers (lingering noise).
    tokens = [t for t in s.split() if not t.isdigit()]
    s = " ".join(tokens).strip()
    # Strip trailing punctuation
    s = re.sub(r"[\-:_.]+$", "", s).strip()
    return s


def _ocr_name_strip(cell: Image.Image) -> tuple[str, float]:
    cw, ch = cell.size
    strip = cell.crop(
        (0, int(ch * _NAME_STRIP_FRACTION_TOP), cw, int(ch * _NAME_STRIP_FRACTION_BOT))
    )
    regions = recognize(strip)
    if not regions:
        return "", 0.0
    # Filter regions: drop pure numbers (level), MAX badges, single-char tokens.
    name_regions: list = []
    for r in regions:
        t = r.text.strip()
        if not t:
            continue
        if re.fullmatch(r"\d{2,4}-?", t):  # "652", "652-"
            continue
        if t.upper() in {"MAX", "LV", "LV.", "LV:"}:
            continue
        if len(t) <= 1:
            continue
        name_regions.append(r)
    if not name_regions:
        return "", 0.0
    # The actual name is the rightmost / longest text. Concat in x-order.
    name_regions.sort(key=lambda r: r.bbox[0])
    text = " ".join(r.text for r in name_regions).strip()
    cleaned = _clean_ocr_name(text)
    avg_conf = sum(r.confidence for r in name_regions) / len(name_regions)
    return cleaned, avg_conf


def _fuzzy_match(name: str, all_names: list[str]) -> tuple[Optional[str], float]:
    if not name:
        return None, 0.0
    matches = difflib.get_close_matches(name, all_names, n=1, cutoff=0.5)
    if not matches:
        return None, 0.0
    best = matches[0]
    score = difflib.SequenceMatcher(None, name.lower(), best.lower()).ratio()
    return best, score


def _fuzzy_match_partial(name: str, all_names: list[str]) -> tuple[Optional[str], float]:
    """Match (potentially cut-off) OCR names against the full character list.

    Strategy:
      1. Exact (case-insensitive) → 1.0
      2. OCR is a suffix or prefix of candidate (cut-off names) → 0.90
      3. OCR appears as a substring → 0.85
      4. Token-level overlap (e.g. "Red Hood" in "Rapi: Red Hood") → 0.7-0.85
    Tiebreak: prefer the *shortest* candidate length ≥ ocr length, since cut-off
    names usually map to a short candidate that exactly contains the OCR text.
    """
    if not name:
        return None, 0.0
    lower = name.lower().strip()
    if not lower:
        return None, 0.0
    ocr_tokens = set(lower.split())
    candidates: list[tuple[str, float, int]] = []  # (name, score, length)
    for n in all_names:
        nl = n.lower()
        score = 0.0
        if lower == nl:
            score = 1.0
        elif nl.endswith(lower) or nl.startswith(lower):
            # Suffix/prefix match — common cut-off case. Length-aware so a
            # 1-char candidate (e.g. "D") doesn't dominate a 7-char OCR.
            ratio = min(len(lower), len(nl)) / max(len(lower), len(nl))
            score = 0.65 + 0.30 * ratio  # 0.65 - 0.95
        elif lower in nl or nl in lower:
            ratio = min(len(lower), len(nl)) / max(len(lower), len(nl))
            score = 0.55 + 0.30 * ratio  # 0.55 - 0.85
        else:
            cand_tokens = set(nl.split())
            if ocr_tokens and cand_tokens:
                shared = ocr_tokens & cand_tokens
                if shared:
                    overlap = len(shared) / max(len(ocr_tokens), len(cand_tokens))
                    if overlap >= 0.4:
                        score = 0.55 + overlap * 0.35  # 0.7 - 0.9
        if score > 0:
            candidates.append((n, score, len(n)))
    if not candidates:
        return None, 0.0
    # Best score, then shortest candidate (cut-off names favor concise matches).
    candidates.sort(key=lambda x: (-x[1], x[2]))
    return candidates[0][0], candidates[0][1]


def extract_icons(
    image_path: Path,
    *,
    cols: int = 4,
    rows: Optional[int] = None,
) -> list[IconExtraction]:
    image = Image.open(image_path).convert("RGB")
    cells = _crop_cells(image, cols=cols, rows=rows)
    results: list[IconExtraction] = []
    for idx, cell in cells:
        name, conf = _ocr_name_strip(cell)
        results.append(
            IconExtraction(
                cell_index=idx,
                crop=cell,
                ocr_name_raw=name,
                ocr_confidence=conf,
                matched_name=None,
                match_confidence=0.0,
            )
        )
    return results


def resolve_matches(
    extractions: Iterable[IconExtraction], all_names: list[str]
) -> list[IconExtraction]:
    """Mutate each extraction to populate matched_name + match_confidence.

    Strategy: prefer structural (substring/suffix/prefix/word-overlap) matches
    over difflib's character-level ratio, because OCR truncations are common
    and the structural match is more reliable for that case.
    """
    out = list(extractions)
    for x in out:
        if not x.ocr_name_raw:
            continue
        direct, score = _fuzzy_match(x.ocr_name_raw, all_names)
        partial, pscore = _fuzzy_match_partial(x.ocr_name_raw, all_names)
        # Trust partial match when it's reasonably confident (structural).
        if partial and pscore >= 0.65:
            x.matched_name = partial
            x.match_confidence = pscore
        elif direct and score >= 0.70:
            x.matched_name = direct
            x.match_confidence = score
        elif pscore > score:
            x.matched_name = partial
            x.match_confidence = pscore
        else:
            x.matched_name = direct
            x.match_confidence = score
    return out


def save_icon_library(
    extractions: Iterable[IconExtraction],
    output_root: Path,
    session: Session,
    *,
    review_dirname: str = "_review",
    source_screenshot: Optional[str] = None,
) -> dict[str, int]:
    """Save cropped icons + persist `CharacterIcon` rows.

    Confident matches go to `<output_root>/<character_name>/`.
    Low-confidence ones go to `<output_root>/<review_dirname>/` with a name
    that includes the OCR guess, for manual sorting.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    review_dir = output_root / review_dirname
    review_dir.mkdir(exist_ok=True)
    counts = {"confident": 0, "review": 0, "skipped": 0}

    for x in extractions:
        if x.is_confident and x.matched_name:
            char = session.exec(
                select(Character).where(Character.name == x.matched_name)
            ).one_or_none()
            if char is None:
                counts["skipped"] += 1
                continue
            char_dir = output_root / _safe_dirname(x.matched_name)
            char_dir.mkdir(exist_ok=True)
            file_path = char_dir / f"icon_{x.cell_index[0]}_{x.cell_index[1]}.png"
            x.crop.save(file_path, format="PNG")
            session.add(
                CharacterIcon(
                    character_id=char.id,
                    image_path=str(file_path),
                    source=source_screenshot or "icon_library_extractor",
                    confidence=x.match_confidence,
                )
            )
            counts["confident"] += 1
        else:
            slug = _safe_dirname(x.ocr_name_raw or "unknown")
            file_path = review_dir / f"r{x.cell_index[0]}c{x.cell_index[1]}_{slug}.png"
            x.crop.save(file_path, format="PNG")
            counts["review"] += 1
    session.commit()
    return counts


def _safe_dirname(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    safe = safe.strip("_") or "unknown"
    return safe[:80]
