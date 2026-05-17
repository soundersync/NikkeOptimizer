"""Hunt for the option_id → percent table.

Strategy: navigate to a Nikke detail page, then try to click into each
of the 4 gear pieces. The "Change Equipment Effects" panel that opens
must render exact percent values per option_id — so it should fetch
the canonical table.

We also click around the Equipment tab elements to see if anything
provokes new XHRs we haven't captured.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from nikke_optimizer.data.scrapers.shiftyspad import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    USER_AGENT,
    default_browser_profile_dir,
)

# The user's own profile.
UID = "MjkwODAtNDI4NzIxMDMzMjEzMzYzNzkwOQ=="
# Biscuit (name_code=5054, resource_id=381) — she has full gear with option_ids.
RESOURCE_ID = 381

URL = (
    f"https://www.blablalink.com/shiftyspad/nikke"
    f"?nikke={RESOURCE_ID}&skin_index=2&uid={UID}&openid={UID}"
)

OUT_DIR = Path(__file__).resolve().parent / "dumps" / "option-hunt"

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

    phase = {"name": "load"}
    captures: dict[str, list[str]] = {}
    requests_log: list[str] = []

    def on_request(req: Any) -> None:
        if SKIP_EXT.search(req.url):
            return
        body = ""
        if req.method != "GET":
            try:
                body = req.post_data or ""
            except Exception:
                body = ""
        line = f"[{phase['name']:18s}] {req.method:6s} {req.url}"
        if body:
            line += f"\n    BODY: {body[:300]}"
        requests_log.append(line)

    def on_response(resp: Any) -> None:
        url = resp.url
        if SKIP_EXT.search(url):
            return
        # All JSON-ish responses from CDN OR API.
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" not in ctype and not url.endswith(".json"):
            return
        try:
            payload = resp.json()
        except Exception:
            return
        # Persist
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", url)[-160:]
        path = bodies_dir / f"{phase['name']}__{slug}.json"
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError:
            return
        captures.setdefault(phase["name"], []).append(url)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(default_browser_profile_dir()),
            headless=False,  # so we can see what's happening
            user_agent=USER_AGENT,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT_MS)
        page.on("request", on_request)
        page.on("response", on_response)

        print(f"[*] navigating to {URL}")
        page.goto(URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(3_000)
        baseline = sum(len(v) for v in captures.values())
        print(f"[*] baseline captures: {baseline}")

        # Try clicking each gear piece. The Equipment tab is the default
        # for skin_index=2. Each piece is a card with the gear icon —
        # they might respond to click with a modal containing the option
        # detail.
        page.screenshot(path=str(OUT_DIR / "baseline.png"), full_page=True)

        # Find all elements that look like gear cards. We'll try several
        # locator strategies and click whichever first.
        click_attempts = [
            ('text="Change Equipment Effects"', None),
            ('text="Equipment Stats"', None),
            ('button:has-text("Change")', None),
            # Gear thumbnails: BlablaLink uses divs with bg images. Try by role.
            ('[role="button"]:has(img)', "nth=0"),
            ('div[class*="card"]:has(img)', "nth=0"),
        ]
        for selector, mod in click_attempts:
            try:
                loc = page.locator(selector)
                if mod and mod.startswith("nth="):
                    loc = loc.nth(int(mod.split("=")[1]))
                else:
                    loc = loc.first
                phase["name"] = f"click_{selector[:15]}"
                print(f"[*] phase: {phase['name']} — trying {selector!r}")
                loc.scroll_into_view_if_needed(timeout=2_000)
                loc.click(timeout=2_000)
                page.wait_for_timeout(2_500)
                print(f"    captures after: {sum(len(v) for v in captures.values())}")
            except Exception as exc:
                print(f"    failed: {exc}")
                continue

        # Try also: navigate to the "Skill" tab + "Collection" tab + "Cube" tab,
        # since they might fire different XHRs that load related tables.
        for tab_name in ("Skill", "Collection", "Cube"):
            try:
                phase["name"] = f"tab_{tab_name}"
                print(f"[*] phase: {phase['name']}")
                t = page.get_by_text(tab_name, exact=True).first
                t.scroll_into_view_if_needed(timeout=3_000)
                t.click(timeout=3_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                page.wait_for_timeout(2_500)
                print(f"    captures after: {sum(len(v) for v in captures.values())}")
            except Exception as exc:
                print(f"    {tab_name} click failed: {exc}")

        page.screenshot(path=str(OUT_DIR / "final.png"), full_page=True)
        ctx.close()

    (OUT_DIR / "requests.txt").write_text("\n".join(requests_log))
    (OUT_DIR / "captures_by_phase.json").write_text(
        json.dumps(captures, ensure_ascii=False, indent=2)
    )

    print()
    print("=" * 80)
    print("captures per phase:")
    for phase_name, urls in captures.items():
        print(f"  {phase_name}: {len(urls)}")
    print()
    print("New URLs (not seen in load):")
    load_urls = set(captures.get("load", []))
    for phase_name, urls in captures.items():
        if phase_name == "load":
            continue
        for u in urls:
            if u not in load_urls:
                print(f"  [{phase_name}] {u[:160]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
