"""Classify the doll / treasure tier on each loadout slot.

The ``char1..5.doll`` regions on a player_loadout screenshot are tiny
(33×37 px) hexagonal badges showing the equipped Doll or Treasure.
Five labeled exemplars live under
``<repo>/debug/labeled-doll-treasure-icons/`` — they're distinguished
primarily by border + interior **colour** (cyan / pink / dark purple
/ cream / orange). HSV mean-squared-distance against each exemplar
gives clean separation; no Vision API or perceptual hashing required.

Adds ``char{n}.doll`` rows to ``PromoExtractedField`` with the
canonical key in ``normalized`` and a human-readable display label
in ``text``. Doll slots without an equipped item (or with an
exemplar we don't have yet, e.g. R level-15) classify as
``"unknown"``.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from sqlmodel import Session, select

from ..data.models import PromoExtractedField, PromoMatchScreenshot
from .promo_tournament_regions import OVERVIEW, PLAYER_LOADOUT  # noqa: F401

log = logging.getLogger(__name__)


# Canonical key → exemplar filename. Add a new entry per labeled image
# the user provides. Pending: ``r_max`` (R level-15, no exemplar yet).
EXEMPLAR_FILES: dict[str, str] = {
    "r_partial": "has-r-doll-not-fully-leveld-up.png",
    "sr_partial": "has-sr-doll-not-fully-leveled-up.png",
    "sr_max": "has-sr-doll-level-15-fully-leveld-up.png",
    "treasure_partial": "has-treasure-not-fully-leveled-up.png",
    "treasure_max": "has-treasure-phase-3-fully-evel-up.png",
}

# Human-readable labels for the UI pill.
DISPLAY_LABELS: dict[str, str] = {
    "r_partial": "R",
    "r_max": "R ★15",
    "sr_partial": "SR",
    "sr_max": "SR ★15",
    "treasure_partial": "Treasure",
    "treasure_max": "Treasure φ3",
    "unknown": "—",
}

# Standard size we resize both exemplars + queries to before comparing.
_STANDARD_SIZE = (32, 32)
# Mean squared HSV distance ceiling above which we treat a crop as
# "no doll equipped" / unsupported tier. Empirically, self-match is
# < 0.001 and cross-class is > 0.05.
_NO_MATCH_THRESHOLD = 0.05

# Doll-region slugs — the per-character hexagonal badge inside each
# loadout card.
_DOLL_SLUGS = tuple(f"char{n}.doll" for n in range(1, 6))
_DOLL_BBOX: dict[str, tuple[int, int, int, int]] = {
    r.slug: r.bbox for r in PLAYER_LOADOUT if r.slug in _DOLL_SLUGS
}


def default_label_dir() -> Path:
    """Repo-root-relative location of the labeled exemplars."""
    return (
        Path(__file__).resolve().parents[3]
        / "debug"
        / "labeled-doll-treasure-icons"
    )


# ---------------------------------------------------------------------------
# Exemplar loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def load_exemplars(label_dir: str) -> dict[str, "object"]:
    """Load + preprocess every labeled exemplar image.

    Returns a mapping of canonical key → HSV float ndarray of shape
    ``(32, 32, 3)`` with values in ``[0, 1]``. Missing files are
    silently skipped — the classifier just won't emit those classes.
    Cache is keyed on the directory so repeated calls within a
    process are instant.
    """
    import numpy as np
    from PIL import Image

    out: dict[str, "object"] = {}
    base = Path(label_dir)
    for key, fname in EXEMPLAR_FILES.items():
        path = base / fname
        if not path.is_file():
            log.warning("doll-match exemplar missing: %s", path)
            continue
        out[key] = _hsv_array(Image.open(path).convert("RGB"))
    return out


def _hsv_array(img):
    """Resize to standard size and return HSV float array in [0, 1]."""
    import numpy as np
    from PIL import Image

    resized = img.resize(_STANDARD_SIZE, Image.LANCZOS)
    return np.asarray(resized.convert("HSV"), dtype=np.float32) / 255.0


def clear_exemplar_cache() -> None:
    load_exemplars.cache_clear()


# ---------------------------------------------------------------------------
# Distance / classification
# ---------------------------------------------------------------------------


def _hsv_distance(query, exemplar) -> float:
    """Mean of squared per-pixel HSV differences with hue wrap-around.

    Hue is circular (0 wraps to 1), so we use ``min(|h1-h2|, 1-|h1-h2|)``
    rather than raw difference. Saturation and value are linear.
    """
    import numpy as np

    qh, qs, qv = query[..., 0], query[..., 1], query[..., 2]
    eh, es, ev = exemplar[..., 0], exemplar[..., 1], exemplar[..., 2]
    dh = np.abs(qh - eh)
    dh = np.minimum(dh, 1.0 - dh)
    ds = np.abs(qs - es)
    dv = np.abs(qv - ev)
    return float(((dh ** 2 + ds ** 2 + dv ** 2) / 3.0).mean())


@dataclass(frozen=True)
class DollClassification:
    canonical_key: str   # 'sr_max' / 'unknown' / etc.
    display_label: str   # 'SR ★15' / '—' / etc.
    distance: float      # mean squared HSV distance to the chosen exemplar
    confidence: float    # 1 - distance, clamped to [0, 1]


def classify_doll_crop(
    crop,
    exemplars: dict[str, "object"],
    *,
    threshold: float = _NO_MATCH_THRESHOLD,
) -> Optional[DollClassification]:
    """Classify a PIL crop against the exemplar dict.

    Returns ``None`` when no exemplars are loaded. Otherwise always
    returns a classification — either the best match (if its
    distance is below ``threshold``) or ``"unknown"``.
    """
    if not exemplars:
        return None
    q = _hsv_array(crop)
    best_key, best_d = None, float("inf")
    for key, ex in exemplars.items():
        d = _hsv_distance(q, ex)
        if d < best_d:
            best_key, best_d = key, d

    if best_d > threshold:
        return DollClassification(
            canonical_key="unknown",
            display_label=DISPLAY_LABELS["unknown"],
            distance=best_d,
            confidence=0.0,
        )
    return DollClassification(
        canonical_key=best_key,
        display_label=DISPLAY_LABELS.get(best_key, best_key),
        distance=best_d,
        confidence=max(0.0, min(1.0, 1.0 - best_d * 4.0)),
    )


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def backfill_doll_classifications(
    session: Session,
    *,
    label_dir: Optional[Path] = None,
) -> tuple[int, int, Counter]:
    """Walk every player_loadout screenshot and classify all 5 doll
    slots, persisting results to ``PromoExtractedField``.

    Returns ``(examined, updated, class_counts)``. Idempotent —
    re-runs only update rows whose canonical_key changed.
    """
    from PIL import Image

    label_dir = Path(label_dir) if label_dir else default_label_dir()
    exemplars = load_exemplars(str(label_dir))
    if not exemplars:
        log.warning("no exemplars loaded from %s — skipping", label_dir)
        return 0, 0, Counter()

    counts: Counter = Counter()
    examined = 0
    updated = 0

    loadouts = session.exec(
        select(PromoMatchScreenshot).where(
            PromoMatchScreenshot.kind == "player_loadout"
        )
    ).all()

    for loadout in loadouts:
        try:
            image = Image.open(loadout.file_path).convert("RGB")
        except OSError as exc:
            log.warning("doll-match open failed for %s: %s", loadout.file_path, exc)
            continue
        for slug in _DOLL_SLUGS:
            bbox = _DOLL_BBOX.get(slug)
            if bbox is None:
                continue
            crop = image.crop(bbox)
            classification = classify_doll_crop(crop, exemplars)
            if classification is None:
                continue
            examined += 1
            counts[classification.canonical_key] += 1

            existing = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.screenshot_id == loadout.id,
                    PromoExtractedField.region_slug == slug,
                )
            ).first()
            new_text = classification.display_label
            new_norm = classification.canonical_key
            new_conf = classification.confidence

            if existing is None:
                session.add(PromoExtractedField(
                    screenshot_id=loadout.id,
                    region_slug=slug,
                    text=new_text,
                    normalized=new_norm,
                    character_id=None,
                    character_match_score=None,
                    confidence=new_conf,
                ))
                updated += 1
            elif (
                existing.normalized != new_norm
                or existing.text != new_text
                or existing.confidence != new_conf
            ):
                existing.text = new_text
                existing.normalized = new_norm
                existing.confidence = new_conf
                # Make sure character_id stays None (defensive).
                existing.character_id = None
                existing.character_match_score = None
                session.add(existing)
                updated += 1
        session.commit()

    return examined, updated, counts
