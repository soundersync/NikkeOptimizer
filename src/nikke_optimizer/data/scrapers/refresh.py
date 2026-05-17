"""Refresh job — pulls fresh character data from Prydwen and upserts into SQLite.

Idempotent: matches on Character.name. Designed to be invoked from the CLI
(`nikkeoptimizer refresh`) or scheduled via cron / launchd.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from platformdirs import user_cache_dir
from sqlmodel import Session, select

from ..db import get_session, init_db, make_engine
from ..models import Character
from .prydwen import PrydwenClient, NormalizedCharacter

log = logging.getLogger(__name__)

_CACHE_APP = "NikkeOptimizer"


def default_cache_dir() -> Path:
    return Path(user_cache_dir(_CACHE_APP, appauthor=False)) / "prydwen"


def upsert_character(session: Session, normalized: NormalizedCharacter) -> Character:
    existing = session.exec(
        select(Character).where(Character.name == normalized.name)
    ).one_or_none()
    fields = normalized.to_kwargs()
    fields["source"] = "prydwen"
    fields.pop("slug", None)  # slug is not on the Character table
    if existing is None:
        char = Character(**fields)
        session.add(char)
        return char
    for k, v in fields.items():
        setattr(existing, k, v)
    return existing


def _name_to_slug_candidate(name: str) -> str:
    """Heuristic: convert a display name to Prydwen's slug form."""
    import re
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def _resolve_names_to_slugs(
    names: list[str], all_slugs: list[str]
) -> tuple[list[str], list[str]]:
    """Map display names to known Prydwen slugs.

    Strategy per name: exact (case-insensitive) → prefix → substring,
    each requiring a unique match before falling through to the next.
    Returns ``(matched_slugs, unmatched_names)``.
    """
    slug_lower = {s.lower(): s for s in all_slugs}
    matched: list[str] = []
    unmatched: list[str] = []
    for name in names:
        candidate = _name_to_slug_candidate(name)
        if not candidate:
            unmatched.append(name)
            continue
        if candidate in slug_lower:
            matched.append(slug_lower[candidate])
            continue
        prefix_hits = [s for k, s in slug_lower.items() if k.startswith(candidate + "-")]
        if len(prefix_hits) == 1:
            matched.append(prefix_hits[0])
            continue
        sub_hits = [s for k, s in slug_lower.items() if candidate in k]
        if len(sub_hits) == 1:
            matched.append(sub_hits[0])
            continue
        unmatched.append(name)
    return matched, unmatched


async def refresh_async(
    db_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    *,
    use_cache: bool = True,
    names: Optional[list[str]] = None,
) -> dict[str, int]:
    """Fetch characters from Prydwen and upsert into the local DB.

    When ``names`` is ``None`` (default), refreshes every character in the
    Prydwen index. When ``names`` is a list, only those are fetched —
    each name is resolved to a Prydwen slug via case-insensitive exact /
    prefix / substring matching against the slug list.

    Returns counts: ``{"fetched", "inserted", "updated", "skipped",
    "unmatched"}`` (last is the count of input names with no slug match).
    """
    cache = cache_dir if (cache_dir is not None or not use_cache) else default_cache_dir()
    engine = make_engine(db_path)
    init_db(engine)

    counts = {"fetched": 0, "inserted": 0, "updated": 0, "skipped": 0, "unmatched": 0}
    async with PrydwenClient(cache_dir=cache if use_cache else None) as client:
        if names:
            all_slugs = await client.list_character_slugs()
            slugs, unmatched = _resolve_names_to_slugs(names, all_slugs)
            counts["unmatched"] = len(unmatched)
            for n in unmatched:
                log.warning("no Prydwen slug matched name=%r — skipping", n)
            if not slugs:
                return counts
            normalized_list = await client.fetch_all(slugs=slugs)
        else:
            normalized_list = await client.fetch_all()
    counts["fetched"] = len(normalized_list)

    with get_session(engine) as session:
        for n in normalized_list:
            existing = session.exec(
                select(Character).where(Character.name == n.name)
            ).one_or_none()
            try:
                upsert_character(session, n)
            except Exception as exc:  # noqa: BLE001
                log.warning("skipping %s: %s", n.name, exc)
                counts["skipped"] += 1
                continue
            if existing is None:
                counts["inserted"] += 1
            else:
                counts["updated"] += 1
        session.commit()
    return counts


def refresh(**kw) -> dict[str, int]:
    return asyncio.run(refresh_async(**kw))
