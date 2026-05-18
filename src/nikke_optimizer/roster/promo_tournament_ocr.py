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

# Image-only regions — no OCR. Includes both per-Champion-loadout char
# portrait/doll AND rookie arena portrait/doll (also image-only).
_SKIP_SLUGS = frozenset(
    {f"char{i}.{kind}" for i in range(1, 6) for kind in ("portrait", "doll")}
    | {
        f"{side}.char{i}.{kind}"
        for side in ("opp", "my")
        for i in range(1, 6)
        for kind in ("portrait", "doll")
    }
)
# LB stars + Core badge — color-based star count + targeted badge OCR
# handled by promo_tournament_lb_core.detect_lb_core. Now matches both
# the Champion popup slug shape and the rookie arena `(opp|my).charN.lb_core`.
_LB_CORE_SLUG_RE = re.compile(r"^(?:(?:opp|my)\.)?char\d\.lb_core$")
# Comma-formatted / multi-digit numeric fields with thousand separators
# — CPs, sums in the multi-thousands. Keep this strict; the new
# integer-level slug below handles small (1-3 digit) values that
# shouldn't be confused for these.
_NUMBER_SLUG_RE = re.compile(
    r"^(team_cp|player_level|char\d\.cp|"
    r"(left|right)\.char\d\.(atk|def|heal)|"
    r"(?:opponent|my)_team_cp"
    r")$"
)
# Small integer level — 1-3 digit; used for:
#   * Rookie arena per-Nikke level under each tile: `(opp|my).charN.level`
#   * Rookie opponent.png my_player_level + 3 candidate cards' level
# Normalized to digits-only by the same helper as `number` but routes
# through a tighter token filter (single digit run, ignore stray noise).
_LEVEL_SLUG_RE = re.compile(
    r"^(my_player_level|opp\d\.level|(?:opp|my)\.char\d\.level)$"
)
# HP percentage.
_PERCENT_SLUG_RE = re.compile(r"^(left|right)\.char\d\.hp$")
# Character name — fuzzy-match against Character DB. Three shapes:
#   * ``left.char{N}.name`` / ``right.char{N}.name`` — from results_duel
#   * ``char{N}.name``                              — from player_loadout /
#     player_data (Arena Info popup) cards
#   * ``(opp|my).char{N}.name``                      — from rookie_loadout
_CHAR_NAME_SLUG_RE = re.compile(
    r"^(?:(?:left|right|opp|my)\.)?char\d\.name$"
)
# Plain text — no normalization, no DB match. Rookie opponent.png
# `oppN.name` lands here (player names, not Nikke character names) plus
# the existing `player_name` / `opponent_name` / `my_name` fields.
_PLAIN_NAME_SLUG_RE = re.compile(
    r"^(?:player_name|opponent_name|my_name|opp\d\.name)$"
)
# Round-result strip on overview — also derives a roundN_winner field.
_ROUND_STRIP_SLUG_RE = re.compile(r"^round(\d)_strip$")


def classify_slug(slug: str) -> str:
    """Return one of:

    * ``"skip"`` — image-only, no OCR
    * ``"lb_core"`` — color star count + targeted badge OCR
    * ``"number"`` — digits-only canonical form (large multi-digit
      values like CP)
    * ``"level"`` — small 1-3 digit integer (per-Nikke level, player
      level). Same normalizer as number but tighter expectations.
    * ``"percent"`` — percentage canonical form
    * ``"char_name"`` — fuzzy-match against Character DB
    * ``"round_strip"`` — overview round result (derives winner side)
    * ``"text"`` — plain text, no normalization
    """
    if slug in _SKIP_SLUGS:
        return "skip"
    if _LB_CORE_SLUG_RE.match(slug):
        return "lb_core"
    if _NUMBER_SLUG_RE.match(slug):
        return "number"
    if _LEVEL_SLUG_RE.match(slug):
        return "level"
    if _PERCENT_SLUG_RE.match(slug):
        return "percent"
    if _CHAR_NAME_SLUG_RE.match(slug):
        return "char_name"
    if _PLAIN_NAME_SLUG_RE.match(slug):
        return "text"
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


