"""Fetch detail responses for known-unsynced (K, Jill) vs known-synced
characters and diff every field. Goal: find an attribute that
distinguishes "actually level 1" from "stored as 1 but displayed at
synced cap" — i.e., a slot-membership or effective-level signal.

Run from project root (must already be logged in):
    PYTHONPATH=src python scripts/debug/compare_lv_responses.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from nikke_optimizer.data.scrapers.shiftyspad import ShiftyPadFetcher
from nikke_optimizer.roster.shiftyspad_importer import NameCodeIndex

URL_UID = "MjkwODAtNDI4NzIxMDMzMjEzMzYzNzkwOQ=="

# A mix: 2 unsynced (real level 1) + 2 in-sync (display 655 but possibly stored
# at some lower level). Picking from the validation output:
#   - K: user says real level 1
#   - Jill: user says real level 1
#   - Biscuit: showed 654 → 1 diff, user said this is actually synced at 655
#   - A2: showed 654 → 200 diff, user said this is actually synced at 655
TARGET_NAMES = ["K", "Jill", "Biscuit", "A2"]

OUT_DIR = Path(__file__).resolve().parent / "dumps" / "lv-comparison"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    idx = NameCodeIndex.from_mirror()
    rev = {v.lower(): k for k, v in idx.name_code_to_name.items()}

    target_codes: list[tuple[str, int, int]] = []
    for name in TARGET_NAMES:
        # Handle collab fuzzy: try plain name first, then known full names
        code = rev.get(name.lower())
        if code is None:
            # Fuzzy fallback for known collab forms
            for full_name, c in rev.items():
                if full_name.startswith(name.lower() + " "):
                    code = c
                    print(f"[*] fuzzy: {name} → {idx.name_code_to_name[c]}")
                    break
        if code is None:
            print(f"[!] no name_code for {name!r}")
            continue
        target_codes.append((name, code, idx.name_code_to_resource_id[code]))

    print(f"[*] fetching details for: {target_codes}")
    details: dict[str, dict] = {}
    with ShiftyPadFetcher(headless=True) as f:
        for name, code, rid in target_codes:
            print(f"[*] fetching {name} (name_code={code}, resource_id={rid})")
            result = f.fetch_character_detail(URL_UID, rid)
            if result.detail is not None:
                details[name] = result.detail
                (OUT_DIR / f"{name.replace(' ', '_')}.json").write_text(
                    json.dumps(result.detail, ensure_ascii=False, indent=2)
                )
            else:
                print(f"[!] {name} returned no detail (private={result.is_private})")

    # Side-by-side comparison: every key, value per character.
    print()
    print("=" * 80)
    print(f"{'field':<35s} " + "  ".join(f"{n:>15s}" for n in details))
    print("-" * 80)
    all_keys = sorted({k for d in details.values() for k in d.keys()})
    for key in all_keys:
        row = f"{key:<35s} " + "  ".join(
            f"{repr(d.get(key))[:15]:>15s}" for d in details.values()
        )
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
