"""Central registry of hand-encoded :class:`CharacterSkillSet` records.

Each library module (``library/<character>.py``) registers itself by
calling :func:`register_character` at import time. This module imports
every library module so the registry is populated at startup.

The registry is lookup-by-name; case-insensitive matching is offered
through :func:`get`.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Optional

from .dsl import CharacterSkillSet, assert_well_formed

log = logging.getLogger(__name__)


_REGISTRY: dict[str, CharacterSkillSet] = {}


def register_character(skills: CharacterSkillSet) -> None:
    """Register a hand-encoded skill set. Validates the DSL on insert.

    Typo / malformed-effect bugs surface at import time rather than at
    simulator runtime, where they'd be much harder to diagnose.
    """
    assert_well_formed(skills)
    name = skills.character_name
    if name in _REGISTRY:
        raise ValueError(f"character {name!r} already registered")
    _REGISTRY[name] = skills


def get(name: str) -> Optional[CharacterSkillSet]:
    """Look up a character by name (case-insensitive exact match)."""
    if name in _REGISTRY:
        return _REGISTRY[name]
    lookup = name.lower()
    for k, v in _REGISTRY.items():
        if k.lower() == lookup:
            return v
    return None


def all_encoded_names() -> list[str]:
    return sorted(_REGISTRY)


def coverage_against(db_names: list[str]) -> dict[str, list[str]]:
    """Compare encoded characters against the DB roster.

    Returns ``{"encoded": [names...], "missing": [unencoded names...]}``
    so callers can show "encoded N of M characters in the DB".
    """
    db_set = set(db_names)
    encoded = [n for n in _REGISTRY if n in db_set]
    missing_in_db = [n for n in _REGISTRY if n not in db_set]
    if missing_in_db:
        log.warning(
            "encoded characters not in DB (typo or unscraped?): %s",
            missing_in_db,
        )
    return {
        "encoded": sorted(encoded),
        "encoded_orphans": sorted(missing_in_db),
        "unencoded_in_db": sorted(set(db_names) - set(_REGISTRY)),
    }


def _autoload_library() -> None:
    """Import every module under ``library/`` so they self-register."""
    from . import library  # noqa: F401  — package import side effect

    for _, mod_name, _ in pkgutil.iter_modules(library.__path__):
        importlib.import_module(f"{library.__name__}.{mod_name}")


_autoload_library()
