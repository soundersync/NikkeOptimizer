"""Auto-classify a screenshot's type and dispatch to the right importer.

Used by ``nikkecopilot ingest <dir>`` to walk a directory tree and route each
file to the appropriate handler:

  * CSVs → roster CSV importer
  * Cube detail screenshots → cube importer
  * Arena pre-battle / Champion 'Arena Info' → arena importer
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

from .arena import detect_title
from .ocr import recognize

log = logging.getLogger(__name__)


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


# Returned by `classify_screenshot()`. Codes mirror the dispatch table in
# `ingest_directory()`. "unknown" means no importer applies.
SCREENSHOT_CLASSES = {
    "rookie",
    "special",
    "champion",  # Champion 'Arena Info' loadout popup
    "champion_battle_record",  # Per-round Battle Records screen
    "champion_duel_result",  # Overall Champions Duel Result screen
    "cube",
    "csv",
    "unknown",
}

# Map an upload form's mode_hint to the classes the router should accept
# without re-detecting. Useful when OCR title detection is unreliable
# (random filenames, season UI tweaks, low-res screenshots).
_MODE_HINT_FAMILIES = {
    "rookie": {"rookie"},
    "sp": {"special"},
    "special": {"special"},
    "champions": {
        "champion",
        "champion_battle_record",
        "champion_duel_result",
    },
}


def classify_screenshot(path: Path, *, mode_hint: Optional[str] = None) -> str:
    """Heuristic classifier — returns one of ``SCREENSHOT_CLASSES``.

    Strategy:
      1. CSVs by extension.
      2. Try the arena title detector (top 25% of the image).
      3. Fall back to bottom-of-image OCR for cube detail signatures
         ("Cube Ability" / "Cube Skill" / "Cube Equipping Status").
      4. If ``mode_hint`` was provided and the auto-detect returned a
         class outside that family, prefer the hint family's most
         specific Champion subtype that matches a header keyword. When
         no specific subtype matches, the file falls back to the hint's
         primary mode (e.g. ``"champion"``) so it still routes somewhere.

    ``mode_hint`` values: ``"rookie"`` | ``"sp"`` | ``"special"`` |
    ``"champions"`` | ``None`` (auto).
    """
    if path.suffix.lower() == ".csv":
        return "csv"
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        return "unknown"
    try:
        image = Image.open(path).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to open %s: %s", path, exc)
        return "unknown"

    # Fast-path: portrait library files are 256x512; in-game screenshots are
    # at least 1500 px wide. Skip the OCR call for anything tiny.
    if max(image.size) < 1000:
        return "unknown"

    mode, _ = detect_title(image)
    if mode in (
        "rookie",
        "special",
        "champion",
        "champion_battle_record",
        "champion_duel_result",
    ):
        # Honor mode_hint when the auto-detect picked something from a
        # different family. Champions Battle Records and Duel Result still
        # auto-detect just fine; the hint mostly matters when title OCR
        # misses entirely (handled below via the fallback branch).
        if mode_hint:
            family = _MODE_HINT_FAMILIES.get(mode_hint.lower())
            if family and mode not in family:
                # Hint says it's Champions but title OCR said Rookie?
                # Trust the title — false positives there are rarer than
                # users mis-clicking the radio. Log for visibility.
                log.warning(
                    "%s: mode_hint=%r but title detected %r — keeping detected",
                    path.name, mode_hint, mode,
                )
        return mode

    # Auto-detect missed; fall back to mode_hint if provided. For Champions
    # specifically we cannot disambiguate loadout vs battle-record vs duel-
    # result without a successful header read, so we route the file to the
    # most permissive class (champion = loadout) and let the importer's
    # extractor return None on a mismatch.
    if mode_hint:
        family = _MODE_HINT_FAMILIES.get(mode_hint.lower())
        if family:
            primary = (
                "rookie" if "rookie" in family
                else "special" if "special" in family
                else "champion"
            )
            log.info(
                "%s: title-detect failed, routing to %s via mode_hint",
                path.name, primary,
            )
            return primary

    # Cube fallback — Vision finds nothing in the top of cube screenshots
    # because the cube art fills the upper half. Check the lower half for
    # the cube info dialog text.
    w, h = image.size
    bottom = image.crop((0, int(h * 0.45), w, h))
    text = " ".join(r.text for r in recognize(bottom)).lower()
    if any(s in text for s in ("cube ability", "cube skill", "cube equipping")):
        return "cube"
    return "unknown"


@dataclass
class IngestReport:
    files_seen: int = 0
    csv: int = 0
    rookie: int = 0
    special: int = 0
    champion: int = 0
    cube: int = 0
    unknown: int = 0
    warnings: list[str] = field(default_factory=list)
    classifications: dict[str, str] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        log.warning(msg)
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return {
            "files_seen": self.files_seen,
            "csv": self.csv,
            "rookie": self.rookie,
            "special": self.special,
            "champion": self.champion,
            "cube": self.cube,
            "unknown": self.unknown,
            "warnings": self.warnings,
        }


def _walk_inputs(root: Path) -> list[Path]:
    """Recursively collect every csv / image file under ``root``."""
    out: list[Path] = []
    if root.is_file():
        return [root]
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() == ".csv" or p.suffix.lower() in _IMAGE_SUFFIXES:
            out.append(p)
    return out


def ingest_directory(
    root: Path,
    *,
    library_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    user_username: str = "NIKA",
    classify_only: bool = False,
) -> IngestReport:
    """Walk ``root`` and route every file to the matching importer.

    When ``classify_only`` is True, returns the per-file classification
    without persisting anything — useful as a dry run before commit.

    The arena pipeline needs a portrait library to build the matcher; if no
    arena screenshots are present the library can be omitted.
    """
    report = IngestReport()
    paths = _walk_inputs(root)
    report.files_seen = len(paths)

    # Bucket paths by class.
    buckets: dict[str, list[Path]] = {k: [] for k in SCREENSHOT_CLASSES}
    for p in paths:
        cls = classify_screenshot(p)
        buckets[cls].append(p)
        report.classifications[str(p)] = cls
        if cls == "unknown":
            report.unknown += 1
            report.warn(f"unclassified: {p}")

    if classify_only:
        report.csv = len(buckets["csv"])
        report.rookie = len(buckets["rookie"])
        report.special = len(buckets["special"])
        report.champion = len(buckets["champion"])
        report.cube = len(buckets["cube"])
        return report

    # CSV import — there's typically one full-roster CSV; if multiple are
    # present the importer's delete-and-replace semantics mean the last one
    # wins, so we run them in path order.
    if buckets["csv"]:
        from .csv_importer import import_csv

        for p in buckets["csv"]:
            try:
                import_csv(p, db_path=db_path)
                report.csv += 1
            except Exception as exc:  # noqa: BLE001
                report.warn(f"{p}: csv import crashed: {exc}")

    # Cube import — the importer takes a directory, but here we have a flat
    # list of paths; pass each parent dir we encounter at most once.
    if buckets["cube"]:
        from .cube_importer import import_cubes

        cube_dirs = {p.parent for p in buckets["cube"]}
        for d in sorted(cube_dirs):
            try:
                r = import_cubes(d, db_path=db_path)
                report.cube += r.upserted
                if r.warnings:
                    report.warnings.extend(r.warnings)
            except Exception as exc:  # noqa: BLE001
                report.warn(f"{d}: cube import crashed: {exc}")

    # Arena import (rookie + special + champion) all share one matcher.
    arena_paths = buckets["rookie"] + buckets["special"] + buckets["champion"]
    if arena_paths:
        if library_dir is None:
            report.warn(
                f"{len(arena_paths)} arena screenshots found but --library "
                "was not provided — skipping arena import"
            )
        else:
            from .arena_importer import import_arena_screenshots
            from .portrait_matcher import PortraitMatcher
            from ..data.db import get_session, init_db, make_engine

            engine = make_engine(db_path)
            init_db(engine)
            with get_session(engine) as session:
                matcher = PortraitMatcher.from_portrait_library(
                    library_dir, session=session
                )
            r = import_arena_screenshots(
                arena_paths,
                matcher,
                db_path=db_path,
                user_username=user_username,
            )
            report.rookie += r.rookie
            report.special += r.special
            report.champion += r.champion
            if r.warnings:
                report.warnings.extend(r.warnings)

    return report
