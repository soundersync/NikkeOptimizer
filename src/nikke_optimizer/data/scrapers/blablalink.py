"""BlablaLink character data mirror — pulls per-character stat tables.

BlablaLink hosts character data as static JSONs on
``sg-tools-cdn.blablalink.com``, but every URL is content-hashed at
runtime by their JS bundle (each path segment is rewritten via salted
MD5 with a per-segment salt array). That means we can't construct the
URLs ourselves: we have to load the page and let their JS resolve
them.

Approach: a headless Chromium (Playwright) opens the BlablaLink Nikke
browser, then visits each character detail page. We register a
response listener that captures any JSON whose path contains
``/roledata/``, ``/character_id_map.json``, or ``/nikke_list_``, and
saves it to disk keyed by the ``resource_id`` field inside the
payload.

Public surface:

  - :class:`BrowserFetcher` — context-managed browser session
  - :func:`fetch_id_map`   -> list[{name_code, resource_id, ...}]
  - :func:`fetch_roledata` -> the big per-character JSON
  - :func:`fetch_all`      -> bulk download every character
  - :func:`fetch_one`      -> single character, by resource_id or name

All fetchers share a polite throttle (default ~1s gap between page
navigations). Files cache to ``<user_data_dir>/blablalink/<lang>/``;
re-runs are cheap.

Requires ``pip install -e .[scrape] && playwright install chromium``.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

from platformdirs import user_data_dir

log = logging.getLogger(__name__)

SITE_BASE = "https://www.blablalink.com"
NIKKE_LIST_URL = f"{SITE_BASE}/shiftyspad/nikke-list/all"
CHARACTER_DETAIL_URL_TEMPLATE = f"{SITE_BASE}/shiftyspad/nikke?from=list&nikke={{resource_id}}"

DEFAULT_LANG = "en"
DEFAULT_RATE_SECONDS = 1.0
DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
DEFAULT_QUIET_PERIOD_MS = 800

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_APP_NAME = "NikkeOptimizer"
_CACHE_DIRNAME = "blablalink"
_BROWSER_PROFILE_DIRNAME = "_browser_profile"


def default_cache_dir() -> Path:
    base = Path(user_data_dir(_APP_NAME, appauthor=False)) / _CACHE_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def default_browser_profile_dir() -> Path:
    """Persistent Chromium profile directory.

    Reusing the same profile across runs lets static assets (CSS/JS
    chunks, character portraits, icons, fonts) hit Chromium's disk
    cache and skip the network entirely on the second-and-later
    page loads. Roledata JSONs are unique per character so they
    always fetch fresh, but the surrounding ~180 incidental requests
    per page mostly stop hitting the wire after the first character.
    """
    p = default_cache_dir() / _BROWSER_PROFILE_DIRNAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_path_for_roledata(resource_id: str, lang: str, cache_dir: Optional[Path] = None) -> Path:
    base = cache_dir or default_cache_dir()
    return base / lang / "roledata" / f"{resource_id}-v2-{lang}.json"


def cache_path_for_id_map(cache_dir: Optional[Path] = None) -> Path:
    base = cache_dir or default_cache_dir()
    return base / "character_id_map.json"


def cache_path_for_nikke_list(lang: str, cache_dir: Optional[Path] = None) -> Path:
    base = cache_dir or default_cache_dir()
    return base / lang / f"nikke_list_{lang}_v2.json"


@dataclass
class FetchStats:
    fetched: int = 0
    cached: int = 0
    errors: int = 0
    error_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.error_ids is None:
            self.error_ids = []


class BrowserFetcher:
    """Headless-Chromium harness for the BlablaLink CDN.

    The CDN's static JSON URLs are mangled at runtime by their JS, so
    we let their JS do the mangling for us and intercept the network
    responses. The fetcher's public methods all return parsed JSON
    payloads; persistence is the caller's job (the module-level
    helpers below handle caching).
    """

    def __init__(
        self,
        *,
        rate_seconds: float = DEFAULT_RATE_SECONDS,
        headless: bool = True,
        nav_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
        quiet_period_ms: int = DEFAULT_QUIET_PERIOD_MS,
        user_agent: str = USER_AGENT,
        profile_dir: Optional[Path] = None,
    ) -> None:
        self._rate_seconds = max(0.0, rate_seconds)
        self._headless = headless
        self._nav_timeout_ms = nav_timeout_ms
        self._quiet_period_ms = quiet_period_ms
        self._user_agent = user_agent
        self._profile_dir = profile_dir or default_browser_profile_dir()
        self._last_nav_at: float = 0.0
        # Lazy: created in __enter__
        self._pw_ctx: Any = None
        self._context: Any = None
        self._page: Any = None
        # Capture buffers — populated by the response listener.
        self._captured_roledata: dict[str, dict[str, Any]] = {}
        self._captured_id_map: Optional[list[dict[str, Any]]] = None
        self._captured_nikke_list: dict[str, list[dict[str, Any]]] = {}  # lang -> list

    def __enter__(self) -> "BrowserFetcher":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run "
                "`pip install -e '.[scrape]' && playwright install chromium`."
            ) from exc
        self._pw_ctx = sync_playwright().start()
        # launch_persistent_context returns the BrowserContext directly
        # and keeps disk cache + cookies under self._profile_dir between
        # runs. First run is cold; second-and-later are much quieter.
        self._context = self._pw_ctx.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=self._headless,
            user_agent=self._user_agent,
        )
        # Reuse the default page if one exists, otherwise create one.
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page.set_default_navigation_timeout(self._nav_timeout_ms)
        self._page.on("response", self._on_response)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._page is not None:
                self._page.close()
        finally:
            try:
                if self._context is not None:
                    self._context.close()
            finally:
                if self._pw_ctx is not None:
                    self._pw_ctx.stop()
        self._page = self._context = self._pw_ctx = None

    def _on_response(self, response: Any) -> None:
        """Capture JSONs whose body shape matches interesting patterns.

        The mangled CDN URLs are useless for routing (everything is
        under content-hashed paths), so we identify each payload by
        looking at its structure:

        - **id_map**: large list of dicts with exactly the keys
          ``{id, resource_id}``.
        - **nikke_list**: smaller list of dicts that have ``name_code``,
          ``resource_id`` and ``original_rare`` (full character index).
        - **roledata**: single dict carrying ``character_level_attack_list``
          (the per-character stat-table payload).
        """
        url = response.url
        if not url.endswith(".json"):
            return
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 — many irrelevant assets fail to parse
            return
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            sample = payload[0]
            if "name_code" in sample and "original_rare" in sample and "resource_id" in sample:
                self._captured_nikke_list.setdefault(DEFAULT_LANG, payload)
            elif set(sample.keys()) <= {"id", "resource_id"} and "resource_id" in sample:
                self._captured_id_map = payload
        elif isinstance(payload, dict):
            rid = payload.get("resource_id")
            if rid is not None and "character_level_attack_list" in payload:
                self._captured_roledata[str(rid)] = payload

    def _throttle(self) -> None:
        if self._rate_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_nav_at
        if elapsed < self._rate_seconds:
            time.sleep(self._rate_seconds - elapsed)

    def _navigate(self, url: str) -> None:
        self._throttle()
        self._last_nav_at = time.monotonic()
        log.info("navigating to %s", url)
        self._page.goto(url, wait_until="domcontentloaded")
        # Allow async fetches a moment to settle.
        try:
            self._page.wait_for_load_state("networkidle", timeout=self._nav_timeout_ms)
        except Exception as exc:  # noqa: BLE001
            log.debug("networkidle wait timed out for %s: %s", url, exc)
        # Brief quiet period to let lazy fetches complete.
        self._page.wait_for_timeout(self._quiet_period_ms)

    def bootstrap(self) -> None:
        """Visit the all-Nikkes list page so the id_map and nikke_list
        are captured. Idempotent — safe to call multiple times.
        """
        if self._captured_id_map is not None:
            return
        self._navigate(NIKKE_LIST_URL)
        if self._captured_id_map is None:
            log.warning(
                "bootstrap visited %s but no id_map response was captured; "
                "the page structure may have changed.",
                NIKKE_LIST_URL,
            )

    def fetch_id_map(self) -> list[dict[str, Any]]:
        if self._captured_id_map is None:
            self.bootstrap()
        if self._captured_id_map is None:
            raise RuntimeError(
                "Failed to capture character_id_map.json from the BlablaLink list page."
            )
        return self._captured_id_map

    def fetch_nikke_list(self, lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
        if lang not in self._captured_nikke_list:
            self.bootstrap()
        return self._captured_nikke_list.get(lang, [])

    def fetch_roledata(self, resource_id: str) -> Optional[dict[str, Any]]:
        """Navigate to a character's detail page and return its
        roledata JSON (or ``None`` if the page didn't load anything
        recognisable).
        """
        if resource_id in self._captured_roledata:
            return self._captured_roledata[resource_id]
        url = CHARACTER_DETAIL_URL_TEMPLATE.format(resource_id=resource_id)
        self._navigate(url)
        return self._captured_roledata.get(resource_id)


def _load_cached_json(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        log.warning("corrupt cache file at %s — refetching", path)
        return None


def _write_cache(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


@contextmanager
def _fetcher_or_provided(
    fetcher: Optional[BrowserFetcher],
    *,
    rate_seconds: float,
    headless: bool,
) -> Iterator[BrowserFetcher]:
    if fetcher is not None:
        yield fetcher
        return
    with BrowserFetcher(rate_seconds=rate_seconds, headless=headless) as f:
        yield f


def fetch_id_map(
    fetcher: Optional[BrowserFetcher] = None,
    *,
    rate_seconds: float = DEFAULT_RATE_SECONDS,
    headless: bool = True,
    cache_dir: Optional[Path] = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    cache_path = cache_path_for_id_map(cache_dir)
    if not force:
        cached = _load_cached_json(cache_path)
        if cached is not None:
            return cached  # type: ignore[return-value]
    with _fetcher_or_provided(fetcher, rate_seconds=rate_seconds, headless=headless) as f:
        data = f.fetch_id_map()
    _write_cache(cache_path, data)
    return data


def fetch_roledata(
    resource_id: str,
    *,
    fetcher: Optional[BrowserFetcher] = None,
    lang: str = DEFAULT_LANG,
    rate_seconds: float = DEFAULT_RATE_SECONDS,
    headless: bool = True,
    cache_dir: Optional[Path] = None,
    force: bool = False,
) -> Optional[dict[str, Any]]:
    cache_path = cache_path_for_roledata(resource_id, lang, cache_dir)
    if not force:
        cached = _load_cached_json(cache_path)
        if cached is not None:
            return cached  # type: ignore[return-value]
    with _fetcher_or_provided(fetcher, rate_seconds=rate_seconds, headless=headless) as f:
        data = f.fetch_roledata(resource_id)
    if data is None:
        return None
    _write_cache(cache_path, data)
    return data


def fetch_nikke_list(
    fetcher: Optional[BrowserFetcher] = None,
    *,
    lang: str = DEFAULT_LANG,
    rate_seconds: float = DEFAULT_RATE_SECONDS,
    headless: bool = True,
    cache_dir: Optional[Path] = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Fetch the per-language Nikke list (id, resource_id, name_code,
    name_localkey, original_rare, element, weapon, etc.). This is the
    canonical "what Nikkes exist" list — 189-ish entries today,
    versus the 1437-entry character_id_map which also includes
    Treasures, Dolls, weapons and other non-character resources.
    """
    cache_path = cache_path_for_nikke_list(lang, cache_dir)
    if not force:
        cached = _load_cached_json(cache_path)
        if cached is not None:
            return cached  # type: ignore[return-value]
    with _fetcher_or_provided(fetcher, rate_seconds=rate_seconds, headless=headless) as f:
        data = f.fetch_nikke_list(lang=lang)
    if not data:
        raise RuntimeError(
            "Failed to capture nikke_list from the BlablaLink list page."
        )
    _write_cache(cache_path, data)
    return data


