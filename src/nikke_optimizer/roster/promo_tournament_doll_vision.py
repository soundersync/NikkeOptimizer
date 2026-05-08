"""Apple Vision feature-print classifier for doll/treasure icons.

The HSV-distance classifier in ``promo_tournament_doll_match`` works
off five hand-labeled exemplar images (one per non-empty class).
After the user audited every captured doll into a fully-corrected
1800-row corpus, we have a much richer set of references — a Vision
feature-print embedding per row plus the user's class label.

This module mirrors the structure of ``portrait_matcher.PortraitMatcher``:
build a feature-print index from the labeled corpus, then classify
new crops via majority-vote nearest-neighbour. The k-NN approach
captures intra-class variation (e.g. Treasure φ3 in odd lighting,
SR★15 with the dim sub-render) that a single mean-color exemplar
can't.

Heavy macOS-only deps (pyobjc-framework-Vision) are imported lazily
through ``FeaturePrintEmbedder`` so this module can still be imported
in headless tests via a stub embedder.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol

from PIL import Image
from sqlmodel import Session, select

from ..data.models import PromoExtractedField, PromoMatchScreenshot

log = logging.getLogger(__name__)


# Doll/treasure crops are 33×37 px; Vision feature-prints are more
# stable on slightly larger inputs. Resize both corpus + query to
# this size with the same algorithm so distances are comparable.
_VISION_INPUT_SIZE = (96, 96)

# Distance ceiling for "is this a credible match at all". Values
# above this trigger an `unknown` fallback even if it's still the
# nearest neighbour. Calibrated empirically against typical Vision
# distances (5–20 for similar dolls, 25+ for unrelated crops).
_NO_MATCH_THRESHOLD = 25.0


class _Embedder(Protocol):
    """Subset of ``FeaturePrintEmbedder`` surface this matcher uses.

    A test-only stub can satisfy this protocol without importing pyobjc.
    """

    def embed_pil(self, image: Image.Image) -> object: ...

    @staticmethod
    def compute_distance(a: object, b: object) -> float: ...


@dataclass
class _IndexEntry:
    """One labeled corpus exemplar."""

    embedding: object  # VNFeaturePrintObservation in production
    field_id: int
    normalized: str  # canonical class key
    screenshot_id: int
    region_slug: str  # "char3.doll"


@dataclass(frozen=True)
class DollClassification:
    """Vision-classifier output (mirrors HSV ``DollClassification``)."""

    canonical_key: str
    display_label: str
    distance: float       # mean distance to the K nearest winning-class neighbours
    confidence: float     # 1 - distance/THRESHOLD, clamped to [0, 1]
    n_voting: int         # how many of the K-NN voted for the winner


def _resize_for_vision(crop: Image.Image) -> Image.Image:
    if crop.mode != "RGB":
        crop = crop.convert("RGB")
    return crop.resize(_VISION_INPUT_SIZE, Image.LANCZOS)


def _bbox_lookup() -> dict[str, tuple[int, int, int, int]]:
    """``slug -> bbox`` for every doll region in the player_loadout schema."""
    from .promo_tournament_regions import PLAYER_LOADOUT

    return {
        r.slug: r.bbox for r in PLAYER_LOADOUT if r.slug.endswith(".doll")
    }


class DollVisionMatcher:
    """Vision-feature-print nearest-neighbour matcher over a labeled corpus.

    Construction is a one-shot scan of the DB; the embedder
    (``FeaturePrintEmbedder``) is reused across the build + every
    subsequent ``match`` call. The matcher is intentionally stateless
    after construction — refreshing the corpus means rebuilding via
    ``from_session``.
    """

    def __init__(self, *, embedder: Optional[_Embedder] = None) -> None:
        if embedder is None:
            from ._vision_features import FeaturePrintEmbedder
            embedder = FeaturePrintEmbedder()
        self.embedder: _Embedder = embedder
        self._index: list[_IndexEntry] = []

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_session(
        cls,
        session: Session,
        *,
        embedder: Optional[_Embedder] = None,
        manually_corrected_only: bool = True,
    ) -> "DollVisionMatcher":
        """Build the corpus from every doll ``PromoExtractedField`` row.

        With ``manually_corrected_only=True`` (the default) only
        user-confirmed rows feed the index — that's the gold-standard
        corpus. Pass ``False`` to seed an index from the entire table
        (useful for cold-start when nothing's been audited yet).
        """
        m = cls(embedder=embedder)
        bbox_by_slug = _bbox_lookup()

        query = select(PromoExtractedField).where(
            PromoExtractedField.region_slug.like("%.doll")
        )
        if manually_corrected_only:
            query = query.where(
                PromoExtractedField.manually_corrected == True  # noqa: E712
            )

        rows = session.exec(query).all()
        if not rows:
            log.info(
                "DollVisionMatcher: corpus is empty (manually_corrected=%s)",
                manually_corrected_only,
            )
            return m

        # Batch-load source screenshots so we don't hit the DB per row.
        shot_ids = list({r.screenshot_id for r in rows})
        shots = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.id.in_(shot_ids)
            )
        ).all()
        shot_by_id = {s.id: s for s in shots}

        # Open each source PNG once even when several rows reference it.
        images: dict[int, Image.Image] = {}
        skipped = 0
        for row in rows:
            if not row.normalized:
                skipped += 1
                continue
            shot = shot_by_id.get(row.screenshot_id)
            if shot is None:
                skipped += 1
                continue
            bbox = bbox_by_slug.get(row.region_slug)
            if bbox is None:
                skipped += 1
                continue
            img = images.get(shot.id)
            if img is None:
                try:
                    img = Image.open(shot.file_path).convert("RGB")
                except OSError as exc:
                    log.warning("doll-vision open failed for %s: %s", shot.file_path, exc)
                    skipped += 1
                    continue
                images[shot.id] = img
            crop = img.crop(bbox)
            try:
                emb = m.embedder.embed_pil(_resize_for_vision(crop))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "doll-vision embed failed for field %d: %s", row.id, exc
                )
                skipped += 1
                continue
            m._index.append(_IndexEntry(
                embedding=emb,
                field_id=row.id,
                normalized=row.normalized,
                screenshot_id=row.screenshot_id,
                region_slug=row.region_slug,
            ))
        log.info(
            "DollVisionMatcher: indexed %d corpus entries (skipped %d)",
            len(m._index), skipped,
        )
        return m

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def match(
        self,
        crop: Image.Image,
        *,
        k: int = 5,
        exclude_field_id: Optional[int] = None,
    ) -> Optional[DollClassification]:
        """Classify a query crop via K-NN majority vote.

        ``exclude_field_id`` lets the diagnostic command exclude a
        row from its own self-match when reclassifying corpus
        members against the corpus (otherwise a row always votes
        for itself).
        """
        if not self._index:
            return None
        try:
            query = self.embedder.embed_pil(_resize_for_vision(crop))
        except Exception as exc:  # noqa: BLE001
            log.warning("doll-vision query embed failed: %s", exc)
            return None

        from .promo_tournament_doll_match import DISPLAY_LABELS

        scored: list[tuple[float, _IndexEntry]] = []
        for e in self._index:
            if exclude_field_id is not None and e.field_id == exclude_field_id:
                continue
            d = self.embedder.compute_distance(query, e.embedding)
            scored.append((d, e))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0])
        nearest = scored[: max(1, k)]

        # Majority vote on `normalized`. Ties broken by lowest mean
        # distance per candidate class.
        votes: Counter = Counter()
        per_class_distances: dict[str, list[float]] = {}
        for d, e in nearest:
            votes[e.normalized] += 1
            per_class_distances.setdefault(e.normalized, []).append(d)
        # Pick winner: highest vote count, then lowest mean distance.
        best_class, best_count = max(
            votes.items(),
            key=lambda kv: (
                kv[1],
                -sum(per_class_distances[kv[0]]) / len(per_class_distances[kv[0]]),
            ),
        )
        winning_distances = per_class_distances[best_class]
        mean_d = sum(winning_distances) / len(winning_distances)

        # Calibrate confidence to the no-match threshold.
        if mean_d > _NO_MATCH_THRESHOLD:
            return DollClassification(
                canonical_key="unknown",
                display_label=DISPLAY_LABELS.get("unknown", "—"),
                distance=mean_d,
                confidence=0.0,
                n_voting=0,
            )

        return DollClassification(
            canonical_key=best_class,
            display_label=DISPLAY_LABELS.get(best_class, best_class),
            distance=mean_d,
            confidence=max(
                0.0, min(1.0, 1.0 - mean_d / _NO_MATCH_THRESHOLD)
            ),
            n_voting=best_count,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._index)

    def coverage(self) -> dict[str, int]:
        """Per-class corpus size."""
        out: dict[str, int] = {}
        for e in self._index:
            out[e.normalized] = out.get(e.normalized, 0) + 1
        return out

    def index(self) -> Iterable[_IndexEntry]:
        """Read-only iterator over the index — for diagnostic commands
        that need to walk every entry."""
        return iter(self._index)
