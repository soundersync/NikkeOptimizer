"""User-config persistence (next to the DB).

A tiny JSON file at ``<user_data_dir>/config.json`` stores per-user
settings the app needs to remember across runs — currently just the
in-game username, used to gate CP cross-validation auto-confirm so
the system knows which team is the user's own.

Env vars take precedence over the config file. The file is created
on first write and is safe to delete (callers handle a missing file).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir

_APP_NAME = "NikkeCopilot"
_CONFIG_FILENAME = "config.json"


def _config_path() -> Path:
    base = Path(user_data_dir(_APP_NAME, appauthor=False))
    base.mkdir(parents=True, exist_ok=True)
    return base / _CONFIG_FILENAME


def _load() -> dict:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    path = _config_path()
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def get_self_username() -> Optional[str]:
    """Return the user's in-game name, or None if unconfigured.

    Resolution order:
      1. ``NIKKE_COPILOT_USERNAME`` env var
      2. ``username`` key in ``<user_data_dir>/config.json``
    """
    env = os.environ.get("NIKKE_COPILOT_USERNAME", "").strip()
    if env:
        return env
    cfg = _load()
    name = cfg.get("username")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def set_self_username(name: str) -> Path:
    """Persist the user's in-game name to the config file.

    Returns the path the value was written to so the caller can echo it.
    """
    cfg = _load()
    cfg["username"] = name.strip()
    _save(cfg)
    return _config_path()


def detect_self_username(session) -> Optional[tuple[str, int]]:
    """Best-guess the user's in-game name from existing arena captures.

    Counts occurrences of each ``user_username`` value across captured
    ArenaMatch rows; returns ``(name, count)`` for the most frequent one,
    or ``None`` if there are no captures yet.

    Used by ``nikkecopilot detect-username`` and the dashboard's first-
    run prompt to eliminate the only manual step left for CP cross-
    validation.
    """
    from collections import Counter
    # Late import to avoid circular dependency: data.models imports from
    # data.db which imports from data.config in the future.
    from sqlmodel import select

    from .models import ArenaMatch

    counts: Counter[str] = Counter()
    for cap in session.exec(select(ArenaMatch)).all():
        if cap.user_username:
            counts[cap.user_username.strip()] += 1
    if not counts:
        return None
    name, n = counts.most_common(1)[0]
    return (name, n)
