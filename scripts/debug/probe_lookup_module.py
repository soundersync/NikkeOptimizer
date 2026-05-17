"""Smoke-test the blablalink_user_lookup module on Agito + Royalvio.

Verifies the full flow end-to-end (search → verify level → home XHR →
build CSV row) and prints each row.
"""

from __future__ import annotations

import json
import sys

from nikke_optimizer.data.scrapers.blablalink_user_lookup import (
    CSV_COLUMNS,
    PlayerQuery,
    run_lookup,
    write_csv,
)


def main() -> int:
    queries = [
        PlayerQuery(name="Agito", expected_level=817),
        PlayerQuery(name="Royalvio", expected_level=653),
    ]

    def progress(p):
        print(f"[{p.index+1}/{p.total}] {p.name}: {p.status}")

    rows = run_lookup(queries, headless=True, on_progress=progress)

    print("\n--- ROWS ---")
    for row in rows:
        print(json.dumps(row, indent=2, ensure_ascii=False))

    out = "/tmp/nikke_lookup_smoke.csv"
    write_csv(rows, out)
    print(f"\nWrote {out}")
    print(f"columns: {len(CSV_COLUMNS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
