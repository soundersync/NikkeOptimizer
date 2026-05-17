"""Aggressive XHR sniff: load shiftyspad profile, log every request,
capture every response body, click the My Nikkes tab if present, wait
long enough for lazy fetches.

Run from project root:
    PYTHONPATH=src python scripts/debug/explore_shiftyspad.py
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

URL = (
    "https://www.blablalink.com/shiftyspad/home"
    "?uid=MjkwODAtMzkzMDgwOTM5MjUyMDI1MzkzOA=="
    "&openid=MjkwODAtMzkzMDgwOTM5MjUyMDI1MzkzOA=="
)
OUT_DIR = Path(__file__).resolve().parent / "dumps" / "shiftyspad-dump"
HEADLESS = False

# Skip static asset chatter; we want API-ish traffic.
SKIP_EXT = re.compile(
    r"\.(?:js|css|png|jpe?g|gif|webp|svg|woff2?|ttf|otf|ico|mp4|webm|map)(?:\?|$)",
    re.IGNORECASE,
)

# Hosts that almost certainly carry player/profile data on BlablaLink.
INTEREST_HOSTS = ("blablalink.com", "playerinfinite.com")


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


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bodies_dir = OUT_DIR / "bodies"
    # Wipe previous run to make diffs easy.
    if bodies_dir.exists():
        for p in bodies_dir.iterdir():
            p.unlink()
    bodies_dir.mkdir(exist_ok=True)
    request_log_path = OUT_DIR / "request_log.txt"
    request_log_path.write_text("")  # truncate

    request_lines: list[str] = []

    def on_request(req: Any) -> None:
        if SKIP_EXT.search(req.url):
            return
        line = f"{req.method:6s}  {req.url}"
        request_lines.append(line)

    captured: list[dict[str, Any]] = []

    def on_response(response: Any) -> None:
        url = response.url
        if SKIP_EXT.search(url):
            return
        # Always grab anything on interesting hosts; otherwise filter by content-type.
        ctype = (response.headers.get("content-type") or "").lower()
        on_interest_host = any(h in url for h in INTEREST_HOSTS)
        if not on_interest_host and "json" not in ctype:
            return

        slug = _safe_slug(url)
        entry: dict[str, Any] = {
            "url": url,
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

        # Try JSON first; if it parses, dump pretty. Otherwise dump raw.
        try:
            payload = json.loads(body)
            entry["summary"] = _summarize(payload)
            (bodies_dir / f"{slug}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
            )
        except Exception:  # noqa: BLE001
            entry["summary"] = {"type": "binary", "len": len(body)}
            (bodies_dir / f"{slug}.bin").write_bytes(body)
        captured.append(entry)

    with sync_playwright() as pw:
        # Trust the persistent profile to hold cookies + localStorage from
        # the login session. No cache busting; no manual auth injection.
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

        print(f"[*] navigating to {URL}")
        page.goto(URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] networkidle timed out: {exc}")
        page.wait_for_timeout(2_000)

        # Try to click the "My Nikkes" tab if it exists.
        try:
            tab = page.get_by_text("My Nikkes", exact=True).first
            tab.scroll_into_view_if_needed(timeout=5_000)
            tab.click(timeout=5_000)
            print("[*] clicked 'My Nikkes'")
        except Exception as exc:  # noqa: BLE001
            print(f"[!] couldn't click 'My Nikkes' tab: {exc}")

        # Wait + scroll to provoke any lazy loads / paginated fetches.
        for i in range(6):
            page.wait_for_timeout(2_500)
            try:
                page.mouse.wheel(0, 1500)
            except Exception:  # noqa: BLE001
                pass
            print(f"[*] tick {i + 1} — captured so far: {len(captured)}")

        # Final settle.
        page.wait_for_timeout(3_000)

        html_path = OUT_DIR / "rendered.html"
        html_path.write_text(page.content())
        page.screenshot(path=str(OUT_DIR / "screenshot.png"), full_page=True)
        ctx.close()

    request_log_path.write_text("\n".join(request_lines))
    index_path = OUT_DIR / "index.json"
    index_path.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    print(f"\n[*] {len(request_lines)} non-asset requests logged → {request_log_path}")
    print(f"[*] {len(captured)} response bodies captured → {index_path}")
    print()
    # Show the captures sorted by host, hide the noisy CDN char-data files
    for entry in captured:
        url = entry["url"]
        if "sg-tools-cdn.blablalink.com" in url:
            continue  # known character DB files
        s = entry.get("summary", {})
        if s.get("type") == "list":
            tail = f"list[{s['len']}] keys={s.get('sample_keys')}"
        elif s.get("type") == "dict":
            tail = f"dict keys={s.get('keys')}"
        elif s.get("type") == "binary":
            tail = f"binary {s['len']}B"
        else:
            tail = entry.get("error", s.get("type", "?"))
        print(f"  {entry.get('status', '?')} {entry['method']:5s} {url[:140]}  →  {tail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
