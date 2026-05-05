"""SQLite engine + session management.

Database lives under the user's data directory (platformdirs-aware) so the
roster persists across reinstalls. Override path with NIKKE_COPILOT_DB env var.
"""

import os
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  -- ensures table metadata is registered

_APP_NAME = "NikkeCopilot"
_DB_FILENAME = "nikke_copilot.sqlite3"
_PORTRAITS_DIRNAME = "portraits"


def default_db_path() -> Path:
    override = os.environ.get("NIKKE_COPILOT_DB")
    if override:
        return Path(override)
    base = Path(user_data_dir(_APP_NAME, appauthor=False))
    base.mkdir(parents=True, exist_ok=True)
    return base / _DB_FILENAME


def default_portrait_library_path() -> Optional[Path]:
    """Return the standard location for the labeled portrait library.

    Looks at ``NIKKE_COPILOT_PORTRAITS`` env var first, then falls back
    to ``<user_data_dir>/portraits/``. Returns ``None`` if neither
    location exists — the caller should treat that as "no library
    available, run without portrait matching."
    """
    override = os.environ.get("NIKKE_COPILOT_PORTRAITS")
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


def get_session(engine) -> Session:
    return Session(engine)
