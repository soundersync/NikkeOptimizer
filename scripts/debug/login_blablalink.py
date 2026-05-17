"""Open BlablaLink in a non-headless Chromium pointed at the persistent
profile that the scraper uses. Lets the user log in manually; auth state
(cookies + localStorage + sessionStorage) lands in the profile dir so
subsequent scrapes run authenticated.

Run from project root:
    PYTHONPATH=src python scripts/debug/login_blablalink.py

Steps in the opened browser:
  1. Click any "Log in" / "Sign in" affordance and authenticate.
  2. Navigate to your own ShiftyPad profile — confirm "My Nikkes" now
     renders content instead of the privacy notice.
  3. In a separate terminal (or via Claude Code Bash), run:
         touch /tmp/blablalink-login-done
     The script polls for that file once per second and shuts down
     cleanly when it appears.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from nikke_optimizer.data.scrapers.blablalink import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    USER_AGENT,
    default_browser_profile_dir,
)

START_URL = "https://www.blablalink.com/"
SENTINEL = Path("/tmp/blablalink-login-done")
DUMP_DIR = Path(__file__).resolve().parent / "dumps" / "shiftyspad-dump"
MAX_WAIT_SECONDS = 30 * 60  # 30 minutes; plenty for a manual login


def main() -> int:
    from playwright.sync_api import sync_playwright

    # Clean any stale sentinel from a previous run.
    if SENTINEL.exists():
        SENTINEL.unlink()
    DUMP_DIR.mkdir(parents=True, exist_ok=True)

    profile = default_browser_profile_dir()
    print(f"[*] persistent profile: {profile}")
    print(f"[*] opening {START_URL}")
    print(f"[*] when done logging in, run:  touch {SENTINEL}")
    print(f"[*] (script polls for that file; max wait {MAX_WAIT_SECONDS // 60} min)")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            user_agent=USER_AGENT,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT_MS)
        page.goto(START_URL, wait_until="domcontentloaded")

        deadline = time.monotonic() + MAX_WAIT_SECONDS
        while time.monotonic() < deadline:
            if SENTINEL.exists():
                print(f"[*] sentinel detected — capturing state and closing.")
                break
            time.sleep(1.0)
        else:
            print("[!] timed out waiting for sentinel; capturing state anyway.")

        # Capture full auth state.
        cookies = ctx.cookies()
        bla_cookies = [c for c in cookies if "blablalink" in c.get("domain", "")]
        print(f"[*] {len(cookies)} cookies total, {len(bla_cookies)} on blablalink domain")
        for c in bla_cookies:
            print(f"    {c['domain']:30s}  {c['name']}")

        # Dump localStorage / sessionStorage for every open page.
        storage_snapshot = []
        for p in ctx.pages:
            try:
                local = p.evaluate(
                    "() => Object.fromEntries(Object.entries(window.localStorage))"
                )
                session = p.evaluate(
                    "() => Object.fromEntries(Object.entries(window.sessionStorage))"
                )
                storage_snapshot.append(
                    {"url": p.url, "localStorage": local, "sessionStorage": session}
                )
            except Exception as exc:  # noqa: BLE001
                storage_snapshot.append({"url": p.url, "error": str(exc)})

        out_path = DUMP_DIR / "auth_state.json"
        out_path.write_text(
            json.dumps(
                {"cookies": cookies, "storage": storage_snapshot},
                ensure_ascii=False,
                indent=2,
            )
        )
        print(f"[*] full auth state dumped to {out_path}")

        # Quick sanity hint: count plausibly-auth-shaped storage keys.
        auth_keyish = 0
        for snap in storage_snapshot:
            for store in ("localStorage", "sessionStorage"):
                for k in (snap.get(store) or {}):
                    kl = k.lower()
                    if any(t in kl for t in ("token", "auth", "uid", "openid", "user", "session")):
                        auth_keyish += 1
        print(f"[*] storage entries with auth-ish key names: {auth_keyish}")

        # Clean up the sentinel.
        if SENTINEL.exists():
            SENTINEL.unlink()

        ctx.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
