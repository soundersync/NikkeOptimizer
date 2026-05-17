"""Sequential, paced probe of additional ShiftyPad pages to discover
endpoints we haven't seen yet. Captures every API XHR per-page and
prints a per-page summary so we can pick up:

  - Champions Arena loadouts
  - Arena/PvP match history
  - Synchro device (slot membership)
  - Privacy settings

Realistic delay between page navigations to look like a user browsing
through their profile.
"""

from __future__ import annotations

import json
import random
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

UID = "MjkwODAtNDI4NzIxMDMzMjEzMzYzNzkwOQ=="

# Pages to probe. Names are best-guess based on common ShiftyPad URL shapes
# observed in the JS bundle; we'll see which 404 and which load fresh.
PAGE_TARGETS = [
    ("home",         f"https://www.blablalink.com/shiftyspad/home?uid={UID}&openid={UID}"),
    ("champion",     f"https://www.blablalink.com/shiftyspad/champion?uid={UID}&openid={UID}"),
    ("history",      f"https://www.blablalink.com/shiftyspad/history?uid={UID}&openid={UID}"),
    ("synchro",      f"https://www.blablalink.com/shiftyspad/synchro?uid={UID}&openid={UID}"),
    ("settings",     f"https://www.blablalink.com/shiftyspad/setting?uid={UID}&openid={UID}"),
]

PAGE_DELAY_RANGE = (4.0, 8.0)
OUT_DIR = Path(__file__).resolve().parent / "dumps" / "page-probe"

SKIP_EXT = re.compile(
    r"\.(?:js|css|png|jpe?g|gif|webp|svg|woff2?|ttf|otf|ico|mp4|webm|map)(?:\?|$)",
    re.IGNORECASE,
)


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bodies_dir = OUT_DIR / "bodies"
    if bodies_dir.exists():
        for p in bodies_dir.iterdir():
            p.unlink()
    bodies_dir.mkdir(exist_ok=True)
    rng = random.Random(42)

    page_state = {"name": "init"}
    captures: list[dict[str, Any]] = []
    requests_seen: list[str] = []

    def on_request(req: Any) -> None:
        if SKIP_EXT.search(req.url):
            return
        body = ""
        if req.method != "GET":
            try:
                body = req.post_data or ""
            except Exception:
                body = "<n/a>"
        line = f"[{page_state['name']:11s}] {req.method:6s} {req.url}"
        if body:
            line += f"\n    BODY: {body[:300]}"
        requests_seen.append(line)

    def on_response(resp: Any) -> None:
        url = resp.url
        if SKIP_EXT.search(url):
            return
        if "api.blablalink.com/api/" not in url and "playerinfinite" not in url:
            return
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" not in ctype:
            return
        try:
            payload = resp.json()
        except Exception:
            return
        # Trim endpoint name for display.
        short = url.replace("https://api.blablalink.com/api/", "")
        capture = {
            "page": page_state["name"],
            "url": short[:140],
            "status": resp.status,
            "method": resp.request.method,
        }
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                capture["data_keys"] = sorted(data.keys())[:15]
            elif isinstance(data, list):
                capture["data_kind"] = f"list[{len(data)}]"
            capture["code"] = payload.get("code")
            capture["msg"] = payload.get("msg")
        captures.append(capture)
        # Persist body — slugged by page + endpoint last token
        slug = (page_state["name"] + "__" + re.sub(r"[^a-zA-Z0-9._-]+", "_", short))[-180:]
        try:
            (bodies_dir / f"{slug}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
            )
        except OSError:
            pass

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(default_browser_profile_dir()),
            headless=True,
            user_agent=USER_AGENT,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT_MS)
        page.on("request", on_request)
        page.on("response", on_response)

        last_t = 0.0
        for i, (name, url) in enumerate(PAGE_TARGETS):
            if last_t:
                wait = rng.uniform(*PAGE_DELAY_RANGE)
                gap = time.monotonic() - last_t
                if gap < wait:
                    time.sleep(wait - gap)
            page_state["name"] = name
            print(f"\n[*] ({i + 1}/{len(PAGE_TARGETS)}) {name}: {url}")
            try:
                resp = page.goto(url, wait_until="domcontentloaded")
                print(f"    → HTTP {resp.status if resp else '?'}")
            except Exception as exc:
                print(f"    nav failed: {exc}")
                last_t = time.monotonic()
                continue
            try:
                page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            last_t = time.monotonic()

        page.screenshot(path=str(OUT_DIR / "last.png"), full_page=True)
        ctx.close()

    (OUT_DIR / "requests.txt").write_text("\n".join(requests_seen))
    (OUT_DIR / "captures.json").write_text(json.dumps(captures, indent=2))

    print()
    print("=" * 80)
    print(f"captured {len(captures)} api/playerinfinite responses across {len(PAGE_TARGETS)} pages")
    print()
    by_page: dict[str, list[dict]] = {}
    for c in captures:
        by_page.setdefault(c["page"], []).append(c)
    for name in [n for n, _ in PAGE_TARGETS]:
        entries = by_page.get(name, [])
        # Endpoints unique to this page (relative to home)
        home_urls = {c["url"] for c in by_page.get("home", [])}
        new_only = [c for c in entries if c["url"] not in home_urls]
        print(f"=== {name} ({len(entries)} total, {len(new_only)} not on home) ===")
        for c in new_only:
            tag = ""
            if c.get("code") and c["code"] != 0:
                tag = f"  ⚠ code={c['code']} msg={c.get('msg')!r}"
            print(f"  {c['method']:5s} {c['url'][:100]}{tag}")
            if "data_keys" in c:
                print(f"      data keys: {c['data_keys']}")
            elif "data_kind" in c:
                print(f"      {c['data_kind']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
