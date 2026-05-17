"""Phase A probe — exercise the SKILL.md flow for Agito + Royalvio.

Goal: understand the JSON response shapes from
``api.blablalink.com/api/ugc/direct/standalonesite/User/SearchUser`` and
``.../User/GetUserGamePlayerInfo`` so we can build a typed Python
scraper instead of the JS-extension flow that regex-parses
``document.body.innerText``.

For each test player we:
  1. POST SearchUser with limit=50.
  2. Filter to NA candidates (area_id == "82") whose role_name matches
     case-insensitively, then GetUserGamePlayerInfo per candidate to
     compare player_level against the expected level.
  3. Navigate to /shiftyspad/home for the chosen openid, capture every
     api.blablalink.com XHR response, and dump them all.

Dumps land in scripts/debug/dumps/user-lookup/ which is gitignored.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from nikke_optimizer.data.scrapers.shiftyspad import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    USER_AGENT,
    default_browser_profile_dir,
)

API_BASE_STANDALONE = "https://api.blablalink.com/api/ugc/direct/standalonesite"
SEARCH_URL = f"{API_BASE_STANDALONE}/User/SearchUser"
GAME_INFO_URL = f"{API_BASE_STANDALONE}/User/GetUserGamePlayerInfo"
SITE_BASE = "https://www.blablalink.com"

TEST_PLAYERS = [
    ("Agito", 817),
    ("Royalvio", 653),
]

NA_AREA_ID = "82"
SERVER_NAMES = {
    "81": "Japan",
    "82": "NA",
    "84": "Global",
    "85": "SEA",
    "91": "HMT",
    "": "(no game account)",
}

OUT_DIR = Path(__file__).resolve().parent / "dumps" / "user-lookup"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _post_json(page: Any, url: str, body: dict[str, Any]) -> dict[str, Any]:
    """page.request.post with credentials (cookies auto-attached)."""
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
    text = resp.text()
    try:
        return resp.json()
    except Exception:
        return {"_raw": text, "_status": resp.status}


def search_user(page: Any, name: str) -> dict[str, Any]:
    return _post_json(page, SEARCH_URL, {"user_name": name, "next_page_cursor": "", "limit": 50})


def get_game_info(page: Any, intl_openid: str) -> dict[str, Any]:
    return _post_json(page, GAME_INFO_URL, {"intl_openid": intl_openid})


SKIP_EXT = re.compile(
    r"\.(?:js|css|png|jpe?g|gif|webp|svg|woff2?|ttf|otf|ico|mp4|webm|map)(?:\?|$)",
    re.IGNORECASE,
)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. pip install -e '.[scrape]' && playwright install chromium")
        return 1

    profile = default_browser_profile_dir()
    print(f"[probe] profile: {profile}")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=True,
            user_agent=USER_AGENT,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT_MS)

        # Warm the origin so cookies are scoped right for cross-host XHRs.
        page.goto(SITE_BASE + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(1_500)

        summary: dict[str, Any] = {}

        for name, expected_lv in TEST_PLAYERS:
            print(f"\n[probe] === {name} (expected Lv.{expected_lv}) ===")
            search = search_user(page, name)
            search_path = OUT_DIR / f"search_{name}.json"
            search_path.write_text(json.dumps(search, indent=2, ensure_ascii=False))
            print(f"[probe]   search dumped → {search_path}")

            hits = ((search.get("data") or {}).get("list")) or []
            print(f"[probe]   total hits: {len(hits)}")
            # Group by area_id
            by_area: dict[str, list[dict[str, Any]]] = {}
            for h in hits:
                by_area.setdefault(str(h.get("area_id", "")), []).append(h)
            print("[probe]   by area:", {SERVER_NAMES.get(k, k): len(v) for k, v in by_area.items()})

            # Exact role_name matches by server (case-insensitive)
            matching_servers = []
            for area_id, group in by_area.items():
                if any((u.get("role_name") or "").upper() == name.upper() for u in group):
                    matching_servers.append(SERVER_NAMES.get(area_id, area_id))
            print(f"[probe]   exact role_name on: {matching_servers}")

            na_candidates = [
                u for u in hits
                if str(u.get("area_id")) == NA_AREA_ID
                and (u.get("role_name") or "").upper() == name.upper()
            ]
            print(f"[probe]   NA exact-role candidates: {len(na_candidates)}")
            for i, c in enumerate(na_candidates):
                # Compact view of the search hit shape
                print(f"[probe]     [{i}] keys: {sorted(c.keys())}")

            # Verify level for each NA candidate
            chosen = None
            for cand in na_candidates:
                openid = cand.get("intl_openid")
                if not openid:
                    continue
                info = get_game_info(page, openid)
                info_path = OUT_DIR / f"gameinfo_{name}_{openid}.json"
                info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False))
                player_level = ((info.get("data") or {}).get("player_level"))
                print(f"[probe]     openid={openid}  player_level={player_level}  → {info_path.name}")
                if player_level is not None and abs(int(player_level) - expected_lv) <= 15:
                    chosen = (cand, info)

            if chosen is None:
                print("[probe]   no level-tolerance match within ±15")
                summary[name] = {"status": "no-match"}
                continue
            cand, info = chosen
            openid = cand["intl_openid"]
            data = info.get("data") or {}
            print(f"[probe]   CHOSEN openid={openid}")
            print(f"[probe]   game info top-level keys: {sorted(data.keys())}")
            summary[name] = {
                "openid": openid,
                "player_level": data.get("player_level"),
                "game_info_keys": sorted(data.keys()),
            }

            # ----- ShiftyPad home page navigation -----
            # Capture every api.blablalink.com response.
            captures: list[dict[str, Any]] = []

            def on_response(resp: Any) -> None:
                url = resp.url
                if SKIP_EXT.search(url):
                    return
                if "api.blablalink.com" not in url:
                    return
                try:
                    body = resp.json()
                except Exception:
                    try:
                        body = {"_text": resp.text()[:500]}
                    except Exception:
                        body = {"_unreadable": True}
                captures.append({"url": url, "status": resp.status, "body": body})

            page.on("response", on_response)
            try:
                import base64
                # intl_openid is already in the form "<area_game_id>-<openid>"
                # (e.g. "29080-6847917515021771940"). Don't prefix again.
                uid_b64 = base64.b64encode(openid.encode()).decode()
                from urllib.parse import quote
                home_url = (
                    f"{SITE_BASE}/shiftyspad/home"
                    f"?uid={quote(uid_b64)}&openid={quote(uid_b64)}"
                )
                print(f"[probe]   navigating → {home_url}")
                page.goto(home_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass
                page.wait_for_timeout(3_000)
            finally:
                page.remove_listener("response", on_response)

            home_path = OUT_DIR / f"home_xhrs_{name}.json"
            home_path.write_text(json.dumps(captures, indent=2, ensure_ascii=False))
            print(f"[probe]   home XHRs ({len(captures)}) dumped → {home_path}")
            # Show distinct endpoint suffixes
            suffixes = sorted({
                c["url"].split("/api/", 1)[-1].split("?", 1)[0]
                for c in captures
            })
            print("[probe]   distinct endpoints:")
            for s in suffixes:
                print(f"[probe]     - {s}")

            # Pace between players
            time.sleep(2.5)

        (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\n[probe] summary → {OUT_DIR / 'summary.json'}")

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
