"""Download Prydwen portraits for every Character into the local cache.

Used by the arena extractor to identify character portraits in team-loadout
screenshots via perceptual hashing. Each portrait is small (~80-200px) so the
full set of 206 fits in a few MB.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import httpx
from platformdirs import user_cache_dir
from sqlmodel import Session, select

from ..db import get_session, init_db, make_engine
from ..models import Character, CharacterIcon

log = logging.getLogger(__name__)

_CACHE_APP = "NikkeOptimizer"


def default_portrait_dir() -> Path:
    return Path(user_cache_dir(_CACHE_APP, appauthor=False)) / "portraits"


async def _download_one(
    client: httpx.AsyncClient,
    char: Character,
    out_dir: Path,
    sem: asyncio.Semaphore,
) -> Optional[Path]:
    if not char.portrait_url:
        return None
    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in char.name
    ).strip("_")[:80]
    out_path = out_dir / f"{safe_name}.png"
    if out_path.exists():
        return out_path
    async with sem:
        try:
            r = await client.get(char.portrait_url)
            r.raise_for_status()
            out_path.write_bytes(r.content)
            return out_path
        except Exception as exc:  # noqa: BLE001
            log.warning("portrait fetch failed for %s: %s", char.name, exc)
            return None


async def download_all_async(
    *,
    db_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    concurrency: int = 8,
) -> dict[str, int]:
    out = out_dir or default_portrait_dir()
    out.mkdir(parents=True, exist_ok=True)
    engine = make_engine(db_path)
    init_db(engine)

    counts = {"downloaded": 0, "skipped_existing": 0, "missing_url": 0, "failed": 0}
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "NikkeOptimizer/0.1 (portraits)"},
    ) as client:
        with get_session(engine) as session:
            chars = list(session.exec(select(Character)).all())

        results = await asyncio.gather(
            *(_download_one(client, c, out, sem) for c in chars),
            return_exceptions=True,
        )

    paths_by_char: dict[str, Path] = {}
    for char, res in zip(chars, results):
        if isinstance(res, Exception):
            counts["failed"] += 1
            continue
        if res is None:
            if not char.portrait_url:
                counts["missing_url"] += 1
            else:
                counts["failed"] += 1
            continue
        paths_by_char[char.name] = res
        if res.stat().st_size > 0:
            counts["downloaded"] += 1

    # Persist CharacterIcon rows pointing at the downloaded files.
    with get_session(engine) as session:
        for char_name, path in paths_by_char.items():
            char = session.exec(
                select(Character).where(Character.name == char_name)
            ).one()
            existing = session.exec(
                select(CharacterIcon)
                .where(CharacterIcon.character_id == char.id)
                .where(CharacterIcon.source == "prydwen_portrait")
            ).first()
            if existing:
                existing.image_path = str(path)
                continue
            session.add(
                CharacterIcon(
                    character_id=char.id,
                    image_path=str(path),
                    source="prydwen_portrait",
                )
            )
        session.commit()

    return counts


def download_all(**kw) -> dict[str, int]:
    return asyncio.run(download_all_async(**kw))
