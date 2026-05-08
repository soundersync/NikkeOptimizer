"""Image-hash-based player identification across tournament overviews.

When the OCR for a match's overview ``left_name`` / ``right_name`` is
empty or unmatchable, the canonical-loadout lookup has no string key
to search by. The in-game UI renders each player's name banner
identically across rounds, so the **pixel pattern** of the overview
name crop is a reliable identity that doesn't depend on OCR success.

This module provides perceptual hashing on those crops plus a
search helper that locates the same player's appearances across all
overview screenshots for canonical-loadout fallback. In-process
LRU-cached so repeated lookups across a session don't re-open the
same images.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..data.models import PromoMatch, PromoMatchScreenshot
from .promo_tournament_regions import OVERVIEW

log = logging.getLogger(__name__)


# Pull bbox coords out of the regions schema so this module stays the
# single source of truth for "how to crop a name region".
_OVERVIEW_NAME_BBOX: dict[str, tuple[int, int, int, int]] = {
    r.slug: r.bbox for r in OVERVIEW
    if r.slug in ("left_name", "right_name")
}

# Hamming-distance ceiling for "same player" verdict on the
# trim-normalized 256-bit hash. Empirical:
#   * same-side same-player: distance 0
#   * cross-side same-player: distance ~16 (margin/position noise)
#   * unrelated players:      distance 80+
# 32 bits / 256 (~12.5%) cleanly separates same-player from different
# players in the live data.
_MATCH_THRESHOLD_BITS = 32

# Plain 64-bit hash collides too easily on visually-flat crops
# (empty / similar backgrounds), so we use the trim-normalized
# 256-bit hash as the single similarity signal. ``_phash_8x8`` is
# kept as a quick sanity check for exact-pixel matches.
_PLAIN_EXACT_THRESHOLD = 0  # only accept plain matches at distance 0


@dataclass(frozen=True)
class HashMatch:
    """Result of a hash-based search for the same player elsewhere."""

    matched_screenshot_id: int
    matched_side: str       # "left" or "right" — which crop on that overview matched
    matched_match_id: int   # PromoMatch.id of the overview's match
    distance: int           # best Hamming distance found
    used_normalized: bool   # whether the trim-normalized hash was the winner


# ---------------------------------------------------------------------------
# Hashing primitives
# ---------------------------------------------------------------------------


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two equal-length unsigned hashes."""
    return (a ^ b).bit_count()