def _score_candidate(query: str, name: str) -> float:
    """Mean of ``fuzz.ratio`` and ``fuzz.partial_ratio``.

    ``WRatio`` was the previous scorer but its
    ``max(ratio, partial_ratio·0.9, …)`` formulation throws away the
    length signal: for query ``"Vesti: Tactical"``, both ``"Vesti"``
    and ``"Vesti: Tactical Upgrade"`` score exactly 90, and
    ``process.extractOne`` deterministically picks the first by ID
    (the base name).

    The arithmetic mean preserves the substring signal (``partial_ratio``)
    while keeping a length-sensitive component (``ratio``), so the
    canonical alt-form correctly outscores the base when the OCR text
    is the alt: ``Vesti`` → 75, ``Vesti: Tactical Upgrade`` → 89.5.
    """
    from rapidfuzz import fuzz

    return (fuzz.ratio(query, name) + fuzz.partial_ratio(query, name)) / 2.0


def match_character(
    name: Optional[str], index: CharIndex, *, threshold: float = 70.0
) -> Optional[tuple[int, str, float]]:
    """Return ``(character_id, matched_name, score)`` for the best fuzzy match.

    Uses a colon-aware pre-filter plus the mean ratio + partial_ratio
    scorer (see ``_score_candidate``). When the OCR query contains a
    colon (an alt-form like ``"Vesti: Tactical"``) the search pool is
    restricted to candidates whose canonical name also contains a
    colon — the in-game UI only displays the colon-form for alts, so
    a colon in the OCR text is a strong signal of the source's
    colon-form. Falls back to the unfiltered pool if the filtered
    best falls below threshold.

    Handles OCR truncations naturally: ``"Liberali"`` → ``"Liberalio"``,
    ``"Eunhwa: Tactic"`` → ``"Eunhwa: Tactical Upgrade"``.
    """
    if not name or not index.entries:
        return None
    q = name.strip()
    if not q:
        return None

    has_colon = ":" in q
    filtered: list[tuple[int, str]] = (
        [(cid, n) for cid, n in index.entries if ":" in n]
        if has_colon else []
    )
    pool: list[tuple[int, str]] = filtered or list(index.entries)

    best_cid, best_name, best_score = -1, "", -1.0
    for cid, n in pool:
        s = _score_candidate(q, n)
        if s > best_score:
            best_cid, best_name, best_score = cid, n, s

    # If the colon-filtered pool's winner is below threshold, retry
    # the full pool — the OCR colon may be noise, or the canonical
    # name might lack a colon for an alt-only character.
    if best_score < threshold and filtered:
        for cid, n in index.entries:
            if (cid, n) in filtered:
                continue  # already scored
            s = _score_candidate(q, n)
            if s > best_score:
                best_cid, best_name, best_score = cid, n, s

    if best_score < threshold:
        return None
    return int(best_cid), str(best_name), float(best_score)


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

    # lb_core is color-driven (stars) + targeted OCR on a sub-crop (badge),
    # so it doesn't run the full-region ocr_crop pass that other slugs use.
    if classification == "lb_core":
        from .promo_tournament_lb_core import detect_lb_core
        result = detect_lb_core(crop, ocr_crop)
        return [
            FieldExtraction(
                slug=region.slug,
                text=result.text,
                normalized=result.normalized,
                character_id=None,
                character_match_score=None,
                confidence=result.confidence,
            )
        ]

    # Level crops are small (44×50 in rookie arena) and PaddleOCR's
    # text DETECTOR sometimes misses them entirely — returning [] even
    # though the digits are clearly visible. Upscaling 3× before OCR
    # fixes detection without changing the high-confidence reads on
    # crops that already worked (verified: slots 1-5 all read "656"
    # at 0.99 confidence after 3× upscale).
    if classification == "level":
        crop = crop.resize((crop.width * 3, crop.height * 3))

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
    elif classification == "level":
        # Same digits-only normalization as `number`, but for small
        # 1-3 digit values (per-Nikke / player level). A separate
        # bucket lets future audits distinguish "expected big" from
        # "expected small" without changing the storage shape.
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
        if match is None and items:
            # Low-confidence noise tokens sometimes garble the start of
            # a name ("1OWA White:" — "1OWA" at conf 0.74 is noise,
            # "White:" at conf 0.997 is clean). The flattened-text
            # score falls below threshold but the high-confidence
            # subset alone matches. Retry once with only tokens at
            # conf >= 0.85; if that resolves, use the retry result.
            high_conf_text = " ".join(
                t for (_b, t, c) in items if c >= 0.85 and t
            ).strip()
            if high_conf_text and high_conf_text != text:
                match = match_character(high_conf_text, char_index)
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
    image, kind: str, *, char_index: CharIndex,
    only_slugs: Optional[frozenset[str]] = None,
) -> list[FieldExtraction]:
    """Extract every region for a screenshot of the given kind.

    When ``only_slugs`` is provided, skip regions whose slug isn't in
    the set. Used by the ``backfill-extractions`` CLI command to run
    extraction only for region types added in a later Phase, without
    re-OCR'ing fields that already exist.
    """
    out: list[FieldExtraction] = []
    for region in regions_for_kind(kind):
        if only_slugs is not None and region.slug not in only_slugs:
            continue
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


