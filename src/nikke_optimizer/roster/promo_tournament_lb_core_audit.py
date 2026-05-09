"""Constants for the Limit-Break / Max-Core audit page.

Mirrors the shape of :mod:`promo_tournament_doll_match`'s class-constants.
12 keys cover every distinct on-screen state of a ``char{N}.lb_core``
crop. ``unknown`` is the catchall for ``LB == 3 + badge present + OCR
returned garbage`` — the Phase-2 detector punts to this class rather
than guessing.
"""
from __future__ import annotations

from typing import Optional

# Stable display order — used for dropdown options + grid sorting.
AUDIT_KEYS: tuple[str, ...] = (
    "lb0", "lb1", "lb2",
    "mlb_c0", "mlb_c1", "mlb_c2", "mlb_c3",
    "mlb_c4", "mlb_c5", "mlb_c6", "mlb_max",
    "unknown",
)

DISPLAY_LABELS: dict[str, str] = {
    "lb0": "0 ★",
    "lb1": "1 ★",
    "lb2": "2 ★",
    "mlb_c0": "MLB Core 0",
    "mlb_c1": "MLB Core 1",
    "mlb_c2": "MLB Core 2",
    "mlb_c3": "MLB Core 3",
    "mlb_c4": "MLB Core 4",
    "mlb_c5": "MLB Core 5",
    "mlb_c6": "MLB Core 6",
    "mlb_max": "MLB MAX",
    "unknown": "—",
}

# PNG filenames under web/static/lb-core-icons/ — one per non-`unknown`
# class. Built once via scripts/build_lb_core_exemplars.py from the
# user's actual corpus, committed to the repo.
EXEMPLAR_FILES: dict[str, str] = {
    "lb0": "lb0.png",
    "lb1": "lb1.png",
    "lb2": "lb2.png",
    "mlb_c0": "mlb_c0.png",
    "mlb_c1": "mlb_c1.png",
    "mlb_c2": "mlb_c2.png",
    "mlb_c3": "mlb_c3.png",
    "mlb_c4": "mlb_c4.png",
    "mlb_c5": "mlb_c5.png",
    "mlb_c6": "mlb_c6.png",
    "mlb_max": "mlb_max.png",
}

# Pre-class-key data format → new class keys. Used by the one-shot
# `migrate-lb-core-format` CLI sub-command. Idempotent: rows already
# in new-format are detected by membership in `AUDIT_KEYS` and skipped.
OLD_TO_NEW_NORMALIZED: dict[str, str] = {
    "0": "lb0",
    "1": "lb1",
    "2": "lb2",
    # "3" used to mean "MLB but badge OCR returned garbage" — that's
    # exactly what `unknown` captures.
    "3": "unknown",
    "3,0": "mlb_c0",
    "3,1": "mlb_c1",
    "3,2": "mlb_c2",
    "3,3": "mlb_c3",
    "3,4": "mlb_c4",
    "3,5": "mlb_c5",
    "3,6": "mlb_c6",
    "3,7": "mlb_max",
}


def parse_lb_core_class(key: str) -> tuple[int, Optional[int]]:
    """Recover the (limit_break, core) integers from a class key.

    >>> parse_lb_core_class("lb0")
    (0, None)
    >>> parse_lb_core_class("mlb_c0")
    (3, 0)
    >>> parse_lb_core_class("mlb_max")
    (3, 7)
    >>> parse_lb_core_class("unknown")
    (-1, None)
    """
    if key == "unknown":
        return (-1, None)
    if key.startswith("lb"):
        return (int(key[2:]), None)
    if key == "mlb_max":
        return (3, 7)
    if key.startswith("mlb_c"):
        return (3, int(key[5:]))
    raise ValueError(f"Unknown LB/Core class key: {key!r}")
