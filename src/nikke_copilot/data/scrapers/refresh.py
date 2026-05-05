"""Refresh job — pulls fresh character data from Prydwen and upserts into SQLite.

Idempotent: matches on Character.name. Designed to be invoked from the CLI
(`nikkecopilot refresh`) or scheduled via cron / launchd.
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

_CACHE_APP = "NikkeCopilot"


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


async def refresh_async(
    db_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    *,
    use_cache: bool = True,
) -> dict[str, int]:
    """Fetch all characters from Prydwen and upsert into the local DB.

    Returns counts: {"fetched": N, "inserted": I, "updated": U, "skipped": S}.
    """
    cache = cache_dir if (cache_dir is not None or not use_cache) else default_cache_dir()
    engine = make_engine(db_path)
    init_db(engine)

    counts = {"fetched": 0, "inserted": 0, "updated": 0, "skipped": 0}
    async with PrydwenClient(cache_dir=cache if use_cache else None) as client:
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
