"""Limit-Break stars + Core badge extraction for ``char{N}.lb_core`` crops.

Each crop is the standard 85×30 region carved by
``promo_tournament_regions._PLAYER_CHAR_LB_CORE``. There are two
in-game layouts:

* **With Core badge** (LB = 3 AND Core ≥ 1): three stars on the left at
  x≈{12, 32, 52}, badge at x≈58–85.
* **Without Core badge** (LB < 3 OR Core = 0): three stars centered at
  x≈{40, 57, 75}; right side is the rank-icon background only.

We pick mode by counting bright-white pixels (badge text) in the right
half — purple is unreliable because some characters carry a purple
rank-icon background that has no Core badge. Yellow stars are detected
via a tight ``R>200 & R-B>140`` mask that excludes the dimmer yellow
background stripes.

Badge value is read by PaddleOCR on the badge sub-crop upscaled 4×.
Empirically it returns one of ``"01".."06"`` or ``"MAX"`` (Core 7
renders as the literal word, not ``"07"``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Pixel classifiers
# ---------------------------------------------------------------------------


def _bright_yellow_mask(arr: np.ndarray) -> np.ndarray:
    """Bright yellow STAR pixels — excludes dimmer background stripes."""
    R = arr[..., 0].astype(int)
    B = arr[..., 2].astype(int)
    return (R > 200) & ((R - B) > 140)


def _bright_white_mask(arr: np.ndarray) -> np.ndarray:
    """Bright white (badge text) pixels."""
    R = arr[..., 0].astype(int)
    G = arr[..., 1].astype(int)
    B = arr[..., 2].astype(int)
    return (
        (R > 200) & (G > 200) & (B > 200)
        & (np.abs(R - G) < 30) & (np.abs(G - B) < 30)
    )


# ---------------------------------------------------------------------------
# Star + badge geometry
# ---------------------------------------------------------------------------

# Empirically derived from a 200-crop sample (champions_duel_20260505).
_STAR_CENTERS_WITH_BADGE = (12, 32, 52)
_STAR_CENTERS_NO_BADGE = (40, 57, 75)
_SAMPLE_HALF = 5  # 11×11 sample window per star center
_SAMPLE_PIX_THRESH = 12  # min bright-yellow pixels in window to count star
_BADGE_X1, _BADGE_X2 = 58, 85
_BADGE_WHITE_THRESH = 30  # min white pixels in badge zone to call badge present


def _badge_present(arr: np.ndarray) -> bool:
    return bool(_bright_white_mask(arr)[:, _BADGE_X1:_BADGE_X2].sum() >= _BADGE_WHITE_THRESH)


def _count_yellow_stars(arr: np.ndarray, badge_present: bool) -> int:
    h, w, _ = arr.shape
    centers = _STAR_CENTERS_WITH_BADGE if badge_present else _STAR_CENTERS_NO_BADGE
    yellow = _bright_yellow_mask(arr)
    cy = h // 2
    n = 0
    for cx in centers:
        x0, x1 = max(0, cx - _SAMPLE_HALF), min(w, cx + _SAMPLE_HALF + 1)
        y0, y1 = max(0, cy - _SAMPLE_HALF), min(h, cy + _SAMPLE_HALF + 1)
        if yellow[y0:y1, x0:x1].sum() >= _SAMPLE_PIX_THRESH:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Badge OCR
# ---------------------------------------------------------------------------

# OcrCallable: PIL Image → list of (bbox, text, conf) — same shape as
# ``promo_tournament_ocr.ocr_crop``. Passed in to keep this module
# decoupled from PaddleOCR import (and lets tests inject fakes).
OcrCallable = Callable[[Image.Image], list]


def _read_core_badge(crop: Image.Image, ocr_fn: OcrCallable) -> tuple[Optional[int], Optional[str], Optional[float]]:
    """Return (core_int 0..7, raw_text, confidence). None if unparseable."""
    badge = crop.crop((_BADGE_X1, 0, _BADGE_X2, crop.height))
    big = badge.resize((badge.width * 4, badge.height * 4), Image.LANCZOS)
    items = ocr_fn(big)
    if not items:
        return None, None, None
    # Concatenate all tokens; pick the first non-empty.
    text = " ".join(t for _b, t, _c in items if t).strip()
    confs = [c for _b, _t, c in items]
    avg_conf = sum(confs) / len(confs) if confs else None
    if not text:
        return None, None, avg_conf
    upper = text.upper().replace(" ", "")
    if upper == "MAX":
        return 7, text, avg_conf
    digits = "".join(ch for ch in upper if ch.isdigit())
    if digits:
        try:
            n = int(digits)
            if 1 <= n <= 7:
                return n, text, avg_conf
        except ValueError:
            pass
    return None, text, avg_conf


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LbCoreResult:
    stars: int                  # 0..3 yellow stars detected
    core: Optional[int]         # 1..7 when badge present and parsed; else None
    badge_present: bool
    badge_text: Optional[str]   # raw OCR (e.g. "MAX", "02")
    confidence: Optional[float] # PaddleOCR avg conf when badge OCR'd

    @property
    def text(self) -> str:
        """Human-readable summary for the ``text`` column of PromoExtractedField."""
        s_word = "star" if self.stars == 1 else "stars"
        if self.badge_present and self.badge_text:
            return f"{self.stars} {s_word} + {self.badge_text}"
        return f"{self.stars} {s_word}"

    @property
    def normalized(self) -> str:
        """Canonical class key — one of the 12 entries in
        :data:`promo_tournament_lb_core_audit.AUDIT_KEYS`.

        - LB < 3 → ``"lb0"``, ``"lb1"``, ``"lb2"``.
        - LB == 3, no badge → ``"mlb_c0"`` (badge hidden when Core = 0).
        - LB == 3, badge ``"01".."06"`` → ``"mlb_c1".."mlb_c6"``.
        - LB == 3, badge ``"MAX"`` → ``"mlb_max"`` (Core 7).
        - LB == 3, badge present but OCR garbage → ``"unknown"``.
        """
        if self.stars < 3:
            return f"lb{self.stars}"
        if not self.badge_present:
            return "mlb_c0"
        if self.core is None:
            return "unknown"
        if self.core == 7:
            return "mlb_max"
        return f"mlb_c{self.core}"


def detect_lb_core(crop: Image.Image, ocr_fn: OcrCallable) -> LbCoreResult:
    """Run star + badge detection on a single 85×30 lb_core crop."""
    arr = np.asarray(crop.convert("RGB"))
    badge = _badge_present(arr)
    stars = _count_yellow_stars(arr, badge)
    core, badge_text, conf = (None, None, None)
    if badge:
        core, badge_text, conf = _read_core_badge(crop, ocr_fn)
    return LbCoreResult(
        stars=stars,
        core=core,
        badge_present=badge,
        badge_text=badge_text,
        confidence=conf,
    )


# ---------------------------------------------------------------------------
# Audit support — re-run the detector on auto rows in a single class
# ---------------------------------------------------------------------------


def reclassify_class_auto_rows(session, class_key: str, ocr_fn: OcrCallable) -> tuple[int, int]:
    """Re-run :func:`detect_lb_core` on every auto row in ``class_key``.

    Mirrors :func:`promo_tournament_doll_match.reclassify_class_auto_rows`.
    Filters to ``region_slug LIKE '%.lb_core' AND normalized=class_key
    AND manually_corrected=False``, batch-loads source screenshots,
    re-runs detection, updates ``normalized`` / ``text`` / ``confidence``
    in place. Manually-corrected rows are intentionally untouched.

    Returns ``(examined, updated)``. The detector is deterministic for a
    fixed source image, so this is a no-op until detector thresholds
    change — the button exists as a safety hatch for future tuning.
    """
    from sqlmodel import select as _select

    from ..data.models import PromoExtractedField, PromoMatchScreenshot
    from .promo_tournament_regions import PLAYER_LOADOUT

    lb_core_bbox = {
        r.slug: r.bbox for r in PLAYER_LOADOUT if r.slug.endswith(".lb_core")
    }

    rows = session.exec(
        _select(PromoExtractedField).where(
            PromoExtractedField.region_slug.like("%.lb_core"),
            PromoExtractedField.normalized == class_key,
            PromoExtractedField.manually_corrected == False,  # noqa: E712
        )
    ).all()
    if not rows:
        return 0, 0

    shot_ids = list({r.screenshot_id for r in rows})
    shots = session.exec(
        _select(PromoMatchScreenshot).where(PromoMatchScreenshot.id.in_(shot_ids))
    ).all()
    shot_by_id = {s.id: s for s in shots}
    images: dict[int, Image.Image] = {}

    examined = 0
    updated = 0
    for row in rows:
        bbox = lb_core_bbox.get(row.region_slug)
        shot = shot_by_id.get(row.screenshot_id)
        if bbox is None or shot is None:
            continue
        img = images.get(shot.id)
        if img is None:
            try:
                img = Image.open(shot.file_path).convert("RGB")
            except OSError:
                continue
            images[shot.id] = img
        result = detect_lb_core(img.crop(bbox), ocr_fn)
        examined += 1
        if (
            row.normalized != result.normalized
            or row.text != result.text
            or row.confidence != result.confidence
        ):
            row.normalized = result.normalized
            row.text = result.text
            row.confidence = result.confidence
            session.add(row)
            updated += 1
    session.commit()
    return examined, updated