def fetch_all(
    *,
    lang: str = DEFAULT_LANG,
    rate_seconds: float = DEFAULT_RATE_SECONDS,
    headless: bool = True,
    cache_dir: Optional[Path] = None,
    force: bool = False,
    only: Optional[Iterable[Any]] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> FetchStats:
    """Pull every roledata JSON listed in the per-language nikke_list.

    ``only`` restricts to a subset of resource_ids (for incremental
    re-fetches). ``progress`` is called as ``(idx, total, resource_id)``
    after each character.
    """
    stats = FetchStats()
    only_set: Optional[set[str]] = None
    if only is not None:
        only_set = {str(x) for x in only}
    with BrowserFetcher(rate_seconds=rate_seconds, headless=headless) as fetcher:
        nikke_list = fetch_nikke_list(
            fetcher=fetcher, lang=lang, cache_dir=cache_dir, force=force
        )
        targets = [
            rec for rec in nikke_list
            if only_set is None or str(rec.get("resource_id")) in only_set
        ]
        total = len(targets)
        for idx, rec in enumerate(targets, start=1):
            rid = rec.get("resource_id")
            if rid is None:
                stats.errors += 1
                continue
            rid_str = str(rid)
            cached_before = cache_path_for_roledata(rid_str, lang, cache_dir).is_file()
            try:
                data = fetch_roledata(
                    rid_str,
                    fetcher=fetcher,
                    lang=lang,
                    cache_dir=cache_dir,
                    force=force,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("failed to fetch %s: %s", rid_str, exc)
                stats.errors += 1
                stats.error_ids.append(rid_str)  # type: ignore[union-attr]
                if progress is not None:
                    progress(idx, total, rid_str)
                continue
            if data is None:
                stats.errors += 1
                stats.error_ids.append(rid_str)  # type: ignore[union-attr]
            elif cached_before and not force:
                stats.cached += 1
            else:
                stats.fetched += 1
            if progress is not None:
                progress(idx, total, rid_str)
    return stats


def fetch_one(
    identifier: str,
    *,
    lang: str = DEFAULT_LANG,
    rate_seconds: float = DEFAULT_RATE_SECONDS,
    headless: bool = True,
    cache_dir: Optional[Path] = None,
    force: bool = False,
) -> Optional[dict[str, Any]]:
    """Fetch a single character. ``identifier`` can be the integer
    ``resource_id`` (e.g. ``"90"``), the ``name_code`` (e.g. ``"5005"``),
    or the localized character name (e.g. ``"Emma"``, case-insensitive).
    """
    with BrowserFetcher(rate_seconds=rate_seconds, headless=headless) as fetcher:
        nikke_list = fetch_nikke_list(
            fetcher=fetcher, lang=lang, cache_dir=cache_dir, force=force
        )
        rid = _resolve_identifier(identifier, nikke_list)
        if rid is None:
            log.error(
                "could not resolve identifier %r against nikke_list (lang=%s)",
                identifier,
                lang,
            )
            return None
        return fetch_roledata(
            rid,
            fetcher=fetcher,
            lang=lang,
            cache_dir=cache_dir,
            force=force,
        )


def _resolve_identifier(
    identifier: str, nikke_list: list[dict[str, Any]]
) -> Optional[str]:
    """Resolve a user-typed identifier to a resource_id string.

    Match order: exact resource_id, exact name_code, then case-
    insensitive ``name_localkey.name``.
    """
    needle = identifier.strip()
    needle_lower = needle.lower()
    for rec in nikke_list:
        if str(rec.get("resource_id", "")) == needle:
            return str(rec["resource_id"])
    for rec in nikke_list:
        if str(rec.get("name_code", "")) == needle:
            return str(rec["resource_id"])
    for rec in nikke_list:
        name = (rec.get("name_localkey") or {}).get("name")
        if isinstance(name, str) and name.lower() == needle_lower:
            return str(rec["resource_id"])
    return None
