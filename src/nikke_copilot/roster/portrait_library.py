"""Load the user-curated `Portrait_library/` folder into the matcher.

The directory contains 335 webp portraits named ``<Character> - <Skin>.webp``.
The character part before " - " is a *display* name that may not match the
canonical Prydwen DB name exactly — we resolve it via:

  1. Exact match against `Character.name`.
  2. Inserting ":" after the first word ("Ade Agent Bunny" → "Ade: Agent Bunny").
  3. A small hand-curated alias table for known mismatches.
  4. Fuzzy fallback (``difflib`` cutoff 0.85).

Each character may have multiple skins. All of a character's portraits are
indexed under that character's canonical DB name so the matcher can find a
match regardless of which skin appears in the screenshot.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sqlmodel import Session, select

from ..data.models import Character

log = logging.getLogger(__name__)


# Hand-curated aliases for the 13 portrait→DB name mismatches identified during
# the initial inventory pass. Keys are the *portrait* character names (the part
# before " - " in the filename); values are the canonical Prydwen DB names.
NAME_ALIASES: dict[str, str] = {
    "Ada": "Ada Wong",
    "Asuka": "Asuka Shikinami Langley",
    "Asuka WILLE": "Asuka Shikinami Langley: Wille",
    "Chisato": "Chisato Nishikigi",
    "Claire": "Claire Redfield",
    "EH": "E.H.",
    "EVE": "Eve",
    "Elegg Boom and Shock": "Elegg: Boom and Shock",
    "Jill": "Jill Valentine",
    "Little Mermaid": "Little Mermaid (Siren)",
    "Misato": "Misato Katsuragi",
    "Sakura Bloom in Summer": "Sakura: Bloom in Summer",
    # Takina is from Lycoris Recoil; Prydwen lists her as "Takina Inoue"
    "Takina": "Takina Inoue",
}


@dataclass(frozen=True)
class PortraitEntry:
    """One labeled portrait file resolved against the DB."""

    file_path: Path
    portrait_name: str  # raw character name from filename
    skin_name: str  # raw skin name from filename
    character_name: Optional[str]  # canonical DB name, None when unresolved
    resolution: str  # 'exact', 'colon-insert', 'alias', 'fuzzy', 'unresolved'


_FILENAME_RE = re.compile(r"^(?P<char>.+?)\s+-\s+(?P<skin>.+)\.(webp|png|jpg|jpeg)$", re.I)


def _parse_filename(path: Path) -> Optional[tuple[str, str]]:
    m = _FILENAME_RE.match(path.name)
    if not m:
        return None
    return m.group("char").strip(), m.group("skin").strip()


def _try_colon_insert(name: str, candidates: set[str]) -> Optional[str]:
    """If "First Rest" doesn't match, try "First: Rest"."""
    parts = name.split(" ", 1)
    if len(parts) != 2:
        return None
    candidate = f"{parts[0]}: {parts[1]}"
    if candidate in candidates:
        return candidate
    return None


def resolve_character_name(
    portrait_name: str, db_names: set[str], *, fuzzy_cutoff: float = 0.85
) -> tuple[Optional[str], str]:
    """Resolve a portrait-folder character name to a DB name. Returns
    ``(db_name, resolution_kind)`` where kind is one of
    ``exact|colon-insert|alias|fuzzy|unresolved``.
    """
    if portrait_name in db_names:
        return portrait_name, "exact"
    if portrait_name in NAME_ALIASES:
        canonical = NAME_ALIASES[portrait_name]
        if canonical in db_names:
            return canonical, "alias"
        log.warning("alias %r → %r is not in the DB", portrait_name, canonical)
    colon = _try_colon_insert(portrait_name, db_names)
    if colon is not None:
        return colon, "colon-insert"
    matches = difflib.get_close_matches(
        portrait_name, db_names, n=1, cutoff=fuzzy_cutoff
    )
    if matches:
        return matches[0], "fuzzy"
    return None, "unresolved"


def discover_portraits(library_dir: Path) -> list[Path]:
    """Return every portrait file under ``library_dir`` (sorted)."""
    if not library_dir.exists():
        return []
    paths: list[Path] = []
    for ext in ("webp", "png", "jpg", "jpeg"):
        paths.extend(library_dir.glob(f"*.{ext}"))
        paths.extend(library_dir.glob(f"*.{ext.upper()}"))
    return sorted(set(paths))