def missing_slugs(
    session: Session, screenshot_id: int, kind: str
) -> frozenset[str]:
    """Region slugs from the schema with no PromoExtractedField row yet.

    Used by ``backfill-extractions`` to run extraction only for region
    types added after the screenshot was originally ingested. Derived
    slugs (e.g. ``round{N}_winner``) are not considered — they're
    emitted alongside their parent slug, so missing the parent implies
    missing the derived.
    """
    canonical = {r.slug for r in regions_for_kind(kind)}
    existing = set(
        session.exec(
            select(PromoExtractedField.region_slug).where(
                PromoExtractedField.screenshot_id == screenshot_id
            )
        ).all()
    )
    return frozenset(canonical - existing)


def _resolve_side(
    loadout_player: str, overview_names: dict[str, str]
) -> Optional[str]:
    """Return ``"left"`` / ``"right"`` for the loadout's player, or ``None``
    if neither overview name matches even fuzzily.

    Match tiers (most strict first):
    1. Exact case-sensitive
    2. Exact case-insensitive
    3. Fuzzy ``fuzz.ratio`` ≥ 60 — picks the side with the higher score.
       Empty / missing overview names are treated as 0 score.
    """
    lp = loadout_player.strip()
    left = (overview_names.get("left_name") or "").strip()
    right = (overview_names.get("right_name") or "").strip()
    if not lp or (not left and not right):
        return None
    if left == lp:
        return "left"
    if right == lp:
        return "right"
    if left and left.lower() == lp.lower():
        return "left"
    if right and right.lower() == lp.lower():
        return "right"
    from rapidfuzz import fuzz

    left_score = fuzz.ratio(lp.lower(), left.lower()) if left else 0
    right_score = fuzz.ratio(lp.lower(), right.lower()) if right else 0
    if max(left_score, right_score) < 60:
        return None
    return "left" if left_score >= right_score else "right"


