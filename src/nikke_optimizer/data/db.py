"""SQLite engine + session management.

Database lives under the user's data directory (platformdirs-aware) so the
roster persists across reinstalls. Override path with NIKKE_OPTIMIZER_DB env var.
"""

import os
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  -- ensures table metadata is registered

_APP_NAME = "NikkeOptimizer"
_DB_FILENAME = "nikke_optimizer.sqlite3"
_PORTRAITS_DIRNAME = "portraits"


def default_db_path() -> Path:
    override = os.environ.get("NIKKE_OPTIMIZER_DB")
    if override:
        return Path(override)
    base = Path(user_data_dir(_APP_NAME, appauthor=False))
    base.mkdir(parents=True, exist_ok=True)
    return base / _DB_FILENAME


def default_portrait_library_path() -> Optional[Path]:
    """Return the standard location for the labeled portrait library.

    Looks at ``NIKKE_OPTIMIZER_PORTRAITS`` env var first, then falls back
    to ``<user_data_dir>/portraits/``. Returns ``None`` if neither
    location exists — the caller should treat that as "no library
    available, run without portrait matching."
    """
    override = os.environ.get("NIKKE_OPTIMIZER_PORTRAITS")
    if override:
        p = Path(override)
        return p if p.is_dir() else None
    base = Path(user_data_dir(_APP_NAME, appauthor=False))
    candidate = base / _PORTRAITS_DIRNAME
    return candidate if candidate.is_dir() else None


def make_engine(db_path: Optional[Path] = None, *, echo: bool = False):
    path = db_path or default_db_path()
    if path != Path(":memory:"):
        path.parent.mkdir(parents=True, exist_ok=True)
    url = "sqlite:///:memory:" if str(path) == ":memory:" else f"sqlite:///{path}"
    return create_engine(url, echo=echo, connect_args={"check_same_thread": False})


def init_db(engine) -> None:
    """Idempotently create all tables. Safe to call on every startup."""
    SQLModel.metadata.create_all(engine)
    _ensure_promo_extracted_field_columns(engine)
    _ensure_owned_character_v2_columns(engine)


def _ensure_promo_extracted_field_columns(engine) -> None:
    """Add columns added to ``PromoExtractedField`` since the table was
    first created. SQLite doesn't support ``ALTER ... ADD IF NOT EXISTS``
    so we check ``pragma_table_info`` and ALTER only when the column is
    missing. Idempotent — safe on every boot.
    """
    with engine.connect() as conn:
        cols = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(promo_extracted_field)"
            )
        }
        if not cols:
            return  # table not yet created (e.g. fresh in-memory DB before create_all)
        if "manually_corrected" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE promo_extracted_field "
                "ADD COLUMN manually_corrected INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()


def _ensure_owned_character_v2_columns(engine) -> None:
    """Add per-character rank-buff columns added in the 2026-05-08
    CSV format. SQLite doesn't support ``ALTER ... ADD IF NOT EXISTS``
    so we check pragma and ALTER only when missing. Idempotent.
    """
    new_cols = [
        "bond_rank", "bond_hp", "bond_def", "bond_atk",
        "class_rank_level", "class_rank_hp", "class_rank_def", "class_rank_atk",
        "mfr_rank_level", "mfr_rank_hp", "mfr_rank_def", "mfr_rank_atk",
    ]
    with engine.connect() as conn:
        cols = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(owned_character)"
            )
        }
        if not cols:
            return  # table not yet created
        for col in new_cols:
            if col not in cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE owned_character ADD COLUMN {col} INTEGER"
                )
        conn.commit()


def get_session(engine) -> Session:
    return Session(engine)