# Feedback subdirectory layout — created by the matcher feedback loop.
# Files live at ``<library_dir>/feedback/<Character>/<timestamp>_<id>.webp``.
# Character name is taken from the *parent directory*, not the filename, so
# crops can be saved under arbitrary timestamped names without parsing.
_FEEDBACK_SUBDIR = "feedback"


def discover_feedback_exemplars(library_dir: Path) -> list[tuple[Path, str]]:
    """Return ``[(file_path, character_name), ...]`` from ``feedback/<C>/``.

    The character name comes from the immediate parent directory. Files
    without a parent directory under ``feedback/`` are ignored. This keeps
    the layout self-documenting and resistant to filename mistakes — the
    DB-canonical character name lives in the directory structure.
    """
    fb_root = library_dir / _FEEDBACK_SUBDIR
    if not fb_root.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for char_dir in sorted(fb_root.iterdir()):
        if not char_dir.is_dir():
            continue
        char_name = char_dir.name
        for ext in ("webp", "png", "jpg", "jpeg"):
            for p in sorted(char_dir.glob(f"*.{ext}")):
                out.append((p, char_name))
            for p in sorted(char_dir.glob(f"*.{ext.upper()}")):
                out.append((p, char_name))
    return out


def resolve_library(
    library_dir: Path, db_names: Iterable[str]
) -> list[PortraitEntry]:
    """Walk ``library_dir`` and resolve every portrait against ``db_names``.

    Includes feedback-loop exemplars under ``feedback/<Character>/`` —
    these are crops saved by the matcher feedback loop when a user
    overrides a borderline cell, and they're indexed under the parent
    directory's character name (skipping the filename parse).
    """
    db_set = set(db_names)
    out: list[PortraitEntry] = []
    for p in discover_portraits(library_dir):
        parsed = _parse_filename(p)
        if parsed is None:
            log.warning("could not parse portrait filename: %s", p.name)
            out.append(
                PortraitEntry(
                    file_path=p,
                    portrait_name=p.stem,
                    skin_name="",
                    character_name=None,
                    resolution="unresolved",
                )
            )
            continue
        portrait_name, skin_name = parsed
        canonical, kind = resolve_character_name(portrait_name, db_set)
        out.append(
            PortraitEntry(
                file_path=p,
                portrait_name=portrait_name,
                skin_name=skin_name,
                character_name=canonical,
                resolution=kind,
            )
        )
    # Feedback exemplars — directory-name-as-canonical layout. Skip the
    # filename parse, but still validate against db_names so a typo'd
    # directory doesn't pollute the index silently.
    for p, char_name in discover_feedback_exemplars(library_dir):
        if char_name in db_set:
            resolution = "feedback"
        else:
            log.warning(
                "feedback exemplar character %r is not in DB: %s", char_name, p
            )
            resolution = "feedback-unresolved"
        out.append(
            PortraitEntry(
                file_path=p,
                portrait_name=char_name,
                skin_name="feedback",
                character_name=char_name if char_name in db_set else None,
                resolution=resolution,
            )
        )
    return out


def resolve_library_from_session(
    library_dir: Path, session: Session
) -> list[PortraitEntry]:
    db_names = [c.name for c in session.exec(select(Character)).all()]
    return resolve_library(library_dir, db_names)


def summarize(entries: list[PortraitEntry]) -> dict[str, int]:
    """Quick counters useful for `/inventory` output."""
    summary: dict[str, int] = {
        "total": len(entries),
        "exact": 0,
        "colon-insert": 0,
        "alias": 0,
        "fuzzy": 0,
        "unresolved": 0,
        "feedback": 0,
        "feedback-unresolved": 0,
        "unique_characters": 0,
    }
    chars_seen: set[str] = set()
    for e in entries:
        summary[e.resolution] = summary.get(e.resolution, 0) + 1
        if e.character_name:
            chars_seen.add(e.character_name)
    summary["unique_characters"] = len(chars_seen)
    return summary
