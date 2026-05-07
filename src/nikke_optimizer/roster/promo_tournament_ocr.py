"""Promotion Tournament / Champions Duel OCR pipeline.

Runs PaddleOCR over the labelled regions for each screenshot and
persists results in ``PromoExtractedField``. Skips image-only regions
(character portraits and doll/treasure icons — those are for portrait
matching, not OCR). Character-name fields are fuzzy-matched against
the ``Character`` DB so truncated OCR text (``"Liberali"``) still
resolves to the right Nikke (``"Liberalio"``).

Round-result strips on the match-overview screen get a special pass:
the strip is OCR'd, then the x-positions of the ``WIN`` / ``LOSE``
tokens determine which side won the round. The derived
``round{N}_winner`` (``'left'`` / ``'right'``) is stored as its own
extracted field so the UI / analytics can compute match scores
without re-parsing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlmodel import Session, select

from ..data.models import Character, PromoExtractedField
from .promo_tournament_regions import Region, regions_for_kind

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Slug classification
# ---------------------------------------------------------------------------

# Image-only regions — no OCR.
_SKIP_SLUGS = frozenset(
    {f"char{i}.{kind}" for i in range(1, 6) for kind in ("portrait", "doll")}
)
# CP / damage / heal — store digits-only canonical form.
_NUMBER_SLUG_RE = re.compile(
    r"^(team_cp|char\d\.cp|(left|right)\.char\d\.(atk|def|heal))$"
)
# HP percentage.
_PERCENT_SLUG_RE = re.compile(r"^(left|right)\.char\d\.hp$")
# Character name — fuzzy-match against Character DB.
_CHAR_NAME_SLUG_RE = re.compile(r"^(left|right)\.char\d\.name$")
# Round-result strip on overview — also derives a roundN_winner field.
_ROUND_STRIP_SLUG_RE = re.compile(r"^round(\d)_strip$")


def classify_slug(slug: str) -> str:
    """Return one of:

    * ``"skip"`` — image-only, no OCR
    * ``"number"`` — digits-only canonical form
    * ``"percent"`` — percentage canonical form
    * ``"char_name"`` — fuzzy-match against Character DB
    * ``"round_strip"`` — overview round result (derives winner side)
    * ``"text"`` — plain text, no normalization
    """
    if slug in _SKIP_SLUGS:
        return "skip"
    if _NUMBER_SLUG_RE.match(slug):
        return "number"
    if _PERCENT_SLUG_RE.match(slug):
        return "percent"
    if _CHAR_NAME_SLUG_RE.match(slug):
        return "char_name"
    if _ROUND_STRIP_SLUG_RE.match(slug):
        return "round_strip"
    return "text"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# Match a comma-formatted number ("630,336") or a bare run of digits.
_NUMBER_TOKEN_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?")


def normalize_number(text: Optional[str]) -> Optional[str]:
    """Return the canonical digits-only form of the largest number in ``text``.

    Two-tier strategy:

    * **Comma-formatted token wins.** OCR sometimes appends a stray
      icon-as-digit after a clean number ("630,336 0" — the trailing
      "0" is an icon). When any token contains a comma, take the
      longest comma-formatted one and drop the rest.
    * **Otherwise, concatenate all digit runs.** Some game UIs render
      thousand-separators as spaces ("142 887"), which should round
      to "142887".

    >>> normalize_number("3,587,616")
    '3587616'
    >>> normalize_number("630,336 0")
    '630336'
    >>> normalize_number("142 887")
    '142887'
    >>> normalize_number("--") is None
    True
    """
    if not text:
        return None
    tokens = _NUMBER_TOKEN_RE.findall(text)
    if not tokens:
        return None
    comma_tokens = [t for t in tokens if "," in t]
    if comma_tokens:
        return max(comma_tokens, key=len).replace(",", "")
    # No commas — assume space-separators. Concatenate all digit runs.
    return "".join(tokens)


def normalize_percent(text: Optional[str]) -> Optional[str]:
    """Extract a percentage like ``"100.00%"`` from arbitrary text.

    >>> normalize_percent("100.00%")
    '100.00%'
    >>> normalize_percent("0%")
    '0%'
    >>> normalize_percent("disconnected") is None
    True
    """
    if not text:
        return None
    m = _PERCENT_RE.search(text)
    return m.group(0) + "%" if m else None


# ---------------------------------------------------------------------------
# Round-strip side detection
# ---------------------------------------------------------------------------


def parse_round_winner(items) -> Optional[str]:
    """Given PaddleOCR results for a round strip, return ``'left'`` or
    ``'right'`` based on the x-position of the WIN token relative to LOSE.

    Returns ``None`` if either token is missing or both end up on the same
    side (ambiguous). ``items`` is the raw PaddleOCR output:
    ``[(bbox, text, conf), ...]`` where ``bbox`` is four ``(x, y)`` corners.
    """
    win_x: Optional[float] = None
    lose_x: Optional[float] = None
    for bbox, text, _conf in items:
        text_norm = (text or "").upper().strip()
        if not text_norm:
            continue
        try:
            xs = [pt[0] for pt in bbox]
        except (TypeError, IndexError):
            continue
        cx = sum(xs) / len(xs)
        # Use exact word match where possible; in-game labels are clean
        # but OCR sometimes glues neighbours.
        if "LOSE" in text_norm and lose_x is None:
            lose_x = cx
        elif "WIN" in text_norm and win_x is None:
            win_x = cx
    if win_x is None or lose_x is None:
        return None
    if abs(win_x - lose_x) < 5:
        return None  # both on top of each other — ambiguous
    return "left" if win_x < lose_x else "right"


# ---------------------------------------------------------------------------
# Character-name fuzzy match
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharIndex:
    """Cached (character_id, name) tuples for fuzzy matching."""

    entries: tuple[tuple[int, str], ...]

    @classmethod
    def from_session(cls, session: Session) -> "CharIndex":
        rows = session.exec(select(Character.id, Character.name)).all()
        return cls(entries=tuple((int(cid), str(name)) for cid, name in rows))


def match_character(
    name: Optional[str], index: CharIndex, *, threshold: float = 70.0
) -> Optional[tuple[int, str, float]]:
    """Return ``(character_id, matched_name, score)`` for the best fuzzy match.

    Uses ``rapidfuzz.process.extractOne`` with the WRatio scorer, which
    handles partial matches well — useful for OCR truncations like
    ``"Liberali"`` → ``"Liberalio"``. ``None`` when no candidate scores
    above ``threshold``.
    """
    if not name or not index.entries:
        return None
    from rapidfuzz import fuzz, process

    candidates = {cid: cname for cid, cname in index.entries}
    best = process.extractOne(
        name.strip(), candidates, scorer=fuzz.WRatio, score_cutoff=threshold
    )
    if best is None:
        return None
    matched_name, score, cid = best
    return int(cid), str(matched_name), float(score)


# ---------------------------------------------------------------------------
# OCR engine — lazy singleton
# ---------------------------------------------------------------------------


_paddle_instance = None


def _get_paddle():
    """Lazy-init a single PaddleOCR instance (~5–10s the first call)."""
    global _paddle_instance
    if _paddle_instance is None:
        from paddleocr import PaddleOCR

        # In-game text is always horizontal + the crops are already
        # rectified, so disable the orientation / unwarping pipeline
        # stages to keep per-call latency down.
        _paddle_instance = PaddleOCR(
            lang="en",
            use_textline_orientation=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
        )
    return _paddle_instance


def ocr_crop(crop) -> list[tuple[list, str, float]]:
    """Run OCR on a PIL crop. Returns ``[(bbox, text, confidence), ...]``.

    Adapted to PaddleOCR 3.x's new ``predict`` API which returns a list
    of ``OCRResult`` objects with parallel ``rec_polys`` / ``rec_texts``
    / ``rec_scores`` arrays.
    """
    import numpy as np

    arr = np.asarray(crop)
    paddle = _get_paddle()
    raw = paddle.predict(arr)
    if not raw:
        return []
    out: list[tuple[list, str, float]] = []
    for result in raw:
        polys = result.get("rec_polys", []) or []
        texts = result.get("rec_texts", []) or []
        scores = result.get("rec_scores", []) or []
        for poly, text, score in zip(polys, texts, scores):
            # ``poly`` is a numpy array of 4 (x, y) corners — convert
            # to a plain list of [x, y] pairs for downstream callers
            # that may not have numpy.
            try:
                bbox = [[float(pt[0]), float(pt[1])] for pt in poly]
            except (TypeError, IndexError):
                bbox = []
            out.append((bbox, str(text), float(score)))
    return out


def _flatten_text(items: list[tuple[list, str, float]]) -> tuple[str, float]:
    if not items:
        return "", 0.0
    texts = [t for (_b, t, _c) in items if t]
    confs = [c for (_b, _t, c) in items]
    text = " ".join(texts).strip()
    conf = sum(confs) / len(confs) if confs else 0.0
    return text, conf


# ---------------------------------------------------------------------------
# Per-screenshot extraction
# ---------------------------------------------------------------------------


@dataclass
class FieldExtraction:
    slug: str
    text: Optional[str]
    normalized: Optional[str]
    character_id: Optional[int]
    character_match_score: Optional[float]
    confidence: Optional[float]


def extract_region(image, region: Region, *, char_index: CharIndex) -> list[FieldExtraction]:
    """OCR one region. Returns ``[]`` for image-only slugs, one row for
    most slugs, two rows for round_strip (raw + derived winner)."""
    classification = classify_slug(region.slug)
    if classification == "skip":
        return []
    x1, y1, x2, y2 = region.bbox
    crop = image.crop((x1, y1, x2, y2))
    items = ocr_crop(crop)
    raw_text, conf = _flatten_text(items)
    text = raw_text or None
    confidence = conf if items else None

    out: list[FieldExtraction] = []

    if classification == "number":
        out.append(
            FieldExtraction(
                slug=region.slug,
                text=text,
                normalized=normalize_number(text),
                character_id=None,
                character_match_score=None,
                confidence=confidence,
            )
        )
    elif classification == "percent":
        out.append(
            FieldExtraction(
                slug=region.slug,
                text=text,
                normalized=normalize_percent(text),
                character_id=None,
                character_match_score=None,
                confidence=confidence,
            )
        )
    elif classification == "char_name":
        match = match_character(text, char_index)
        cid, _matched, score = match if match else (None, None, None)
        out.append(
            FieldExtraction(
                slug=region.slug,
                text=text,
                normalized=None,
                character_id=cid,
                character_match_score=score,
                confidence=confidence,
            )
        )
    elif classification == "round_strip":
        out.append(
            FieldExtraction(
                slug=region.slug,
                text=text,
                normalized=None,
                character_id=None,
                character_match_score=None,
                confidence=confidence,
            )
        )
        m = _ROUND_STRIP_SLUG_RE.match(region.slug)
        if m is not None:
            n = m.group(1)
            winner = parse_round_winner(items)
            out.append(
                FieldExtraction(
                    slug=f"round{n}_winner",
                    text=None,
                    normalized=winner,
                    character_id=None,
                    character_match_score=None,
                    confidence=confidence,
                )
            )
    else:  # plain text
        out.append(
            FieldExtraction(
                slug=region.slug,
                text=text,
                normalized=None,
                character_id=None,
                character_match_score=None,
                confidence=confidence,
            )
        )
    return out


def extract_screenshot(
    image, kind: str, *, char_index: CharIndex
) -> list[FieldExtraction]:
    """Extract every region for a screenshot of the given kind."""
    out: list[FieldExtraction] = []
    for region in regions_for_kind(kind):
        out.extend(extract_region(image, region, char_index=char_index))
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def persist_extractions(
    session: Session,
    screenshot_id: int,
    extractions: Iterable[FieldExtraction],
) -> int:
    """Upsert ``PromoExtractedField`` rows. Returns the count written."""
    n = 0
    for ext in extractions:
        existing = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id == screenshot_id,
                PromoExtractedField.region_slug == ext.slug,
            )
        ).first()
        if existing is None:
            session.add(
                PromoExtractedField(
                    screenshot_id=screenshot_id,
                    region_slug=ext.slug,
                    text=ext.text,
                    normalized=ext.normalized,
                    character_id=ext.character_id,
                    character_match_score=ext.character_match_score,
                    confidence=ext.confidence,
                )
            )
        else:
            existing.text = ext.text
            existing.normalized = ext.normalized
            existing.character_id = ext.character_id
            existing.character_match_score = ext.character_match_score
            existing.confidence = ext.confidence
            session.add(existing)
        n += 1
    session.commit()
    return n


def has_extractions(session: Session, screenshot_id: int) -> bool:
    """Whether any extracted fields exist for a screenshot."""
    return (
        session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id == screenshot_id
            ).limit(1)
        ).first()
        is not None
    )
