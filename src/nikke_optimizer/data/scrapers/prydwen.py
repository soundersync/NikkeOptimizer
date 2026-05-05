"""Prydwen.gg character data scraper.

Prydwen exposes its content as Gatsby `page-data.json` files (the same approach
the archived NikkeAPI used). We hit those JSON endpoints directly rather than
parsing HTML — far more stable.

Endpoints:
  - INDEX: https://www.prydwen.gg/page-data/nikke/characters/page-data.json
    -> result.data.allCharacters.nodes[] with slug, basic info for all chars
  - DETAIL: https://www.prydwen.gg/page-data/nikke/characters/<slug>/page-data.json
    -> result.data.currentUnit.nodes[0] with full data (skills, stats, ...)

This module fetches + normalizes; persistence is in `refresh.py`.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx

from ..enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)

log = logging.getLogger(__name__)

PRYDWEN_BASE = "https://www.prydwen.gg"
INDEX_URL = f"{PRYDWEN_BASE}/page-data/nikke/characters/page-data.json"
DETAIL_URL_TEMPLATE = f"{PRYDWEN_BASE}/page-data/nikke/characters/{{slug}}/page-data.json"

_WEAPON_MAP: dict[str, WeaponClass] = {
    "SMG": WeaponClass.SMG,
    "Assault Rifle": WeaponClass.AR,
    "Sniper Rifle": WeaponClass.SR,
    "Rocket Launcher": WeaponClass.RL,
    "Shotgun": WeaponClass.SG,
    "Minigun": WeaponClass.MG,
}

_BURST_MAP: dict[str, BurstType] = {
    "1": BurstType.I,
    "2": BurstType.II,
    "3": BurstType.III,
    "All": BurstType.FLEX,
    "I": BurstType.I,
    "II": BurstType.II,
    "III": BurstType.III,
}

_ELEMENT_MAP: dict[str, Element] = {
    "Fire": Element.FIRE,
    "Water": Element.WATER,
    "Electric": Element.ELECTRIC,
    "Iron": Element.IRON,
    "Wind": Element.WIND,
}

_MANUFACTURER_MAP: dict[str, Manufacturer] = {
    "Elysion": Manufacturer.ELYSION,
    "Missilis": Manufacturer.MISSILIS,
    "Tetra": Manufacturer.TETRA,
    "Pilgrim": Manufacturer.PILGRIM,
    "Abnormal": Manufacturer.ABNORMAL,
}

_RARITY_MAP: dict[str, Rarity] = {
    "R": Rarity.R,
    "SR": Rarity.SR,
    "SSR": Rarity.SSR,
}


class NormalizedCharacter:
    """Plain container of normalized character fields ready for SQLModel insertion."""

    __slots__ = (
        "name",
        "slug",
        "rarity",
        "element",
        "weapon_class",
        "burst_type",
        "manufacturer",
        "role_tags",
        "base_atk",
        "base_hp",
        "base_def",
        "skill1_description",
        "skill2_description",
        "burst_description",
        "portrait_url",
        # Slice #61 — additional Prydwen fields. Names match the Character
        # SQLModel columns so to_kwargs() drops straight into the DB layer.
        "specialities",
        "pros_raw",
        "cons_raw",
        "review_raw",
        "skill_analysis_raw",
        "harmony_cubes_info_raw",
        "has_treasure",
        "high_investment",
        "is_limited",
        "limited_event",
        "release_date",
        "squad",
        "raw_node",
    )

    def __init__(self, **kw: Any) -> None:
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def to_kwargs(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__ if k != "raw_node"}


def flatten_rich_text(raw: Optional[str]) -> Optional[str]:
    """Flatten a Contentful rich-text JSON string into plain text.

    Walks the Contentful AST collecting every ``text`` node's value with
    space joins. Used by the web UI when rendering review/pros/cons/etc.
    in plain form, and by anything searching the prose for keywords.
    Returns ``None`` if the input is empty or malformed JSON.
    """
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    pieces: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("nodeType") == "text" and "value" in node:
                pieces.append(node["value"])
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    text = " ".join(p for p in pieces if p).strip()
    return text or None


def _flatten_skill_description(skill_obj: Optional[dict]) -> Optional[str]:
    """Prydwen stores skill text in Contentful Rich Text format. Flatten to a string.

    Prefers level-10 (max) text when present; falls back to level-1.
    """
    if not skill_obj:
        return None
    raw = (
        skill_obj.get("descriptionLevel10", {}).get("raw")
        or skill_obj.get("descriptionLevel1", {}).get("raw")
    )
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    pieces: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("nodeType") == "text" and "value" in node:
                pieces.append(node["value"])
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    text = " ".join(p for p in pieces if p).strip()
    return text or None


def _portrait_url(node: dict) -> Optional[str]:
    img = node.get("smallImage") or node.get("cardImage") or node.get("fullImage")
    if not img:
        return None
    try:
        path = img["localFile"]["childImageSharp"]["gatsbyImageData"]["images"]["fallback"]["src"]
    except (KeyError, TypeError):
        return None
    return f"{PRYDWEN_BASE}{path}" if path.startswith("/") else path


def _stats(node: dict) -> tuple[Optional[int], Optional[int], Optional[int]]:
    stats = node.get("stats")
    if not isinstance(stats, dict) or not stats:
        return None, None, None
    keys = list(stats.keys())
    if len(keys) < 2:
        return None, None, None
    bucket = stats[keys[1]]  # NikkeAPI used [1] — second key is the level-200 bucket
    if not isinstance(bucket, dict):
        return None, None, None

    def _to_int(v: Any) -> Optional[int]:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return _to_int(bucket.get("hp")), _to_int(bucket.get("atk")), _to_int(bucket.get("def"))


def normalize_character_node(node: dict) -> Optional[NormalizedCharacter]:
    """Convert one Prydwen `currentUnit` node into a `NormalizedCharacter`.

    Returns None if required fields are missing — caller should log + skip.
    """
    name = node.get("name")
    slug = node.get("slug")
    if not name or not slug:
        return None
    try:
        rarity = _RARITY_MAP[node["rarity"]]
        element = _ELEMENT_MAP[node["element"]]
        weapon_class = _WEAPON_MAP[node["weapon"]]
        burst_type = _BURST_MAP[str(node["burstType"])]
    except KeyError as exc:
        log.warning("character %s missing/unknown enum field: %s", name, exc)
        return None

    manufacturer = _MANUFACTURER_MAP.get(node.get("manufacturer", ""))
    specialities = node.get("specialities") or []
    role_tags: list[str] = []
    if node.get("class"):
        role_tags.append(node["class"])
    role_tags.extend(specialities)

    skills = node.get("skills") or {}
    if isinstance(skills, list):  # Prydwen sometimes uses an indexed list
        skills_dict = {f"skill_{i}": s for i, s in enumerate(skills)}
        skill1, skill2, burst = (skills + [None, None, None])[:3]
    else:
        skill1 = skills.get("skill1") or skills.get("skill_0")
        skill2 = skills.get("skill2") or skills.get("skill_1")
        burst = skills.get("burst") or skills.get("skill_2")

    hp, atk, def_ = _stats(node)

    # Pull the rich-text raw JSON strings as-is. We store the verbatim
    # JSON so the web UI can render with formatting; flatten_rich_text()
    # produces plain prose when needed for search / display fallback.
    def _raw(field: str) -> Optional[str]:
        block = node.get(field)
        if isinstance(block, dict):
            v = block.get("raw")
            if isinstance(v, str) and v.strip():
                return v
        return None

    return NormalizedCharacter(
        name=name,
        slug=slug,
        rarity=rarity,
        element=element,
        weapon_class=weapon_class,
        burst_type=burst_type,
        manufacturer=manufacturer,
        role_tags=role_tags,
        base_atk=atk,
        base_hp=hp,
        base_def=def_,
        skill1_description=_flatten_skill_description(skill1),
        skill2_description=_flatten_skill_description(skill2),
        burst_description=_flatten_skill_description(burst),
        portrait_url=_portrait_url(node),
        # Slice #61 — additional Prydwen fields.
        specialities=list(specialities),
        pros_raw=_raw("pros"),
        cons_raw=_raw("cons"),
        review_raw=_raw("review"),
        skill_analysis_raw=_raw("skillAnalysis"),
        harmony_cubes_info_raw=_raw("harmonyCubesInfo"),
        has_treasure=bool(node["hasTreasure"]) if node.get("hasTreasure") is not None else None,
        high_investment=bool(node["highInvestement"]) if node.get("highInvestement") is not None else None,
        is_limited=bool(node["isLimited"]) if node.get("isLimited") is not None else None,
        limited_event=node.get("limitedEvent"),
        release_date=node.get("releaseDate"),
        squad=node.get("squad"),
        raw_node=node,
    )


class PrydwenClient:
    """Async HTTP client for Prydwen's gatsby page-data endpoints with on-disk cache."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        *,
        concurrency: int = 8,
        timeout: float = 30.0,
        user_agent: str = "NikkeOptimizer/0.1 (+local research tool)",
    ) -> None:
        self.cache_dir = cache_dir
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    async def __aenter__(self) -> "PrydwenClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    def _cache_path(self, key: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        safe = key.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe}.json"

    async def _get_json(self, url: str, *, cache_key: Optional[str] = None) -> dict:
        cache = self._cache_path(cache_key) if cache_key else None
        if cache and cache.exists():
            return json.loads(cache.read_text())
        async with self._semaphore:
            r = await self._client.get(url)
            r.raise_for_status()
            data = r.json()
        if cache:
            cache.write_text(json.dumps(data))
        return data

    async def list_character_slugs(self) -> list[str]:
        data = await self._get_json(INDEX_URL, cache_key="index")
        nodes = data["result"]["data"]["allCharacters"]["nodes"]
        return [n["slug"] for n in nodes if n.get("slug")]

    async def fetch_character(self, slug: str) -> Optional[NormalizedCharacter]:
        data = await self._get_json(
            DETAIL_URL_TEMPLATE.format(slug=slug),
            cache_key=f"char_{slug}",
        )
        try:
            node = data["result"]["data"]["currentUnit"]["nodes"][0]
        except (KeyError, IndexError):
            log.warning("no currentUnit node for slug=%s", slug)
            return None
        return normalize_character_node(node)

    async def fetch_all(
        self, slugs: Optional[Iterable[str]] = None
    ) -> list[NormalizedCharacter]:
        if slugs is None:
            slugs = await self.list_character_slugs()
        slugs = list(slugs)
        results = await asyncio.gather(
            *(self.fetch_character(s) for s in slugs), return_exceptions=True
        )
        out: list[NormalizedCharacter] = []
        for slug, r in zip(slugs, results):
            if isinstance(r, Exception):
                log.warning("fetch failed for %s: %s", slug, r)
                continue
            if r is None:
                continue
            out.append(r)
        return out
