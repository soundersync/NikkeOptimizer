"""ShiftyPad scraper — pulls a player's roster + outpost from BlablaLink.

The ShiftyPad section of BlablaLink (https://www.blablalink.com/shiftyspad)
is the publisher-adjacent player-profile surface. Logged-in users see
their own private data; with the profile owner's permission, others can
view it too. The relevant in-game data is exposed through four
``api.blablalink.com`` JSON endpoints that fire as the SPA navigates:

  - ``Game/GetUserProfileBasicInfo`` — nickname, region, currencies.
  - ``Game/GetUserProfileOutpostInfo`` — synchro level + Outpost
    research levels (general + class + manufacturer). Maps directly
    onto ``AccountState``.
  - ``Game/GetUserCharacters`` — list of owned Nikkes (``name_code``,
    CP, grade, core, costume, synchro slot level). The home page hits
    this once.
  - ``Game/GetUserCharacterDetails`` — per-character investment
    (skills, OL gear, cubes, doll/treasure, bond). Each character
    detail page (``/shiftyspad/nikke?nikke=<resource_id>``) fires one
    of these.

Approach: a Playwright session navigates to the actual ShiftyPad pages
the same way a user would. The XHR responses are captured by a network
listener and returned as parsed JSON. We never hit the API
"out-of-band" — each fetch corresponds to one page navigation the
public UI would also do, with randomized delays between them so the
traffic shape looks like a real player browsing their roster.

Privacy handling:

  - ``GetUserCharacters`` / ``GetUserCharacterDetails`` return
    ``code = 1301002`` ("user not allow show nikkeinfo in Shiftypad")
    when the target has My Nikkes private. The fetcher reports this
    as ``is_roster_private = True`` and returns no detail payload.
  - ``GetUserProfileOutpostInfo`` is selectively redacted: every
    ``recycle_room_researches`` entry has ``tid == lv == exp ==
    -9999`` when the owner has set Outpost private; non-research
    fields (synchro_level, outpost_battle_level, ...) stay populated.
    The fetcher reports this as ``is_outpost_private = True`` and
    leaves the redacted fields as-is for the caller to drop.

Requires Playwright. A logged-in cookie state (see
``login_blablalink.py`` / the future ``shiftyspad-login`` CLI verb)
must already exist in the persistent profile directory.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Optional

from .blablalink import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    USER_AGENT,
    default_browser_profile_dir,
)

log = logging.getLogger(__name__)

SITE_BASE = "https://www.blablalink.com"
API_BASE = "https://api.blablalink.com/api/game/proxy/Game"
HOME_URL_TEMPLATE = SITE_BASE + "/shiftyspad/home?uid={uid}&openid={openid}"
DETAIL_URL_TEMPLATE = (
    SITE_BASE + "/shiftyspad/nikke?nikke={rid}&skin_index=2"
    "&uid={uid}&openid={openid}"
)

# Numeric sentinel for redacted (private) outpost fields.
PRIVACY_SENTINEL = -9999

# Error code returned by GetUserCharacters / GetUserCharacterDetails
# when the target's My Nikkes is set to private.
PRIVATE_NIKKE_INFO_CODE = 1301002

# Default pacing for per-character detail fetches. Each navigation is
# preceded by a uniform random wait in this range, in seconds.
DEFAULT_DETAIL_DELAY_RANGE: tuple[float, float] = (3.0, 7.0)

# Per-page settle: post-DCL wait before considering the XHR captured.
# Bumped from 2.5s → 4s after CHIGLETS / LUCARNE / NANA / BECHO / RUSTY
# came back with missing GetUserCharacters captures in the season-29
# scrape — the SPA's roster XHR sometimes fires after networkidle
# triggers but before the settle window expires. The extra ~1.5s
# catches the race; the per-player home_pacing_range already spaces
# navigations far enough that the additional cost is amortized.
DEFAULT_SETTLE_MS = 4_000


@dataclass
class HomePayload:
    """The three home-page endpoints' parsed bodies, plus privacy flags."""

    basic_info: Optional[dict[str, Any]] = None
    outpost_info: Optional[dict[str, Any]] = None
    characters: list[dict[str, Any]] = field(default_factory=list)
    is_roster_private: bool = False
    is_outpost_private: bool = False
    raw_responses: dict[str, Any] = field(default_factory=dict)