def backfill_portrait_character_ids(session: Session) -> tuple[int, int]:
    """Label each loadout's char1..5.portrait with the character_id read
    from the SAME-ROUND duel result at the matching slot.

    The loadout screen shows portraits but no character names. The duel
    result for the same round shows both — names *and* implied slots
    (5 chars per side, in order). Combining them gives us a reliable
    portrait → character mapping with zero Vision API calls:

    1. For each loadout, find its same-match same-round
       ``results_duel`` screenshot.
    2. Match the loadout's player_name OCR against the same match's
       overview ``left_name`` / ``right_name`` to determine which side
       of the duel this loadout corresponds to.
    3. Copy the ``character_id`` (and OCR'd raw name as ``text``) from
       the duel's ``{side}.char{N}.name`` extraction into the loadout's
       ``char{N}.portrait`` row.

    Returns ``(examined, updated)``.
    """
    # Lazy imports — avoid pulling these into headless test envs.
    from ..data.models import (
        PromoExtractedField as _Field,
        PromoMatchScreenshot as _Shot,
    )

    examined = 0
    updated = 0

    loadouts = session.exec(
        select(_Shot).where(_Shot.kind == "player_loadout")
    ).all()

    # Cache same-match overview names + duel screenshots so we don't
    # re-query for each of the (up to 10) loadouts in a match.
    overview_cache: dict[int, dict[str, str]] = {}
    duels_cache: dict[tuple[int, int], int] = {}

    def _overview_names(match_id: int) -> dict[str, str]:
        if match_id in overview_cache:
            return overview_cache[match_id]
        ov = session.exec(
            select(_Shot).where(
                _Shot.match_id == match_id, _Shot.kind == "results_overview"
            )
        ).first()
        names: dict[str, str] = {}
        if ov is not None:
            for f in session.exec(
                select(_Field).where(
                    _Field.screenshot_id == ov.id,
                    _Field.region_slug.in_(["left_name", "right_name"]),
                )
            ).all():
                if f.text:
                    names[f.region_slug] = f.text
        overview_cache[match_id] = names
        return names

    def _duel_id(match_id: int, round_no: int) -> int | None:
        key = (match_id, round_no)
        if key in duels_cache:
            return duels_cache[key]
        d = session.exec(
            select(_Shot).where(
                _Shot.match_id == match_id,
                _Shot.kind == "results_duel",
                _Shot.round_no == round_no,
            )
        ).first()
        duels_cache[key] = d.id if d else None
        return duels_cache[key]

    for loadout in loadouts:
        examined += 1
        # Find this loadout's player_name extraction.
        pn_field = session.exec(
            select(_Field).where(
                _Field.screenshot_id == loadout.id,
                _Field.region_slug == "player_name",
            )
        ).first()
        if pn_field is None or not pn_field.text:
            continue
        loadout_player = pn_field.text.strip()

        # Determine which side of the duel this loadout corresponds to.
        # Tries: exact match → case-insensitive → fuzzy ratio (handles
        # OCR drift like "AHIO" vs "AHH" being the same player).
        names = _overview_names(loadout.match_id)
        side = _resolve_side(loadout_player, names)
        if side is None:
            continue

        duel_id = _duel_id(loadout.match_id, loadout.round_no)
        if duel_id is None:
            continue

        # Pull the 5 duel name extractions for this side.
        duel_fields = session.exec(
            select(_Field).where(
                _Field.screenshot_id == duel_id,
                _Field.region_slug.like(f"{side}.char%.name"),
            )
        ).all()
        by_slug = {f.region_slug: f for f in duel_fields}

        for n in range(1, 6):
            duel_name = by_slug.get(f"{side}.char{n}.name")
            if duel_name is None:
                continue
            target_slug = f"char{n}.portrait"
            target = session.exec(
                select(_Field).where(
                    _Field.screenshot_id == loadout.id,
                    _Field.region_slug == target_slug,
                )
            ).first()
            new_text = duel_name.text
            new_cid = duel_name.character_id
            new_score = duel_name.character_match_score
            if target is None:
                target = _Field(
                    screenshot_id=loadout.id,
                    region_slug=target_slug,
                    text=new_text,
                    normalized=None,
                    character_id=new_cid,
                    character_match_score=new_score,
                    confidence=duel_name.confidence,
                )
                session.add(target)
                updated += 1
            elif (
                target.character_id != new_cid
                or target.text != new_text
                or target.character_match_score != new_score
            ):
                target.text = new_text
                target.character_id = new_cid
                target.character_match_score = new_score
                target.confidence = duel_name.confidence
                session.add(target)
                updated += 1
        session.commit()

    return examined, updated


def rematch_character_fields(session: Session) -> tuple[int, int]:
    """Re-run ``match_character`` on every stored ``*.name`` extraction.

    Useful when the matching algorithm changes but the OCR text itself
    is fine — avoids the 15-minute cost of a full ``--force-ocr``. Walks
    every ``PromoExtractedField`` whose slug ends in ``.name``, scores
    its existing ``text`` against the current Character DB, and updates
    ``character_id`` + ``character_match_score`` in place.

    Returns ``(rows_examined, rows_updated)``.
    """
    char_index = CharIndex.from_session(session)
    rows = session.exec(
        select(PromoExtractedField).where(
            PromoExtractedField.region_slug.like("%.name")
        )
    ).all()
    examined = 0
    updated = 0
    for row in rows:
        examined += 1
        if not row.text:
            new_cid, new_score = None, None
        else:
            match = match_character(row.text, char_index)
            if match is None:
                new_cid, new_score = None, None
            else:
                new_cid, _, new_score = match
        if (row.character_id != new_cid) or (
            row.character_match_score != new_score
        ):
            row.character_id = new_cid
            row.character_match_score = new_score
            session.add(row)
            updated += 1
    if updated:
        session.commit()
    return examined, updated
