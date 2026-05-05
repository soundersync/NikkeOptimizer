"""Parser for the `Costumes` column in the roster CSV.

Two formats observed across CSV exports:

  * **legacy** (early roster exports): entries glue the character's full
    name + rarity tier with no separator, e.g.
    ``"Snow White: Heavy ArmsDefault"`` or
    ``"Red FlavorUnique | Shining LightSpecial"``.

  * **current** (post-2026-04 exports): entries are just the skin name,
    pipe-separated, with the in-game default appearing as the literal
    word ``"Default"``, e.g.
    ``"Red Flavor|Cherished Red|Shining Light|Default"``.

The parser handles both. The output schema is unchanged: a list of
``{"name": str, "rarity": Optional[str]}`` dicts.
"""

from __future__ import annotations

import re
from typing import Optional

# Order matters: longer suffixes must be checked first so "specialevent"
# doesn't get split as "special" + "event". The single-letter "r"/"sr"/"ssr"
# rarities apply to characters, not skins — including them here would
# corrupt skin names like "Red Flavor" (would strip the trailing "r").
_RARITY_SUFFIXES = ["default", "unique", "special", "event", "limited"]


def _strip_rarity(value: str) -> tuple[str, Optional[str]]:
    low = value.lower()
    for suffix in _RARITY_SUFFIXES:
        if low.endswith(suffix):
            return value[: -len(suffix)].strip(), suffix
    return value.strip(), None


def parse_costumes(value: Optional[str]) -> list[dict]:
    """Parse the Costumes cell into a structured list.

    Returns a list of ``{"name": str, "rarity": Optional[str]}`` dicts.
    Returns an empty list when the cell is blank. Handles both the
    legacy "name+rarity glued together" format and the current
    "skin name only, with 'Default' as a literal entry" format.
    """
    if not value:
        return []
    out: list[dict] = []
    for raw in value.split("|"):
        raw = raw.strip()
        if not raw:
            continue
        stripped_name, rarity = _strip_rarity(raw)
        if stripped_name:
            # Legacy format: "Red Flavorunique" → name="Red Flavor", rarity="unique"
            out.append({"name": stripped_name, "rarity": rarity})
        elif rarity:
            # Current format where the entry IS a rarity word, e.g. just
            # "Default" — keep the original word as the skin name and
            # set the rarity tier accordingly. (The in-game default skin
            # is conventionally named after the rarity tier.)
            out.append({"name": raw, "rarity": rarity})
        else:
            # Current format: skin name with no rarity suffix.
            out.append({"name": raw, "rarity": None})
    return out