@dataclass
class CharacterDetailPayload:
    """One character's ``GetUserCharacterDetails`` parsed body.

    ``state_effects`` is the sibling field returned alongside
    ``character_details``: a list whose entries carry exact percent
    values for the gear ``option_id`` set this character has rolled.
    Needed to decode OL gear bonuses (option_id → bonus_type +
    percent) via :func:`shiftyspad_decoder.decode_gear_bonus`.
    """

    name_code: int
    detail: Optional[dict[str, Any]] = None
    state_effects: list[dict[str, Any]] = field(default_factory=list)
    is_private: bool = False


def decode_uid(uid_b64: str) -> tuple[int, str]:
    """Decode a base64 ShiftyPad uid (e.g. from a URL) to ``(area_id, openid)``.

    The URL form is ``uid=<base64>`` where the decoded value is
    ``"<area_id>-<openid>"``. The area_id is the BlablaLink game id
    (29080 for NIKKE) and is NOT the ``nikke_area_id`` the API body
    expects — that's a separate server-region value (e.g. 82 for SEA)
    that comes from ``GetUserProfileBasicInfo``.
    """
    raw = base64.b64decode(uid_b64).decode("ascii")
    area, _, openid = raw.partition("-")
    if not openid:
        raise ValueError(f"invalid shiftyspad uid {uid_b64!r}: missing '-' separator")
    return int(area), openid


