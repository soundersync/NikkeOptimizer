"""Match a cropped portrait against the local portrait library.

Two indexing strategies are supported:

  * **labeled library** (preferred): the user-curated `Portrait_library/` folder
    with one or more skins per character (`<Character> - <Skin>.webp`). Each
    skin is embedded independently and a query matches against the **best**
    skin for that character — robust to which skin actually appears in-game.
  * **prydwen single-portrait** (fallback): the auto-downloaded character
    portraits indexed in `CharacterIcon` rows. One embedding per character.

Embeddings come from Apple's `VNGenerateImageFeaturePrintRequest` (a learned
visual descriptor). Distance is the squared L2 between embeddings — small
values mean similar images.

Perceptual-hash matching was tried first and rejected: phash distances clustered
too tightly (50–60 across many characters) on stylized in-game card crops, and
rank-1 results were unreliable. Feature embeddings discriminate far better.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image
from sqlmodel import Session, select

from ..data.models import Character, CharacterIcon
from . import portrait_library
from ._vision_features import FeaturePrintEmbedder

log = logging.getLogger(__name__)


@dataclass
class PortraitMatch:
    """One candidate match returned by ``PortraitMatcher.match``."""

    character_name: str
    distance: float
    image_path: Path
    skin_name: Optional[str] = None

    @property
    def confidence(self) -> float:
        """Heuristic confidence in [0, 1].

        Calibrated against typical Vision feature-print distances:
            <  8.0  → very strong (≥ 0.85)
            ~12.0   → moderate    (~ 0.55)
            > 18.0  → weak        (< 0.30)
        """
        return max(0.0, min(1.0, 1.0 - (self.distance / 22.0)))


@dataclass
class _IndexEntry:
    """Internal record: one embedded reference image."""

    embedding: object  # VNFeaturePrintObservation
    character_name: str
    image_path: Path
    skin_name: Optional[str]


class PortraitMatcher:
    """Vision-feature-print nearest-neighbor matcher over a portrait library."""

    def __init__(self, *, embedder: Optional[FeaturePrintEmbedder] = None) -> None:
        self.embedder = embedder or FeaturePrintEmbedder()
        self._index: list[_IndexEntry] = []

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_portrait_library(
        cls,
        library_dir: Path,
        *,
        session: Optional[Session] = None,
        db_names: Optional[Sequence[str]] = None,
        warn_unresolved: bool = True,
    ) -> "PortraitMatcher":
        """Index every portrait in ``library_dir``.

        Either a SQLModel ``session`` or an explicit ``db_names`` iterable
        must be provided so unresolved filenames can be flagged.
        """
        if session is None and db_names is None:
            raise ValueError("must provide either session or db_names")
        if db_names is None:
            entries = portrait_library.resolve_library_from_session(
                library_dir, session  # type: ignore[arg-type]
            )
        else:
            entries = portrait_library.resolve_library(library_dir, db_names)

        m = cls()
        skipped = 0
        for entry in entries:
            if entry.character_name is None:
                if warn_unresolved:
                    log.warning(
                        "skipping unresolved portrait: %s", entry.file_path.name
                    )
                skipped += 1
                continue
            try:
                emb = m.embedder.embed_path(entry.file_path)
            except Exception as exc:  # noqa: BLE001
                log.warning("embed failed for %s: %s", entry.file_path, exc)
                skipped += 1
                continue
            m._index.append(
                _IndexEntry(
                    embedding=emb,
                    character_name=entry.character_name,
                    image_path=entry.file_path,
                    skin_name=entry.skin_name,
                )
            )
        log.info(
            "loaded %d embeddings into matcher (skipped %d)",
            len(m._index),
            skipped,
        )
        return m

    @classmethod
    def from_session(
        cls, session: Session, *, source: str = "prydwen_portrait"
    ) -> "PortraitMatcher":
        """Index `CharacterIcon` rows from the DB (one image per character)."""
        m = cls()
        rows = session.exec(
            select(CharacterIcon, Character)
            .where(CharacterIcon.source == source)
            .where(CharacterIcon.character_id == Character.id)
        ).all()
        for icon, char in rows:
            path = Path(icon.image_path)
            if not path.exists():
                log.warning("missing portrait file for %s: %s", char.name, path)
                continue
            try:
                emb = m.embedder.embed_path(path)
            except Exception as exc:  # noqa: BLE001
                log.warning("embed failed for %s: %s", char.name, exc)
                continue
            m._index.append(
                _IndexEntry(
                    embedding=emb,
                    character_name=char.name,
                    image_path=path,
                    skin_name=None,
                )
            )
        log.info("loaded %d portraits into matcher", len(m._index))
        return m

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def match(
        self, image: Image.Image, *, top_k: int = 1, group_by_character: bool = True
    ) -> list[PortraitMatch]:
        """Return up to ``top_k`` matches sorted by ascending distance.

        When ``group_by_character`` is True (default), only the best-scoring
        skin for each character is returned in the top-K — important when one
        character has many skins, otherwise the whole top-K is dominated by
        Anis or Rapi variants.
        """
        if not self._index:
            return []
        try:
            query = self.embedder.embed_pil(image)
        except Exception as exc:
            log.warning("query embed failed: %s", exc)
            return []
        scored = [
            (FeaturePrintEmbedder.compute_distance(query, e.embedding), e)
            for e in self._index
        ]
        scored.sort(key=lambda x: x[0])
        if group_by_character:
            seen: set[str] = set()
            grouped: list[tuple[float, _IndexEntry]] = []
            for dist, entry in scored:
                if entry.character_name in seen:
                    continue
                seen.add(entry.character_name)
                grouped.append((dist, entry))
                if len(grouped) >= top_k:
                    break
            scored = grouped
        else:
            scored = scored[:top_k]
        return [
            PortraitMatch(
                character_name=e.character_name,
                distance=d,
                image_path=e.image_path,
                skin_name=e.skin_name,
            )
            for d, e in scored
        ]

    def match_best(self, image: Image.Image) -> Optional[PortraitMatch]:
        m = self.match(image, top_k=1)
        return m[0] if m else None

    # ------------------------------------------------------------------
    # Feedback loop — register a corrected crop as a labeled exemplar.
    # ------------------------------------------------------------------

    def add_exemplar(
        self,
        character_name: str,
        image: Image.Image,
        *,
        source_path: Optional[Path] = None,
        skin_name: Optional[str] = None,
    ) -> bool:
        """Embed ``image`` as an additional exemplar for ``character_name``.

        Used by the override-cell route (web UI) to feed a confirmed
        in-game crop into the running matcher index immediately, so the
        very next capture in the same session benefits from the new
        exemplar without restarting the app.

        Returns True when the embedding succeeded, False when the
        Vision pipeline rejected the crop (too small, unreadable, etc.).
        Mutates ``self._index`` in place.
        """
        try:
            emb = self.embedder.embed_pil(image)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "feedback exemplar embed failed for %s: %s", character_name, exc
            )
            return False
        self._index.append(
            _IndexEntry(
                embedding=emb,
                character_name=character_name,
                image_path=source_path or Path(f"<feedback:{character_name}>"),
                skin_name=skin_name or "feedback",
            )
        )
        log.info(
            "added feedback exemplar for %s (index size now %d)",
            character_name,
            len(self._index),
        )
        return True

    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._index)

    def coverage(self) -> dict[str, int]:
        """Return {character_name: skin_count} for the indexed library."""
        out: dict[str, int] = {}
        for e in self._index:
            out[e.character_name] = out.get(e.character_name, 0) + 1
        return out
