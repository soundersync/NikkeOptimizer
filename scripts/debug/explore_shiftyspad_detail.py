"""Character detail page sniffer: loads /shiftyspad/nikke?nikke=<rid>,
captures XHRs for the default Equipment tab, then clicks Skill →
Collection → Cube and captures each tab's additional XHRs.

Run from project root:
    PYTHONPATH=src python scripts/debug/explore_shiftyspad_detail.py
    PYTHONPATH=src python scripts/debug/explore_shiftyspad_detail.py 191

The optional positional argument is the character's resource_id (defaults
to 191). Requires a logged-in persistent profile — run login_blablalink.py
first if needed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from nikke_optimizer.data.scrapers.blablalink import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    USER_AGENT,
    default_browser_profile_dir,
)

# Default to the user's own profile (uid/openid from message context).
DEFAULT_RESOURCE_ID = "191"
PROFILE_UID = "MjkwODAtMTIzMzY3MDkyMDA0MjAyMjI1MzQ="
PROFILE_OPENID = "MjkwODAtMTIzMzY3MDkyMDA0MjAyMjI1MzQ="
# skin_index=2 URL: shows the full character card with bond rank, class
# rank, manufacturer rank — and a blue arrow that opens a flat-stat modal.
URL_TEMPLATE = (
    "https://www.blablalink.com/shiftyspad/nikke"
    "?nikke={rid}&skin_index=2&uid={uid}&openid={openid}"
)

OUT_DIR = Path(__file__).resolve().parent / "dumps" / "shiftyspad-detail-dump"
HEADLESS = False

SKIP_EXT = re.compile(
    r"\.(?:js|css|png|jpe?g|gif|webp|svg|woff2?|ttf|otf|ico|mp4|webm|map)(?:\?|$)",
    re.IGNORECASE,
)

# Hosts worth capturing even with non-JSON content-type.
INTEREST_HOSTS = ("blablalink.com", "playerinfinite.com")

# Tabs to click in order after the initial Equipment-default load.
TAB_LABELS = ["Skill", "Collection", "Cube"]


def _safe_slug(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", url)[-180:]


def _summarize(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {
            "type": "list",
            "len": len(payload),
            "sample_keys": (
                sorted(payload[0].keys())[:30]
                if payload and isinstance(payload[0], dict)
                else None
            ),
        }
    if isinstance(payload, dict):
        return {"type": "dict", "keys": sorted(payload.keys())[:30]}
    return {"type": type(payload).__name__}


def main(argv: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    rid = argv[1] if len(argv) > 1 else DEFAULT_RESOURCE_ID
    url = URL_TEMPLATE.format(rid=rid, uid=PROFILE_UID, openid=PROFILE_OPENID)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bodies_dir = OUT_DIR / "bodies"
    if bodies_dir.exists():
        for p in bodies_dir.iterdir():
            p.unlink()
    bodies_dir.mkdir(exist_ok=True)

    # Tag every capture with the active tab so we can attribute XHRs.
    active_tab = {"name": "Equipment"}  # mutable for closure
    captured: list[dict[str, Any]] = []
    request_lines: list[str] = []

    def on_request(req: Any) -> None:
        if SKIP_EXT.search(req.url):
            return
        body = ""
        if req.method != "GET":
            try:
                body = req.post_data or ""
            except Exception:  # noqa: BLE001
                body = "<post_data unavailable>"
        line = f"[{active_tab['name']:11s}] {req.method:6s} {req.url}"
        if body:
            line += f"\n    BODY: {body[:500]}"
        request_lines.append(line)

    def on_response(response: Any) -> None:
        url_ = response.url
        if SKIP_EXT.search(url_):
            return
        ctype = (response.headers.get("content-type") or "").lower()
        on_interest = any(h in url_ for h in INTEREST_HOSTS)
        if not on_interest and "json" not in ctype:
            return
        slug = _safe_slug(url_)
        entry: dict[str, Any] = {
            "tab": active_tab["name"],
            "url": url_,
            "status": response.status,
            "method": response.request.method,
            "content_type": ctype,
        }
        try:
            body = response.body()
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"body: {exc}"
            captured.append(entry)
            return
        try:
            payload = json.loads(body)
            entry["summary"] = _summarize(payload)
            # Prefix with tab so collisions across tabs land in separate files.
            (bodies_dir / f"{active_tab['name']}__{slug}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
            )
        except Exception:  # noqa: BLE001
            entry["summary"] = {"type": "binary", "len": len(body)}
            (bodies_dir / f"{active_tab['name']}__{slug}.bin").write_bytes(body)
        captured.append(entry)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(default_browser_profile_dir()),
            headless=HEADLESS,
            user_agent=USER_AGENT,
            bypass_csp=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT_MS)
        page.on("request", on_request)
        page.on("response", on_response)

        print(f"[*] navigating to {url}")
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] networkidle timed out: {exc}")
        page.wait_for_timeout(2_000)
        print(f"[*] Equipment-tab settle done; captured {len(captured)}")

        # Try to open the bond/rank flat-stats modal. The screenshot shows
        # RANK/Attacker/Tetra labels with a right-arrow button. Try several
        # selectors — whichever sticks fires the XHR we're after.
        active_tab["name"] = "RankModal"
        rank_clicked = False
        rank_candidates = [
            lambda: page.get_by_text("RANK", exact=True).first,
            lambda: page.locator('text="Attacker"').first,
            lambda: page.locator('text="Tetra"').first,
            lambda: page.locator('text="Pilgrim"').first,
            lambda: page.locator('text="Elysion"').first,
            lambda: page.locator('text="Missilis"').first,
            lambda: page.locator('text="Abnormal"').first,
            lambda: page.locator('text="Defender"').first,
            lambda: page.locator('text="Supporter"').first,
            # Generic blue-arrow / chevron buttons.
            lambda: page.locator('button:has(svg)').nth(0),
        ]
        for i, mk in enumerate(rank_candidates):
            try:
                loc = mk()
                loc.scroll_into_view_if_needed(timeout=2_000)
                loc.click(timeout=2_000)
                print(f"[*] rank candidate #{i} clicked")
                rank_clicked = True
                page.wait_for_timeout(2_500)
                break
            except Exception:  # noqa: BLE001
                continue
        if not rank_clicked:
            print("[!] could not click any rank-modal trigger")
        else:
            print(f"[*] RankModal settle; running total {len(captured)}")

        for label in TAB_LABELS:
            print(f"[*] clicking '{label}' tab")
            active_tab["name"] = label
            clicked = False
            for locator in (
                page.get_by_role("tab", name=label),
                page.get_by_text(label, exact=True),
            ):
                try:
                    first = locator.first
                    first.scroll_into_view_if_needed(timeout=3_000)
                    first.click(timeout=3_000)
                    clicked = True
                    break
                except Exception:  # noqa: BLE001
                    continue
            if not clicked:
                print(f"[!] could not find tab '{label}'")
                continue
            # Let the tab's XHRs fire and settle.
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(3_000)
            print(f"[*] '{label}' settle done; running total {len(captured)}")

        # Final settle in case lazy fetches haven't completed.
        page.wait_for_timeout(2_000)

        html_path = OUT_DIR / "rendered.html"
        html_path.write_text(page.content())
        page.screenshot(path=str(OUT_DIR / "screenshot.png"), full_page=True)
        ctx.close()

    (OUT_DIR / "request_log.txt").write_text("\n".join(request_lines))
    (OUT_DIR / "index.json").write_text(json.dumps(captured, ensure_ascii=False, indent=2))

    print()
    print(f"[*] {len(request_lines)} requests logged")
    print(f"[*] {len(captured)} bodies captured")
    print()
    # Print only POST/GET to api.blablalink.com (the interesting stuff).
    for entry in captured:
        u = entry["url"]
        if "api.blablalink.com" not in u:
            continue
        s = entry.get("summary", {})
        if s.get("type") == "list":
            tail = f"list[{s['len']}]"
        elif s.get("type") == "dict":
            tail = f"dict keys={s.get('keys')}"
        else:
            tail = s.get("type", "?")
        # Strip the long prefix for readability.
        short = u.replace("https://api.blablalink.com/api/", "")
        print(f"  [{entry['tab']:11s}] {entry['method']:5s} {short[:100]}  →  {tail}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