def _derive_roster_state(
    roster_response: Optional[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    """Decide ``(is_private, characters)`` from a captured
    ``GetUserCharacters`` response.

    Conservative — anything that isn't explicit, unambiguous "public"
    evidence is treated as private:

    * ``None`` (XHR never landed) → private.
    * ``code == PRIVATE_NIKKE_INFO_CODE`` (1301002, explicit private) → private.
    * ``code == 0`` with non-empty characters → public.
    * ``code == 0`` with empty characters → private (active players
      always own ≥ 1 NIKKE, so an empty list indicates the response
      hydrated incompletely; flagging public on no data was the
      original bug surfaced by CHIGLETS / LUCARNE / NANA).
    * Any other code → private (unknown error, don't lie).
    """
    if roster_response is None:
        return True, []
    code = roster_response.get("code")
    if code == PRIVATE_NIKKE_INFO_CODE:
        return True, []
    if code == 0:
        characters = (roster_response.get("data") or {}).get("characters") or []
        return (not characters), list(characters)
    return True, []


def _is_outpost_redacted(outpost_info: dict[str, Any]) -> bool:
    """True when the outpost has the per-field privacy sentinel applied
    to ``recycle_room_researches``. The remaining fields stay public.
    """
    for r in (outpost_info or {}).get("recycle_room_researches") or []:
        if r.get("lv") == PRIVACY_SENTINEL or r.get("tid") == PRIVACY_SENTINEL:
            return True
    return False


def _is_redacted_value(value: Any) -> bool:
    """True when a numeric field carries the privacy sentinel."""
    return isinstance(value, int) and value == PRIVACY_SENTINEL


# ---------------------------------------------------------------------------
# Playwright-backed fetcher
# ---------------------------------------------------------------------------


class ShiftyPadFetcher:
    """Headless-Chromium session for the ShiftyPad section of BlablaLink.

    Reuses the persistent profile from ``blablalink.BrowserFetcher`` so
    a single manual login warms both scrapers. The fetcher exposes:

      - :meth:`fetch_home` — navigate to ``/shiftyspad/home?uid=...``,
        return the three home-page endpoint payloads.
      - :meth:`fetch_character_detail` — navigate to
        ``/shiftyspad/nikke?nikke=<resource_id>``, return that
        character's ``GetUserCharacterDetails`` payload.

    Inter-fetch pacing is randomized in ``DEFAULT_DETAIL_DELAY_RANGE``
    so the request shape resembles a player clicking through their
    own roster. Never bulk-fetches multiple characters in one body
    even though the API supports it.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        nav_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
        settle_ms: int = DEFAULT_SETTLE_MS,
        detail_delay_range: tuple[float, float] = DEFAULT_DETAIL_DELAY_RANGE,
        user_agent: str = USER_AGENT,
        profile_dir: Optional[Any] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._headless = headless
        self._nav_timeout_ms = nav_timeout_ms
        self._settle_ms = settle_ms
        self._delay_lo, self._delay_hi = detail_delay_range
        self._user_agent = user_agent
        self._profile_dir = profile_dir or default_browser_profile_dir()
        self._rng = rng or random.Random()
        self._last_detail_at: float = 0.0
        self._pw_ctx: Any = None
        self._context: Any = None
        self._page: Any = None
        # Capture buffers — reset per-navigation in _reset_capture().
        self._captured: dict[str, dict[str, Any]] = {}

    def __enter__(self) -> "ShiftyPadFetcher":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run "
                "`pip install -e '.[scrape]' && playwright install chromium`."
            ) from exc
        self._pw_ctx = sync_playwright().start()
        self._context = self._pw_ctx.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=self._headless,
            user_agent=self._user_agent,
        )
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

    def _reset_capture(self) -> None:
        self._captured.clear()

    # Endpoints we care about — keyed by suffix of the request URL.
    _ENDPOINT_KEYS = (
        "Game/GetUserProfileBasicInfo",
        "Game/GetUserProfileOutpostInfo",
        "Game/GetUserCharacters",
        "Game/GetUserCharacterDetails",
    )

    def _on_response(self, response: Any) -> None:
        url = response.url
        # Persist any static CDN tables (cubes, treasures, gear defs,
        # bond table) that load opportunistically during navigation.
        # The decoder picks up new entries on the next scrape.
        if "sg-tools-cdn.blablalink.com" in url and url.endswith(".json"):
            try:
                from .shiftyspad_decoder import maybe_persist_table_response
                maybe_persist_table_response(url, response.json())
            except Exception:  # noqa: BLE001 — many CDN files are unrelated
                pass
        # Only consume API responses on the proxy host with one of our
        # known endpoint suffixes. Everything else is page chrome.
        if "api.blablalink.com/api/game/proxy/" not in url:
            return
        for key in self._ENDPOINT_KEYS:
            if url.endswith(key):
                try:
                    self._captured[key] = response.json()
                except Exception as exc:  # noqa: BLE001
                    log.debug("non-JSON body on %s: %s", url, exc)
                return

    def _navigate(self, url: str) -> None:
        self._reset_capture()
        log.info("shiftyspad: navigating to %s", url)
        self._page.goto(url, wait_until="domcontentloaded")
        try:
            self._page.wait_for_load_state("networkidle", timeout=self._nav_timeout_ms)
        except Exception as exc:  # noqa: BLE001
            log.debug("networkidle wait timed out for %s: %s", url, exc)
        self._page.wait_for_timeout(self._settle_ms)

    def _pace_detail(self) -> None:
        """Wait a randomized interval between detail-page navigations.

        Skipped on the first detail fetch in a session (no prior
        navigation to space from).
        """
        if self._last_detail_at == 0.0:
            return
        target = self._rng.uniform(self._delay_lo, self._delay_hi)
        elapsed = time.monotonic() - self._last_detail_at
        if elapsed < target:
            time.sleep(target - elapsed)

    def fetch_home(self, uid_b64: str, *, max_retries: int = 2) -> HomePayload:
        """Fetch the home page payload for a player.

        ``max_retries`` controls how many times we'll re-navigate when
        ``GetUserCharacters`` didn't land in ``_captured`` after the
        first navigation. The retry only fires when the XHR is
        genuinely absent — an explicit ``code == 1301002`` (private)
        response DOES land in ``_captured`` and counts as "we have a
        signal", so genuine private accounts are not retried.

        Default is two retries (3 attempts total) with exponential
        backoff between them. Bumped from 1 retry after a 2026-05-19
        observation where a manual ``refresh-self-from-rookie 14``
        flaked twice in a row with "GetUserCharacters missing" while
        a direct ``fetch-shiftyspad`` call 30s later worked fine.
        """
        url = HOME_URL_TEMPLATE.format(uid=uid_b64, openid=uid_b64)
        for attempt in range(max_retries + 1):
            self._navigate(url)
            if self._captured.get("Game/GetUserCharacters") is not None:
                break
            if attempt < max_retries:
                # Log what XHRs DID land — diagnostic for triaging
                # whether the page even loaded vs. just one XHR missing.
                captured_keys = list(self._captured.keys())
                log.warning(
                    "fetch_home: GetUserCharacters missing for uid=%s; "
                    "re-navigating (attempt %d/%d). Captured XHRs: %s",
                    uid_b64, attempt + 2, max_retries + 1,
                    captured_keys or "none",
                )
                # Exponential backoff: 3-5s, then 6-10s, then 12-20s.
                # Spreads us out from any soft rate-limit BlablaLink
                # might apply on back-to-back navigations.
                base = (2 ** attempt) * 3.0
                time.sleep(self._rng.uniform(base, base * 1.7))

        payload = HomePayload(raw_responses=dict(self._captured))

        basic = self._captured.get("Game/GetUserProfileBasicInfo")
        if basic and basic.get("code") == 0:
            payload.basic_info = (basic.get("data") or {}).get("basic_info")

        # Outpost privacy detection — mirror of the conservative
        # roster-privacy default (see _derive_roster_state). If the
        # XHR didn't land, treat as private rather than silently
        # claiming public.
        outpost = self._captured.get("Game/GetUserProfileOutpostInfo")
        if outpost is None:
            payload.is_outpost_private = True
        elif outpost.get("code") == 0:
            payload.outpost_info = (outpost.get("data") or {}).get("outpost_info")
            if payload.outpost_info and _is_outpost_redacted(payload.outpost_info):
                payload.is_outpost_private = True
        else:
            # Non-zero code from a captured response — unknown error,
            # treat as private.
            payload.is_outpost_private = True

        is_private, characters = _derive_roster_state(
            self._captured.get("Game/GetUserCharacters")
        )
        payload.is_roster_private = is_private
        payload.characters = characters
        return payload

    def fetch_character_detail(
        self,
        uid_b64: str,
        resource_id: int | str,
    ) -> CharacterDetailPayload:
        self._pace_detail()
        url = DETAIL_URL_TEMPLATE.format(
            rid=resource_id, uid=uid_b64, openid=uid_b64
        )
        self._navigate(url)
        self._last_detail_at = time.monotonic()

        body = self._captured.get("Game/GetUserCharacterDetails")
        if not body:
            return CharacterDetailPayload(name_code=-1, detail=None)
        if body.get("code") == PRIVATE_NIKKE_INFO_CODE:
            return CharacterDetailPayload(name_code=-1, is_private=True)
        data = body.get("data") or {}
        details = data.get("character_details") or []
        state_effects = data.get("state_effects") or []
        if not details:
            return CharacterDetailPayload(name_code=-1, detail=None)
        first = details[0]
        return CharacterDetailPayload(
            name_code=int(first.get("name_code", -1)),
            detail=first,
            state_effects=state_effects,
        )


# ---------------------------------------------------------------------------
# Module-level conveniences
# ---------------------------------------------------------------------------


@contextmanager
def _fetcher_or_provided(
    fetcher: Optional[ShiftyPadFetcher],
    *,
    headless: bool,
    detail_delay_range: tuple[float, float],
) -> Iterator[ShiftyPadFetcher]:
    if fetcher is not None:
        yield fetcher
        return
    with ShiftyPadFetcher(
        headless=headless, detail_delay_range=detail_delay_range
    ) as f:
        yield f


def fetch_home(
    uid_b64: str,
    *,
    fetcher: Optional[ShiftyPadFetcher] = None,
    headless: bool = True,
) -> HomePayload:
    """One-shot helper: open a fetcher, navigate to the player's home
    page, return the parsed payloads.
    """
    with _fetcher_or_provided(
        fetcher, headless=headless, detail_delay_range=DEFAULT_DETAIL_DELAY_RANGE
    ) as f:
        return f.fetch_home(uid_b64)


def fetch_character_details(
    uid_b64: str,
    name_codes: Iterable[int],
    name_code_to_resource_id: dict[int, int],
    *,
    fetcher: Optional[ShiftyPadFetcher] = None,
    headless: bool = True,
    detail_delay_range: tuple[float, float] = DEFAULT_DETAIL_DELAY_RANGE,
    progress: Optional[Any] = None,
) -> list[CharacterDetailPayload]:
    """Fetch detail payloads one-by-one for the given ``name_codes``.

    ``name_code_to_resource_id`` is the translation from API name_code
    → BlablaLink resource_id used in the detail URL (these are two
    different IDs). Caller is expected to build it once from the
    mirrored ``nikke_list_<lang>_v2.json`` cache.

    ``progress`` is an optional callable invoked as ``progress(i, n,
    name_code)`` between fetches — useful for a CLI tqdm bar.
    """
    results: list[CharacterDetailPayload] = []
    codes = list(name_codes)
    with _fetcher_or_provided(
        fetcher, headless=headless, detail_delay_range=detail_delay_range
    ) as f:
        for i, code in enumerate(codes):
            if progress is not None:
                progress(i, len(codes), code)
            rid = name_code_to_resource_id.get(code)
            if rid is None:
                log.warning("no resource_id for name_code=%s — skipping", code)
                results.append(CharacterDetailPayload(name_code=code, detail=None))
                continue
            results.append(f.fetch_character_detail(uid_b64, rid))
    return results
