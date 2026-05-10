"""League leaderboard OCR.

A league capture's ``leaderboard.png`` is the source of truth. The
twelve per-rank crop files (``leaderboard__rank<N>_<field>__crop.png``)
are derived from it via :func:`cut_leaderboard_crops`, which uses the
fixed ``LEADERBOARD_REGIONS`` constants in
:mod:`league_leaderboard_regions` (the project's standard
"regions live in code" pattern; see ``promo_tournament_regions.py``,
``arena.py``, ``battle_records.py`` for siblings).

Pipeline:

1. ``cut_leaderboard_crops`` cuts 12 canonical crops from
   ``leaderboard.png`` using ``LEADERBOARD_REGIONS``. Idempotent — the
   destination filenames are deterministic.
2. ``extract_leaderboard`` runs PaddleOCR on each crop and post-
   processes the text into structured ``LeaderboardEntry`` rows.
3. ``process_league_archive`` writes the result to ``leaderboard.json``
   next to ``leaderboard.png`` so subsequent ingests skip OCR.

The user's coord-picker output (``leaderboard__<bbox>__crop.png`` files
in the staging folder) is reference material for updating the
``LEADERBOARD_REGIONS`` constants — the ingest never reads it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .league_leaderboard_regions import (
    LEADERBOARD_REGIONS,
    crop_filename,
    regions_by_rank,
)

log = logging.getLogger(__name__)


@dataclass
class LeaderboardEntry:
    rank: int
    name: str
    name_confidence: float
    name_crop: str  # filename of source crop, relative to leaderboard root
    cp: Optional[int]
    cp_text: str
    cp_confidence: float
    cp_crop: str
    synchro_level: Optional[int]
    synchro_text: str
    synchro_confidence: float
    synchro_crop: str


def parse_cp(text: str) -> Optional[int]:
    """Parse a combat-power string like ``"3,294,200"`` or ``"3294200"``
    into an int. Returns ``None`` when no digits are present.
    """
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def parse_synchro_level(text: str) -> Optional[int]:
    """Parse a synchro-level string into an int. Strips any leading
    ``Lv``/``LV.``/``Level`` prefix that survives OCR.
    """
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Cut canonical crops from the master image
# ---------------------------------------------------------------------------


def cut_leaderboard_crops(
    league_root: Path,
    *,
    master_name: str = "leaderboard.png",
) -> int:
    """Cut the 12 canonical leaderboard crops from
    ``<league_root>/<master_name>`` using ``LEADERBOARD_REGIONS``.

    Output filenames are deterministic
    (``leaderboard__rank<N>_<field>__crop.png``). Idempotent: when a
    destination file already exists at the expected pixel dimensions,
    it's left in place. Returns the number of files written.
    """
    from PIL import Image

    master_path = league_root / master_name
    if not master_path.is_file():
        log.warning("cut_leaderboard_crops: master image %s missing", master_path)
        return 0

    n_written = 0
    with Image.open(master_path) as master:
        master = master.convert("RGB")
        master_w, master_h = master.size
        for region in LEADERBOARD_REGIONS:
            x1, y1, x2, y2 = region.bbox
            target_w, target_h = x2 - x1, y2 - y1
            # Clamp into the master image bounds.
            x1c = max(0, min(x1, master_w - target_w))
            y1c = max(0, min(y1, master_h - target_h))
            x2c = x1c + target_w
            y2c = y1c + target_h
            out_path = league_root / crop_filename(region)
            if out_path.is_file():
                try:
                    with Image.open(out_path) as existing:
                        if existing.size == (target_w, target_h):
                            continue
                except OSError:
                    pass  # corrupt / unreadable — re-cut below
            cropped = master.crop((x1c, y1c, x2c, y2c))
            cropped.save(out_path)
            n_written += 1
    return n_written


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


def _ocr_text(crop_path: Path) -> tuple[str, float]:
    """Open a crop, run PaddleOCR, return concatenated text + mean
    confidence.
    """
    from PIL import Image

    from .promo_tournament_ocr import ocr_crop

    image = Image.open(crop_path).convert("RGB")
    items = ocr_crop(image)
    if not items:
        return "", 0.0
    texts = [t for (_b, t, _c) in items if t]
    confs = [c for (_b, _t, c) in items if c is not None]
    text = " ".join(texts).strip()
    confidence = sum(confs) / len(confs) if confs else 0.0
    return text, confidence


def extract_leaderboard(league_root: Path) -> list[LeaderboardEntry]:
    """Run OCR over every leaderboard crop in ``league_root`` and
    return the 4 leaderboard entries.

    Skips silently (returns ``[]``) when the canonical crops are
    missing — caller is expected to invoke :func:`cut_leaderboard_crops`
    first.
    """
    by_rank = regions_by_rank()
    entries: list[LeaderboardEntry] = []
    for rank in sorted(by_rank.keys()):
        fields = by_rank[rank]
        name_path = league_root / crop_filename(fields["name"])
        cp_path = league_root / crop_filename(fields["cp"])
        syn_path = league_root / crop_filename(fields["synchro"])
        if not (name_path.is_file() and cp_path.is_file() and syn_path.is_file()):
            return []
        name_text, name_conf = _ocr_text(name_path)
        cp_text, cp_conf = _ocr_text(cp_path)
        syn_text, syn_conf = _ocr_text(syn_path)
        entries.append(LeaderboardEntry(
            rank=rank,
            name=name_text,
            name_confidence=name_conf,
            name_crop=name_path.name,
            cp=parse_cp(cp_text),
            cp_text=cp_text,
            cp_confidence=cp_conf,
            cp_crop=cp_path.name,
            synchro_level=parse_synchro_level(syn_text),
            synchro_text=syn_text,
            synchro_confidence=syn_conf,
            synchro_crop=syn_path.name,
        ))
    return entries


# ---------------------------------------------------------------------------
# Sidecar (leaderboard.json)
# ---------------------------------------------------------------------------


def sidecar_path(league_root: Path) -> Path:
    return league_root / "leaderboard.json"


def write_sidecar(league_root: Path, entries: list[LeaderboardEntry]) -> Path:
    out = sidecar_path(league_root)
    payload = {"entries": [asdict(e) for e in entries]}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def read_sidecar(league_root: Path) -> Optional[list[LeaderboardEntry]]:
    p = sidecar_path(league_root)
    if not p.is_file():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw = payload.get("entries", []) if isinstance(payload, dict) else []
    out: list[LeaderboardEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out.append(LeaderboardEntry(**item))
        except TypeError:
            continue
    return out


def process_league_archive(league_root: Path, *, force: bool = False) -> Optional[Path]:
    """Extract + write ``leaderboard.json`` for an archived league
    tournament. Idempotent: if the sidecar exists and ``force`` is
    False, returns the existing path without re-running OCR.

    Returns the sidecar path on success, or ``None`` when there are no
    leaderboard crops to process (caller is expected to call
    :func:`cut_leaderboard_crops` first).
    """
    out = sidecar_path(league_root)
    if out.is_file() and not force:
        return out
    entries = extract_leaderboard(league_root)
    if not entries:
        return None
    return write_sidecar(league_root, entries)
