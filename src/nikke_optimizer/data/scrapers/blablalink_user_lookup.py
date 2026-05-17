"""BlablaLink player-lookup scraper.

Implements the SKILL.md "Nikke Player Lookup" flow as a typed Python
module: given a list of ``(name, expected_level)`` pairs, search
BlablaLink for each, verify the in-game level, navigate to the
shiftyspad/home page of the matched account, and pull the JSON XHRs
that back the profile UI. Returns rows ready for a 31-column CSV.

Unlike the original JS skill — which regex-parses
``document.body.innerText`` — this implementation derives every CSV
field from typed JSON responses. The fields it depends on:

  - ``SearchUser``                  → ``intl_openid``, ``area_id``, ``role_name``
  - ``GetUserGamePlayerInfo``       → ``player_level`` for level verification
  - ``GetUserProfileBasicInfo``     → campaign progress, squad power, costumes,
                                       registration date, overclock high score
  - ``GetUserProfileOutpostInfo``   → synchro level, research levels (by tid),
                                       Memoirs/Call Logs/Data counts, jukebox (BGM)
  - ``GetUserCharacters``           → code 1301002 → My Nikkes Private
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import logging
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Optional
from urllib.parse import quote

from .shiftyspad import (
    DEFAULT_DETAIL_DELAY_RANGE,
    SITE_BASE,
    HomePayload,
    ShiftyPadFetcher,
)

log = logging.getLogger(__name__)

API_STANDALONE = "https://api.blablalink.com/api/ugc/direct/standalonesite"
SEARCH_USER_URL = f"{API_STANDALONE}/User/SearchUser"
GAME_PLAYER_INFO_URL = f"{API_STANDALONE}/User/GetUserGamePlayerInfo"

# Search API caps at 50; higher values silently degrade (per SKILL.md).
SEARCH_LIMIT = 50

# Default level-match tolerance. The SKILL.md guidance is ±10, widening
# to ±15 for source lists more than a few days old. The user-supplied
# 32-player list is dated 2026-05-16 (today), but rosters churn ±5 per
# day for active players, so default to ±15.
DEFAULT_LEVEL_TOLERANCE = 15

# server area_id → display name (per SKILL.md).
SERVER_NAMES: dict[str, str] = {
    "81": "Japan",
    "82": "NA",
    "84": "Global",
    "85": "SEA",
    "91": "HMT",
    "": "(no game account)",
}

# Korea is sometimes seen as area_id "83" or "92" depending on endpoint;
# normalize as best we can.
SERVER_NAMES["83"] = "Korea"
SERVER_NAMES["92"] = "Korea"

NA_AREA_ID = "82"

# tid → Outpost research field. The mfr ordering (1201-1205) was
# verified empirically — see RESEARCH_TID_TO_FIELD in
# roster/shiftyspad_importer.py.
RESEARCH_TID_TO_CSV_LABEL: dict[int, str] = {
    1001: "General Research Lv",
    1101: "Attacker Lv",
    1102: "Defender Lv",
    1103: "Supporter Lv",
    1201: "Elysion Lv",
    1202: "Missilis Lv",
    1203: "Tetra Lv",
    1204: "Pilgrim Lv",
    1205: "Abnormal Lv",
}

# Lost Relics: SKILL.md CSV labels → memorial_counts category.
# jukebox_count is a sibling field, not in memorial_counts.
LOST_RELIC_CATEGORY_MAP: dict[str, str] = {
    "Memoirs": "HandWriting",
    "Call Logs": "CallLog",
    "Data": "Data",
}

# CSV column order — triage flavor: drops Normal/Hard Campaign (encoded
# raw integers, low value), adds UID + Worth Fetching so the row is
# directly usable as input to `fetch-shiftyspad <uid>`. The 31-column
# SKILL.md schema is sufficient context-only and not exported.
CSV_COLUMNS: tuple[str, ...] = (
    "Player Name", "Expected Level", "Actual Level", "Server", "Status",
    "Worth Fetching", "My Nikkes Status", "Outpost Info Status",
    "Found On Servers",
    "UID", "Shiftyspad URL",
    "Towers", "Nikkes Count", "Squad Power", "Costumes",
    "Registration Date", "Synchro Level", "Overclock Mode",
    "General Research Lv", "Attacker Lv", "Defender Lv", "Supporter Lv",
    "Missilis Lv", "Elysion Lv", "Tetra Lv", "Pilgrim Lv", "Abnormal Lv",
    "Memoirs", "Call Logs", "Data", "BGM",
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PlayerQuery:
    """Input row: a player to look up at an expected in-game level."""
    name: str
    expected_level: int


@dataclass
class MatchResult:
    """Outcome of search + level verification for a single PlayerQuery."""

    status: str  # "Found" | "No Search Results" | "Not On NA" | "Level Mismatch"
    found_on_servers: list[str] = field(default_factory=list)
    intl_openid: Optional[str] = None
    actual_level: Optional[int] = None
    server: Optional[str] = None
    game_info: Optional[dict[str, Any]] = None  # GetUserGamePlayerInfo.data


# ---------------------------------------------------------------------------
# API helpers — POST via the Playwright page's request context so cookies
# from the persistent profile auto-attach.
# ---------------------------------------------------------------------------


def _post_json(page: Any, url: str, body: dict[str, Any]) -> dict[str, Any]:
    resp = page.request.post(
        url,
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": SITE_BASE,
            "Referer": SITE_BASE + "/",
        },
        timeout=30_000,
    )
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text(), "_status": resp.status, "code": -1}


def _search_user(page: Any, name: str) -> list[dict[str, Any]]:
    body = _post_json(page, SEARCH_USER_URL, {
        "user_name": name,
        "next_page_cursor": "",
        "limit": SEARCH_LIMIT,
    })
    if body.get("code") != 0:
        log.warning("SearchUser %r returned code=%s msg=%s",
                    name, body.get("code"), body.get("msg"))
    return ((body.get("data") or {}).get("list")) or []


def _get_game_info(page: Any, intl_openid: str) -> dict[str, Any]:
    body = _post_json(page, GAME_PLAYER_INFO_URL, {"intl_openid": intl_openid})
    if body.get("code") != 0:
        log.warning("GetUserGamePlayerInfo %s returned code=%s",
                    intl_openid, body.get("code"))
        return {}
    return body.get("data") or {}


def search_and_verify_player(
    page: Any,
    name: str,
    expected_level: int,
    *,
    tolerance: int = DEFAULT_LEVEL_TOLERANCE,
) -> MatchResult:
    """Run the SKILL.md search + level-verification flow for one name.

    Returns a MatchResult whose ``status`` is one of:
      - ``"Found"``: NA candidate verified within ``tolerance`` of
        ``expected_level``. ``intl_openid``/``actual_level``/``game_info``
        populated.
      - ``"No Search Results"``: SearchUser returned zero hits.
      - ``"Not On NA"``: search returned hits but none on ``area_id=82``.
      - ``"Level Mismatch"``: NA candidate(s) exist but none within
        tolerance.

    ``found_on_servers`` is the comma-joinable list of server names
    where the exact ``role_name`` appeared (case-insensitive).
    """
    hits = _search_user(page, name)
    if not hits:
        return MatchResult(status="No Search Results", found_on_servers=[])

    upper = name.upper()
    found_servers: list[str] = []
    seen_servers: set[str] = set()
    na_candidates: list[dict[str, Any]] = []
    for h in hits:
        area_id = str(h.get("area_id") or "")
        role_name = (h.get("role_name") or "").upper()
        if role_name != upper:
            continue
        server = SERVER_NAMES.get(area_id, area_id or "?")
        if server not in seen_servers:
            seen_servers.add(server)
            found_servers.append(server)
        if area_id == NA_AREA_ID:
            na_candidates.append(h)

    if not na_candidates:
        # Distinguish "Not On NA" from "No Search Results": we got hits,
        # just not on NA with this exact role_name.
        return MatchResult(
            status="Not On NA",
            found_on_servers=found_servers,
        )

    best: tuple[int, dict[str, Any], dict[str, Any]] | None = None  # (delta, cand, game_info)
    for cand in na_candidates:
        openid = cand.get("intl_openid")
        if not openid:
            continue
        info = _get_game_info(page, openid)
        lv = info.get("player_level")
        if lv is None:
            continue
        delta = abs(int(lv) - int(expected_level))
        if delta <= tolerance and (best is None or delta < best[0]):
            best = (delta, cand, info)

    if best is None:
        return MatchResult(
            status="Level Mismatch",
            found_on_servers=found_servers,
        )

    _, cand, info = best
    return MatchResult(
        status="Found",
        found_on_servers=found_servers,
        intl_openid=cand["intl_openid"],
        actual_level=int(info["player_level"]),
        server="NA",
        game_info=info,
    )


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


def _format_unix_date(epoch_str: Any) -> str:
    """`basic_info.created_at` is a Unix epoch string. Format YYYY-MM-DD."""
    try:
        ts = int(str(epoch_str))
    except (ValueError, TypeError):
        return ""
    if ts <= 0:
        return ""
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).date().isoformat()


def _uid_b64(intl_openid: str) -> str:
    """The base64 string used as both `?uid=` and `?openid=` URL params,
    AND as the positional arg to ``nikkeoptimizer fetch-shiftyspad``."""
    return base64.b64encode(intl_openid.encode()).decode()


def _shiftyspad_url(intl_openid: str) -> str:
    enc = _uid_b64(intl_openid)
    q = quote(enc)
    return f"{SITE_BASE}/shiftyspad/home?uid={q}&openid={q}"


def build_row(
    query: PlayerQuery,
    match: MatchResult,
    home: Optional[HomePayload] = None,
) -> dict[str, Any]:
    """Build one CSV row from the search/verify result + (optional) home payload.

    Non-Found rows skip the home navigation; their roster/outpost
    columns are blank, but ``Found On Servers`` is populated to triage
    why they weren't matched.
    """
    row: dict[str, Any] = {col: "" for col in CSV_COLUMNS}
    row["Player Name"] = query.name
    row["Expected Level"] = query.expected_level
    row["Status"] = match.status
    row["Found On Servers"] = ", ".join(match.found_on_servers) if match.found_on_servers else "—"

    if match.status != "Found":
        row["Worth Fetching"] = "no"
        return row

    assert match.intl_openid is not None
    row["Actual Level"] = match.actual_level
    row["Server"] = match.server or "NA"
    row["UID"] = _uid_b64(match.intl_openid)
    row["Shiftyspad URL"] = _shiftyspad_url(match.intl_openid)

    # GetUserGamePlayerInfo fields — always available for Found rows.
    gi = match.game_info or {}
    row["Towers"] = gi.get("tower_floor", "")
    row["Nikkes Count"] = gi.get("own_nikke_cnt", "")
    row["Squad Power"] = gi.get("team_combat", "")

    if home is None:
        # We can't determine publicness without the home page, so be
        # conservative.
        row["Worth Fetching"] = "unknown"
        return row

    # Roster privacy (My Nikkes status).
    row["My Nikkes Status"] = "Private" if home.is_roster_private else "Public"

    basic = home.basic_info or {}
    if basic:
        # Prefer BasicInfo over GameInfo for the squad/towers fields —
        # they're identical in our observations, but BasicInfo is the
        # underlying source the page renders from.
        row["Towers"] = basic.get("progress_tribe_tower", row["Towers"])
        row["Nikkes Count"] = basic.get("character_count", row["Nikkes Count"])
        row["Squad Power"] = basic.get("team_combat", row["Squad Power"])
        row["Costumes"] = basic.get("character_costume_count", "")
        row["Registration Date"] = _format_unix_date(basic.get("created_at"))
        row["Overclock Mode"] = basic.get("sim_room_overclock_latest_season_high_score", "")

    outpost = home.outpost_info or {}
    # SKILL.md status semantics: Private if research entries carry the
    # privacy sentinel. The other outpost fields stay populated in that
    # case, but per spec we leave the research-level columns blank.
    row["Outpost Info Status"] = "Private" if home.is_outpost_private else "Public"

    if outpost:
        row["Synchro Level"] = outpost.get("synchro_level", "")
        row["BGM"] = outpost.get("jukebox_count", "")
        # Lost Relics — Memoirs/Call Logs/Data come from memorial_counts.
        category_counts = {
            (m.get("category") or ""): m.get("count")
            for m in (outpost.get("memorial_counts") or [])
        }
        for csv_label, api_category in LOST_RELIC_CATEGORY_MAP.items():
            row[csv_label] = category_counts.get(api_category, "")
        # Research levels, only when not redacted.
        if not home.is_outpost_private:
            for entry in outpost.get("recycle_room_researches") or []:
                tid = entry.get("tid")
                lv = entry.get("lv")
                label = RESEARCH_TID_TO_CSV_LABEL.get(int(tid)) if tid is not None else None
                if label:
                    row[label] = lv

    # Worth Fetching = "yes" when EITHER the roster OR outpost is
    # public. Both private = nothing useful for fetch-shiftyspad to
    # pull beyond the blue-card BasicInfo already captured here.
    row["Worth Fetching"] = (
        "yes" if (not home.is_roster_private or not home.is_outpost_private) else "no"
    )
    return row


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class LookupProgress:
    """Per-player progress signal for CLI rendering."""
    index: int
    total: int
    name: str
    status: str


def run_lookup(
    queries: list[PlayerQuery],
    *,
    tolerance: int = DEFAULT_LEVEL_TOLERANCE,
    headless: bool = True,
    fetcher: Optional[ShiftyPadFetcher] = None,
    home_pacing_range: tuple[float, float] = DEFAULT_DETAIL_DELAY_RANGE,
    on_progress: Optional[Any] = None,
    rng: Optional[random.Random] = None,
) -> list[dict[str, Any]]:
    """Run the full SKILL flow for ``queries``, sequentially.

    Each player is processed end-to-end before the next starts (per the
    BlablaLink-scraper behavior memory: sequential, human-paced).

    ``home_pacing_range`` is a uniform random delay applied BETWEEN
    home-page navigations (the search/verify POSTs are not paced, since
    they're cheap and don't fingerprint as a browser session — they're
    standard XHRs from the logged-in tab).
    """
    rng = rng or random.Random()
    rows: list[dict[str, Any]] = []

    with _open_fetcher(fetcher, headless=headless) as f:
        # Warm the origin so cookies are scoped right for cross-host XHRs.
        f._page.goto(SITE_BASE + "/", wait_until="domcontentloaded")
        f._page.wait_for_timeout(1_500)

        last_home_nav = 0.0
        for i, query in enumerate(queries):
            if on_progress is not None:
                on_progress(LookupProgress(
                    index=i, total=len(queries), name=query.name, status="searching"
                ))
            match = search_and_verify_player(
                f._page, query.name, query.expected_level, tolerance=tolerance
            )

            home: Optional[HomePayload] = None
            if match.status == "Found":
                # Pace home navigations like a human browsing profiles.
                if last_home_nav > 0.0:
                    target = rng.uniform(*home_pacing_range)
                    elapsed = time.monotonic() - last_home_nav
                    if elapsed < target:
                        time.sleep(target - elapsed)
                if on_progress is not None:
                    on_progress(LookupProgress(
                        index=i, total=len(queries), name=query.name, status="fetching-home"
                    ))
                uid_b64 = base64.b64encode(match.intl_openid.encode()).decode()
                home = f.fetch_home(uid_b64)
                last_home_nav = time.monotonic()

            row = build_row(query, match, home)
            rows.append(row)
            if on_progress is not None:
                on_progress(LookupProgress(
                    index=i, total=len(queries), name=query.name, status=match.status
                ))

    return rows


@contextmanager
def _open_fetcher(
    fetcher: Optional[ShiftyPadFetcher],
    *,
    headless: bool,
) -> Iterator[ShiftyPadFetcher]:
    if fetcher is not None:
        yield fetcher
        return
    with ShiftyPadFetcher(headless=headless) as f:
        yield f


# ---------------------------------------------------------------------------
# CSV serialization
# ---------------------------------------------------------------------------


def write_csv(rows: list[dict[str, Any]], out_path: "Any") -> None:
    """Write ``rows`` to ``out_path`` in the 31-column CSV.

    Each row is expected to be a dict keyed by CSV_COLUMNS labels;
    missing keys are written as empty strings.
    """
    import csv
    from pathlib import Path
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def default_csv_path(when: Optional[_dt.date] = None) -> "Any":
    """Return ``~/Downloads/nikke_player_lookup_YYYY-MM-DD.csv``."""
    from pathlib import Path
    d = (when or _dt.date.today()).isoformat()
    return Path.home() / "Downloads" / f"nikke_player_lookup_{d}.csv"


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def parse_player_input(text: str) -> list[PlayerQuery]:
    """Parse a flexible input format into PlayerQuery list.

    Accepted shapes (one per line, any of):
      - "Rank,Name,lvl"  (header row tolerated)
      - "Name,lvl"
      - "Name, Lv.XXX"
      - "Name Lv.XXX"
    Blank lines and the literal header row are skipped.
    """
    out: list[PlayerQuery] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        # Skip CSV header rows.
        if low.startswith("rank,") or low.startswith("name,"):
            # Re-check that it's actually a header (contains non-numeric "lvl" column tag)
            if "lvl" in low or "level" in low or "name" in low:
                continue
        # Strip leading rank prefix if present: "1,Agito,817" → "Agito,817"
        parts_csv = [p.strip() for p in line.split(",")]
        if len(parts_csv) == 3 and parts_csv[0].isdigit():
            parts_csv = parts_csv[1:]
        if len(parts_csv) == 2:
            name, lv_str = parts_csv
            lv = _strip_lv_prefix(lv_str)
            if name and lv is not None:
                out.append(PlayerQuery(name=name, expected_level=lv))
                continue
        # Try "Name Lv.XXX" form
        import re as _re
        m = _re.match(r"^(.*?)\s+Lv\.?\s*(\d+)\s*$", line, _re.IGNORECASE)
        if m:
            out.append(PlayerQuery(name=m.group(1).strip(), expected_level=int(m.group(2))))
            continue
        log.warning("skipping unparseable input line: %r", line)
    return out


def _strip_lv_prefix(s: str) -> Optional[int]:
    s = s.strip()
    if not s:
        return None
    if s.lower().startswith("lv."):
        s = s[3:].strip()
    elif s.lower().startswith("lv"):
        s = s[2:].strip()
    try:
        return int(s)
    except ValueError:
        return None
