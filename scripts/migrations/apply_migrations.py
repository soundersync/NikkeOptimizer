"""Idempotent migration runner — applies each ``NNNN_*.sql`` file in
this directory to BOTH known databases (user data dir + tests dir).

Detects ALTER TABLE ADD COLUMN statements and skips them when the
column already exists. CREATE INDEX statements use ``IF NOT EXISTS``
in the SQL itself, so they're naturally idempotent.

Per the [dual_db_alter_pattern] memory: schema changes always need to
land on both DBs.

Usage:
    PYTHONPATH=src python scripts/migrations/apply_migrations.py
    PYTHONPATH=src python scripts/migrations/apply_migrations.py --dry-run
    PYTHONPATH=src python scripts/migrations/apply_migrations.py --only 0001
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

DEFAULT_DBS = [
    Path.home() / "Library/Application Support/NikkeOptimizer/nikke_optimizer.sqlite3",
    Path("/tmp/nikke_test.sqlite3"),
]

MIGRATIONS_DIR = Path(__file__).resolve().parent

_ALTER_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
    re.IGNORECASE,
)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _split_statements(sql: str) -> list[str]:
    """Split a SQL file into statements, stripping `-- ...` line comments."""
    cleaned = "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def apply_migration(
    db: Path, sql_file: Path, *, dry_run: bool = False
) -> dict[str, int]:
    counts = {"applied": 0, "skipped_existing": 0, "errors": 0}
    if not db.is_file():
        print(f"  [yellow]db not found:[/] {db} — skipping")
        return counts
    sql = sql_file.read_text()
    conn = sqlite3.connect(db)
    try:
        for stmt in _split_statements(sql):
            m = _ALTER_ADD_COLUMN.search(stmt)
            if m:
                table, column = m.group(1), m.group(2)
                if column in _table_columns(conn, table):
                    print(f"  - {table}.{column} already exists; skip")
                    counts["skipped_existing"] += 1
                    continue
            try:
                if dry_run:
                    print(f"  WOULD RUN: {stmt[:80]}{'...' if len(stmt) > 80 else ''}")
                else:
                    conn.execute(stmt)
                    print(f"  + {stmt[:80]}{'...' if len(stmt) > 80 else ''}")
                counts["applied"] += 1
            except sqlite3.Error as exc:
                # IF NOT EXISTS indexes shouldn't fail; columns we handle above.
                # Anything else is real.
                print(f"  [red]ERROR on `{stmt[:60]}...`:[/] {exc}")
                counts["errors"] += 1
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return counts


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Only apply migrations matching this prefix (e.g. 0001)")
    ap.add_argument(
        "--db", action="append",
        help="Override DB path (repeatable). Default: user_data_dir DB + /tmp/nikke_test.sqlite3.",
    )
    args = ap.parse_args(argv)

    dbs = [Path(p) for p in args.db] if args.db else DEFAULT_DBS
    sql_files = sorted(MIGRATIONS_DIR.glob("[0-9]*_*.sql"))
    if args.only:
        sql_files = [f for f in sql_files if f.name.startswith(args.only)]
    if not sql_files:
        print("No migrations to run.")
        return 0

    overall = {"applied": 0, "skipped_existing": 0, "errors": 0}
    for db in dbs:
        print(f"\n== {db} ==")
        for sql_file in sql_files:
            print(f"  -- {sql_file.name} --")
            counts = apply_migration(db, sql_file, dry_run=args.dry_run)
            for k, v in counts.items():
                overall[k] += v

    print()
    print(f"summary: {overall}")
    return 0 if overall["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