def _phash_8x8(crop) -> int:
    """64-bit perceptual hash via 8x8 grayscale mean-threshold.

    Standard "average hash" — robust to mild compression and resampling
    while preserving enough structure to differentiate distinct text
    patterns. Returns a single int holding 64 bits.
    """
    from PIL import Image

    g = crop.convert("L").resize((8, 8), Image.LANCZOS)
    pixels = list(g.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


def _trim_to_text_bbox(crop):
    """Find the tight bounding box of the dark/light text glyphs and
    return a crop limited to it.

    Same player rendered on the left vs the right of an overview gets
    a different surrounding background but identical text pixels;
    trimming whitespace before hashing makes those crops compare
    equal regardless of bracket-side position.

    Strategy: convert to grayscale, threshold at the median pixel
    value, take the bbox of pixels distant from the median (which
    are the text glyphs over a flatter background). Falls back to
    the original crop if the threshold finds nothing.
    """
    from PIL import Image, ImageChops

    g = crop.convert("L")
    pixels = list(g.getdata())
    median = sorted(pixels)[len(pixels) // 2]
    # Build a binary mask of pixels significantly different from
    # the median — the glyphs.
    mask = g.point(lambda v: 255 if abs(v - median) > 30 else 0, "L")
    bbox = mask.getbbox()
    if bbox is None:
        return crop
    # Add a tiny margin so we don't clip antialiased glyph edges.
    x1, y1, x2, y2 = bbox
    margin = 1
    w, h = g.size
    x1 = max(0, x1 - margin)
    y1 = max(0, y1 - margin)
    x2 = min(w, x2 + margin)
    y2 = min(h, y2 + margin)
    return crop.crop((x1, y1, x2, y2))


def _phash_normalized(crop) -> int:
    """Whitespace-trimmed 64-bit phash (32x8 resize for wider text).

    Designed to give matching results across left/right rendering of
    the same player — left/right crops differ in text horizontal
    position; trimming + a wider resize cancels that out.
    """
    from PIL import Image

    trimmed = _trim_to_text_bbox(crop)
    g = trimmed.convert("L").resize((32, 8), Image.LANCZOS)
    pixels = list(g.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


# ---------------------------------------------------------------------------
# Cached per-screenshot hashing
# ---------------------------------------------------------------------------


@lru_cache(maxsize=512)
def _cached_overview_hashes(file_path: str) -> dict[str, tuple[int, int]]:
    """Open an overview image once and return both side hashes.

    Cache key is the absolute file path. For each side returns a
    ``(plain_phash, normalized_phash)`` pair. Returns ``{}`` if the
    file can't be read.
    """
    from PIL import Image

    try:
        img = Image.open(file_path).convert("RGB")
    except OSError as exc:
        log.warning("overview hash open failed for %s: %s", file_path, exc)
        return {}
    out: dict[str, tuple[int, int]] = {}
    for slug, bbox in _OVERVIEW_NAME_BBOX.items():
        crop = img.crop(bbox)
        out[slug] = (_phash_8x8(crop), _phash_normalized(crop))
    return out


def overview_hashes(screenshot: PromoMatchScreenshot) -> dict[str, tuple[int, int]]:
    """Return cached ``{side: (plain, normalized)}`` for an overview screenshot."""
    if screenshot.kind != "results_overview":
        return {}
    return _cached_overview_hashes(screenshot.file_path)


def clear_hash_cache() -> None:
    """Forget cached hashes — useful in tests."""
    _cached_overview_hashes.cache_clear()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def find_canonical_match_via_image(
    session: Session,
    query_overview: PromoMatchScreenshot,
    query_side: str,
    *,
    threshold_bits: int = _MATCH_THRESHOLD_BITS,
    excluded_match_ids: Optional[set[int]] = None,
) -> Optional[HashMatch]:
    """Find another overview — preferably one with loadouts — whose name
    crop is the same player as ``query_overview``'s ``query_side`` crop.

    Compares the query against every other overview's left + right
    crops using both plain and trim-normalized hashes (taking the
    min distance). Among the candidates whose distance is within
    ``threshold_bits``, prefers matches with loadouts (so the canonical
    lookup can actually return something useful) over results-only
    matches. Within each tier, sorts by ascending distance.

    ``excluded_match_ids`` lets the caller skip matches it doesn't
    want canonical loadouts from (e.g. its own match).
    """
    if query_side not in ("left", "right"):
        raise ValueError(f"query_side must be 'left' or 'right', got {query_side!r}")
    query_hashes = overview_hashes(query_overview)
    query_pair = query_hashes.get(f"{query_side}_name")
    if query_pair is None:
        return None
    q_plain, q_norm = query_pair

    excluded_match_ids = set(excluded_match_ids or ())
    excluded_match_ids.add(query_overview.match_id)

    overviews = session.exec(
        select(PromoMatchScreenshot).where(
            PromoMatchScreenshot.kind == "results_overview"
        )
    ).all()

    # Pre-fetch has_loadouts per match so we can prefer those.
    match_ids = {ov.match_id for ov in overviews}
    matches = session.exec(
        select(PromoMatch).where(PromoMatch.id.in_(match_ids))
    ).all()
    has_loadouts_by_match: dict[int, bool] = {m.id: m.has_loadouts for m in matches}

    candidates: list[HashMatch] = []
    for ov in overviews:
        if ov.id == query_overview.id:
            continue
        if ov.match_id in excluded_match_ids:
            continue
        ov_hashes = overview_hashes(ov)
        for side in ("left", "right"):
            pair = ov_hashes.get(f"{side}_name")
            if pair is None:
                continue
            o_plain, o_norm = pair
            d_plain = hamming_distance(q_plain, o_plain)
            d_norm = hamming_distance(q_norm, o_norm)
            # Accept on trim-normalized hash within threshold, OR a
            # rare exact pixel match on the plain hash. The plain
            # hash alone is unreliable because flat / empty crops
            # collide easily; the normalized hash trims background
            # away and gives a stable identity signal.
            if d_norm > threshold_bits and d_plain > _PLAIN_EXACT_THRESHOLD:
                continue
            # Use d_norm as the primary distance metric; fall back
            # to d_plain only when both signals agree at distance 0.
            d = d_norm if d_plain > _PLAIN_EXACT_THRESHOLD else d_plain
            candidates.append(HashMatch(
                matched_screenshot_id=ov.id,
                matched_side=side,
                matched_match_id=ov.match_id,
                distance=d,
                used_normalized=True,
            ))
    if not candidates:
        return None

    # Sort: matches with loadouts first, then by ascending distance.
    candidates.sort(key=lambda c: (
        not has_loadouts_by_match.get(c.matched_match_id, False),
        c.distance,
    ))
    return candidates[0]


def loadout_for_matched_overview(
    session: Session,
    matched_match_id: int,
    matched_side: str,
) -> Optional[PromoMatchScreenshot]:
    """Pick the right player_top / player_bottom loadout for a side.

    Uses the existing portrait-backfill mapping: each loadout's
    char.portrait fields were populated by joining its player_name
    OCR against the same-match overview. We can re-determine which
    side the loadout was paired with by matching the loadout's
    player_name OCR against the SAME match's overview names.

    Falls back to image-hashing the loadout's player_name region
    against the overview's matched side crop (recursive use of this
    module).
    """
    from ..data.models import PromoExtractedField

    match = session.get(PromoMatch, matched_match_id)
    if match is None:
        return None

    overview = session.exec(
        select(PromoMatchScreenshot).where(
            PromoMatchScreenshot.match_id == matched_match_id,
            PromoMatchScreenshot.kind == "results_overview",
        )
    ).first()
    overview_names: dict[str, str] = {}
    if overview is not None:
        for f in session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id == overview.id,
                PromoExtractedField.region_slug.in_(["left_name", "right_name"]),
            )
        ).all():
            if f.text:
                overview_names[f.region_slug] = f.text.strip()
    target_overview_name = overview_names.get(f"{matched_side}_name") or ""

    candidate_loadouts = session.exec(
        select(PromoMatchScreenshot).where(
            PromoMatchScreenshot.match_id == matched_match_id,
            PromoMatchScreenshot.kind == "player_loadout",
        )
    ).all()
    if not candidate_loadouts:
        return None

    # Group by side (top/bottom). Earliest round_no per side preferred.
    by_side: dict[str, list[PromoMatchScreenshot]] = {"top": [], "bottom": []}
    for ld in candidate_loadouts:
        if ld.side in by_side:
            by_side[ld.side].append(ld)
    for side in by_side:
        by_side[side].sort(key=lambda l: l.round_no or 0)

    # Tier 1: name-OCR match. Read each side's player_name OCR;
    # whichever matches the target overview name (exact / case-
    # insensitive / fuzzy) wins.
    if target_overview_name:
        from rapidfuzz import fuzz

        for ld_side in ("top", "bottom"):
            for ld in by_side[ld_side]:
                pn_field = session.exec(
                    select(PromoExtractedField).where(
                        PromoExtractedField.screenshot_id == ld.id,
                        PromoExtractedField.region_slug == "player_name",
                    )
                ).first()
                ld_name = (pn_field.text if pn_field else "") or ""
                ld_name = ld_name.strip()
                if not ld_name:
                    continue
                if (
                    ld_name == target_overview_name
                    or ld_name.lower() == target_overview_name.lower()
                    or fuzz.ratio(ld_name.lower(), target_overview_name.lower()) >= 80
                ):
                    return ld

    # Tier 2: deterministic top/bottom default. Across the live data,
    # player_top is consistently associated with overview left, player_bottom
    # with overview right — observed during portrait backfill. Use that as
    # the last-resort mapping when name OCR can't disambiguate.
    fallback_side = "top" if matched_side == "left" else "bottom"
    if by_side[fallback_side]:
        return by_side[fallback_side][0]
    other_side = "bottom" if fallback_side == "top" else "top"
    if by_side[other_side]:
        return by_side[other_side][0]
    return None
