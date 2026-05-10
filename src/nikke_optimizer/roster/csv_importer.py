"""Import a Nikke roster CSV into the local DB.

Expected schema (header row): see `EXPECTED_COLUMNS`. The importer:
  1. Looks up each row's character by name (exact, then fuzzy).
  2. Replaces existing OwnedCharacter for that character (cascading delete
     of OLGear/OLGearBonus/BuffSummaryLine).
  3. Upserts Cube rows by name; assigns battle/arena cubes per character.
  4. Returns counts + a list of warnings for unmatched names / missing data.
"""

import csv
import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlmodel import Session, delete, select

from ..data.db import get_session, init_db, make_engine
from ..data.enums import OLGearSlot
from ..data.models import (
    BuffSummaryLine,
    Character,
    Cube,
    OLGear,
    OLGearBonus,
    OwnedCharacter,
)
from .costumes import parse_costumes
from .csv_parsers import (
    parse_burst_cooldown_from_description,
    parse_cooldown,
    parse_effect,
    parse_effect_summary,
    parse_float,
    parse_int,
    parse_phase,
    parse_stats_block,
    strip_burst_cooldown_prefix,
)

log = logging.getLogger(__name__)

# Required columns — every supported CSV must have these (or an alias).
REQUIRED_COLUMNS = ["Name"]

# Canonical column names; aliases observed in user-provided CSVs. The importer
# normalizes the header row by mapping alias → canonical before reading.
COLUMN_ALIASES: dict[str, str] = {
    "Mfr Level": "Manufacturer Level",
    "Manufacturer Lv": "Manufacturer Level",
    # Legacy synonyms that also show up in some exports.
    "Synchro": "Synchro Level",
    "Sync Level": "Synchro Level",
    "Costume": "Costumes",
}

# Full set of canonical columns the importer is aware of. Missing optional
# columns are tolerated silently.
KNOWN_COLUMNS = {
    "Name", "Power", "Synchro Level", "Rank", "Rarity", "Squad", "Class",
    "Manufacturer", "Core Level", "Manufacturer Level", "HP", "ATK", "DEF",
    "Skill 1 Name", "Skill 1 Level", "Skill 1 Description",
    "Skill 2 Name", "Skill 2 Level", "Skill 2 Description",
    "Burst Name", "Burst Level", "Burst Cooldown", "Burst Description",
    "Equipment Effects Summary",
    "Gear 1 Stats", "Gear 1 Effect 1", "Gear 1 Effect 2", "Gear 1 Effect 3",
    "Gear 2 Stats", "Gear 2 Effect 1", "Gear 2 Effect 2", "Gear 2 Effect 3",
    "Gear 3 Stats", "Gear 3 Effect 1", "Gear 3 Effect 2", "Gear 3 Effect 3",
    "Gear 4 Stats", "Gear 4 Effect 1", "Gear 4 Effect 2", "Gear 4 Effect 3",
    # Pre-2026-04-29 CSV format (Doll data mislabeled as Treasure):
    "Treasure Name", "Treasure Phase", "Treasure Stats",
    # 2026-04-29+ CSV format — explicitly distinguishes Doll vs Treasure
    # via Rarity (SSR=Treasure, SR/R=Doll). Phase ranges differ by kind.
    "Doll/Treasure Name", "Doll/Treasure Rarity", "Doll/Treasure Phase",
    "Doll/Treasure Stats", "Doll/Treasure Skill Levels",
    "Battle Cube", "Battle Cube Stats", "Arena Cube", "Arena Cube Stats",
    "Costumes",
    # 2026-05-08+ CSV format (v2): adds Limit Break separately from
    # Core Level, plus explicit per-character rank-buff stats from
    # the Attribute popup (Bond / Class / Manufacturer Rank).
    "Limit Break",
    "Class Rank Level", "Manufacturer Rank Level",
    "Bond Rank", "Bond HP", "Bond DEF", "Bond ATK",
    "Class Rank HP", "Class Rank DEF", "Class Rank ATK",
    "Mfr Rank HP", "Mfr Rank DEF", "Mfr Rank ATK",
    # Skill descriptions are now in the canonical CSV; recognized so the
    # importer doesn't warn about them.
}


def _is_v2_format(fieldnames: list[str]) -> bool:
    """v2 CSV (2026-05-08+) ships explicit Limit Break + bond/class/mfr
    rank stats. Detected by presence of the ``Limit Break`` column.
    """
    return "Limit Break" in fieldnames


def _parse_core_level(raw: Optional[str]) -> Optional[int]:
    """Parse the ``Core Level`` column from a v2 CSV.

    Values: ``"max"`` → 7, ``"0"`` → 0, ``"1"`` ... ``"7"``, ``""``→None.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s == "max":
        return 7
    try:
        v = int(s)
    except ValueError:
        return None
    return max(0, min(7, v))


def _parse_limit_break(raw: Optional[str]) -> Optional[int]:
    """Parse the ``Limit Break`` column. Format is ``"<current>/<max>"``
    (e.g. ``"3/3"``, ``"0/3"``, ``"2/3"``). Returns the current grade.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    head = s.split("/", 1)[0].strip()
    try:
        return max(0, int(head))
    except ValueError:
        return None

# Kept for backward compatibility with existing test code that imports it.
EXPECTED_COLUMNS = sorted(KNOWN_COLUMNS)

_GEAR_SLOTS = [OLGearSlot.HEAD, OLGearSlot.BODY, OLGearSlot.ARMS, OLGearSlot.LEGS]


@dataclass
class ImportReport:
    rows: int = 0
    matched: int = 0
    fuzzy_matched: int = 0
    unmatched: int = 0
    cubes_upserted: int = 0
    format_version: str = "v1"  # "v1" or "v2" — set during header inspection
    warnings: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        log.warning(msg)
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return {
            "rows": self.rows,
            "matched": self.matched,
            "fuzzy_matched": self.fuzzy_matched,
            "unmatched": self.unmatched,
            "cubes_upserted": self.cubes_upserted,
            "format_version": self.format_version,
            "warnings": self.warnings,
        }


# Fields tracked by the dry-run differ. Keep keys in sync with what
# ``_build_owned_kwargs`` puts on the ``OwnedCharacter`` row — anything
# absent from this list won't show up in the diff.
DIFFED_FIELDS = (
    "sync_level", "core", "limit_break", "manufacturer_level",
    "skill1_level", "skill2_level", "burst_skill_level",
    "power", "total_hp", "total_atk", "total_def",
    "treasure_name", "treasure_phase", "treasure_atk", "treasure_def", "treasure_hp",
    "bond_rank", "bond_hp", "bond_def", "bond_atk",
    "class_rank_level", "class_rank_hp", "class_rank_def", "class_rank_atk",
    "mfr_rank_level", "mfr_rank_hp", "mfr_rank_def", "mfr_rank_atk",
)


@dataclass
class CharacterDiff:
    """One row's worth of (current → proposed) field changes."""

    name: str
    matched: bool
    is_new: bool = False  # not in DB
    changes: dict[str, tuple[object, object]] = field(default_factory=dict)
    # Significant power deltas — flagged for the user's attention even
    # when small in absolute terms (might indicate ungeared characters).
    power_delta: Optional[int] = None
    # When the new state has Limit Break 0 and very low Power, the
    # character is just baseline-uninvested — old DB Power was likely
    # stale/inflated rather than the user actually losing gear.
    looks_uninvested: bool = False
    # When the new state has high LB but low Power, that's a real
    # "lost gear" signal — the user MLB'd them but they're now stripped.
    looks_stripped: bool = False


@dataclass
class DryRunReport:
    rows: int = 0
    format_version: str = "v1"
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    fuzzy_warnings: list[str] = field(default_factory=list)
    diffs: list[CharacterDiff] = field(default_factory=list)
    db_only: list[str] = field(default_factory=list)  # in DB but not CSV
    warnings: list[str] = field(default_factory=list)

    def changed(self) -> list[CharacterDiff]:
        return [d for d in self.diffs if d.changes or d.is_new]

    def with_significant_power_drop(self, threshold: int = 50_000) -> list[CharacterDiff]:
        """Return diffs where Power dropped by at least ``threshold``."""
        return [
            d for d in self.diffs
            if d.power_delta is not None and d.power_delta <= -threshold
        ]


def _find_character(
    session: Session, name: str, *, all_names: list[str], report: ImportReport
) -> Optional[Character]:
    """Resolve a CSV character name to a DB ``Character`` row.

    CSV exports use shortened/casual names for collab characters (e.g.
    "Chisato" → "Chisato Nishikigi", "EVE" → "Eve", "Little Mermaid" →
    "Little Mermaid (Siren)"). Tries a series of progressively-fuzzier
    matchers before falling back to ``difflib`` similarity.
    """
    # 1. Exact
    char = session.exec(select(Character).where(Character.name == name)).one_or_none()
    if char is not None:
        return char

    name_lower = name.lower()
    name_map = {n.lower(): n for n in all_names}

    def _resolve(canonical: str, kind: str) -> Optional[Character]:
        report.fuzzy_matched += 1
        report.warn(f"{kind} match: '{name}' -> '{canonical}'")
        return session.exec(
            select(Character).where(Character.name == canonical)
        ).one_or_none()

    # 2. Case-insensitive exact (e.g. "EVE" -> "Eve")
    if name_lower in name_map:
        return _resolve(name_map[name_lower], "case-insensitive")

    # 3. Parenthetical-disambiguator form: CSV is "<X> (<Y>)", DB has
    # "<X> <middle> (<Y>)" (e.g. "Rei (Tentative Name)" -> "Rei Ayanami
    # (Tentative Name)"). Match same parenthetical, prefix on the head.
    if "(" in name and name.endswith(")"):
        head, _, paren = name.partition("(")
        head = head.strip()
        paren_full = "(" + paren  # includes the closing ")"
        head_lower = head.lower()
        paren_lower = paren_full.lower()
        candidates = [
            n for n in all_names
            if n.lower().endswith(" " + paren_lower)
            and n.lower().startswith(head_lower + " ")
        ]
        if len(candidates) == 1:
            return _resolve(candidates[0], "paren-disambiguator")
        if len(candidates) > 1:
            candidates.sort(key=len)
            return _resolve(candidates[0], "paren-disambiguator (ambiguous, shortest)")

    # 4. Colon-separated alt form: CSV is "<X>: <Y>", DB has
    # "<X> <middle>: <Y>" (e.g. "Asuka: WILLE" -> "Asuka Shikinami
    # Langley: Wille"). Match suffix case-insensitively, prefix on head.
    if ":" in name:
        base, _, suffix = name.partition(":")
        base = base.strip()
        suffix = suffix.strip()
        if base and suffix:
            base_lower = base.lower()
            suffix_lower = suffix.lower()
            candidates = []
            for n in all_names:
                if ":" not in n:
                    continue
                n_base, _, n_suffix = n.partition(":")
                n_base_l = n_base.strip().lower()
                n_suffix_l = n_suffix.strip().lower()
                if n_suffix_l != suffix_lower:
                    continue
                if n_base_l == base_lower or n_base_l.startswith(base_lower + " "):
                    candidates.append(n)
            if len(candidates) == 1:
                return _resolve(candidates[0], "colon-alt-form")
            if len(candidates) > 1:
                candidates.sort(key=len)
                return _resolve(candidates[0], "colon-alt-form (ambiguous, shortest)")

    # 5. Plain prefix: CSV "Chisato" -> DB "Chisato Nishikigi" (collab
    # short form), or "Little Mermaid" -> "Little Mermaid (Siren)"
    # (parenthetical disambiguator). Matches DB names that start with
    # "<csv> ", whether or not they have a paren suffix. Excludes alt
    # forms ("<csv>:") so those route through case 4.
    candidates = [
        n for n in all_names
        if n.lower().startswith(name_lower + " ")
        and ":" not in n
    ]
    if len(candidates) == 1:
        return _resolve(candidates[0], "prefix")
    if len(candidates) > 1:
        candidates.sort(key=len)
        return _resolve(candidates[0], "prefix (ambiguous, shortest)")

    # 6. Final fallback: fuzzy difflib (catches genuine typos)
    matches = difflib.get_close_matches(name, all_names, n=1, cutoff=0.85)
    if matches:
        return _resolve(matches[0], "fuzzy")
    return None


def _upsert_cube(session: Session, name: Optional[str], stats: Optional[str]) -> Optional[Cube]:
    if not name or not name.strip():
        return None
    name = name.strip()
    stat_dict = parse_stats_block(stats) if stats else {}
    existing = session.exec(select(Cube).where(Cube.name == name)).one_or_none()
    if existing is None:
        cube = Cube(
            name=name,
            atk=stat_dict.get("atk"),
            hp=stat_dict.get("hp"),
            def_=stat_dict.get("def"),
        )
        session.add(cube)
        session.flush()
        return cube
    if "atk" in stat_dict:
        existing.atk = stat_dict["atk"]
    if "hp" in stat_dict:
        existing.hp = stat_dict["hp"]
    if "def" in stat_dict:
        existing.def_ = stat_dict["def"]
    return existing


def _build_gear(
    row: dict, idx: int, *, report: ImportReport
) -> Optional[OLGear]:
    stats_col = f"Gear {idx} Stats"
    stats = parse_stats_block(row.get(stats_col))
    gear = OLGear(
        slot=_GEAR_SLOTS[idx - 1],
        base_hp=stats.get("hp"),
        base_atk=stats.get("atk"),
        base_def=stats.get("def"),
    )
    bonuses: list[OLGearBonus] = []
    for slot_idx in range(1, 4):
        eff = parse_effect(row.get(f"Gear {idx} Effect {slot_idx}"))
        if eff is None:
            continue
        bonus_type, raw_label, pct = eff
        bonuses.append(
            OLGearBonus(
                bonus_type=bonus_type,
                raw_label=raw_label,
                percent=pct,
                # CSV doesn't distinguish active vs grayed; treat all as active.
                # Buff summary cross-check will validate this assumption.
                highlighted=True,
            )
        )
    gear.bonuses = bonuses
    return gear


def _build_buff_summary(value: Optional[str]) -> list[BuffSummaryLine]:
    parsed = parse_effect_summary(value)
    return [
        BuffSummaryLine(
            bonus_type=bt,
            raw_label=raw,
            percent=pct,
            highlighted=True,
        )
        for bt, raw, pct in parsed
    ]


def _normalize_row(row: dict) -> dict:
    """Apply COLUMN_ALIASES so callers can read by canonical name only."""
    out = dict(row)
    for alias, canonical in COLUMN_ALIASES.items():
        if alias in out and canonical not in out:
            out[canonical] = out.pop(alias)
    return out


def _build_owned_kwargs(row: dict, *, char_id: int, v2: bool) -> dict:
    """Translate one CSV row into kwargs for OwnedCharacter(...).

    v1 vs v2 selection:
      - v2 (Limit Break column present): parse Core Level as ``max``/0-7,
        parse Limit Break as ``current/max``, capture bond/class/mfr rank stats.
      - v1: parse Core Level numerically (legacy behavior, may carry the
        bug where the column actually held class-rank-level values).
    """
    treasure_name_raw = (
        (row.get("Doll/Treasure Name") or row.get("Treasure Name") or "").strip() or None
    )
    treasure_phase_raw = row.get("Doll/Treasure Phase") or row.get("Treasure Phase")
    treasure_stats_raw = row.get("Doll/Treasure Stats") or row.get("Treasure Stats")
    treasure_rarity_raw = (row.get("Doll/Treasure Rarity") or "").strip() or None
    treasure_skill_raw = row.get("Doll/Treasure Skill Levels") or ""
    treasure_stats = parse_stats_block(treasure_stats_raw)
    # v2 CSV writes skill levels as "current/max" (e.g. "4/4"); v1
    # used bare integers. Accept both — strip any "/max" suffix and
    # parse the leading number.
    treasure_skill_levels: list[int] = []
    for tok in treasure_skill_raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        head = tok.split("/", 1)[0].strip()
        try:
            treasure_skill_levels.append(int(head))
        except ValueError:
            pass

    burst_desc_raw = row.get("Burst Description")
    burst_cd = parse_cooldown(row.get("Burst Cooldown"))
    if burst_cd is None:
        burst_cd = parse_burst_cooldown_from_description(burst_desc_raw)

    if v2:
        core_value = _parse_core_level(row.get("Core Level"))
        limit_break_value = _parse_limit_break(row.get("Limit Break"))
        # v2 dropped "Manufacturer Level" in favor of the more explicit
        # "Manufacturer Rank Level". Populate the legacy column from
        # the new one to keep historical readers working.
        manufacturer_level_value = parse_int(
            row.get("Manufacturer Level") or row.get("Manufacturer Rank Level")
        )
    else:
        core_value = parse_int(row.get("Core Level"))
        limit_break_value = None
        manufacturer_level_value = parse_int(row.get("Manufacturer Level"))

    return dict(
        character_id=char_id,
        sync_level=parse_int(row.get("Synchro Level")),
        rank=parse_int(row.get("Rank")),
        squad=(row.get("Squad") or "").strip() or None,
        core=core_value,
        limit_break=limit_break_value,
        manufacturer_level=manufacturer_level_value,
        skill1_level=parse_int(row.get("Skill 1 Level")),
        skill2_level=parse_int(row.get("Skill 2 Level")),
        burst_skill_level=parse_int(row.get("Burst Level")),
        burst_cooldown_seconds=burst_cd,
        skill1_name=(row.get("Skill 1 Name") or "").strip() or None,
        skill2_name=(row.get("Skill 2 Name") or "").strip() or None,
        burst_name=(row.get("Burst Name") or "").strip() or None,
        skill1_description=(row.get("Skill 1 Description") or "").strip() or None,
        skill2_description=(row.get("Skill 2 Description") or "").strip() or None,
        burst_description=strip_burst_cooldown_prefix(burst_desc_raw) or None,
        power=parse_int(row.get("Power")),
        total_hp=parse_int(row.get("HP")),
        total_atk=parse_int(row.get("ATK")),
        total_def=parse_int(row.get("DEF")),
        treasure_name=treasure_name_raw,
        treasure_phase=parse_phase(treasure_phase_raw),
        treasure_atk=treasure_stats.get("atk"),
        treasure_def=treasure_stats.get("def"),
        treasure_hp=treasure_stats.get("hp"),
        treasure_rarity=treasure_rarity_raw,
        treasure_skill_levels=treasure_skill_levels,
        # v2 per-character rank flat stats (from the Attribute popup).
        # All None for v1 CSVs.
        bond_rank=parse_int(row.get("Bond Rank")) if v2 else None,
        bond_hp=parse_int(row.get("Bond HP")) if v2 else None,
        bond_def=parse_int(row.get("Bond DEF")) if v2 else None,
        bond_atk=parse_int(row.get("Bond ATK")) if v2 else None,
        class_rank_level=parse_int(row.get("Class Rank Level")) if v2 else None,
        class_rank_hp=parse_int(row.get("Class Rank HP")) if v2 else None,
        class_rank_def=parse_int(row.get("Class Rank DEF")) if v2 else None,
        class_rank_atk=parse_int(row.get("Class Rank ATK")) if v2 else None,
        mfr_rank_level=parse_int(row.get("Manufacturer Rank Level")) if v2 else None,
        mfr_rank_hp=parse_int(row.get("Mfr Rank HP")) if v2 else None,
        mfr_rank_def=parse_int(row.get("Mfr Rank DEF")) if v2 else None,
        mfr_rank_atk=parse_int(row.get("Mfr Rank ATK")) if v2 else None,
    )


def dry_run_diff(
    csv_path: Path,
    *,
    db_path: Optional[Path] = None,
) -> DryRunReport:
    """Read the CSV and compare to the current DB without writing.

    Returns a :class:`DryRunReport` with per-character before→after
    diffs, characters that don't match a Character row, characters
    present in the DB but absent from the CSV, and a list of
    significant power drops the user may want to verify (e.g.
    accidental gear loss, unequipped Nikkes).
    """
    engine = make_engine(db_path)
    init_db(engine)
    report = DryRunReport()

    with get_session(engine) as session:
        all_chars = session.exec(select(Character)).all()
        all_names = [c.name for c in all_chars]
        # Existing OwnedCharacter rows by character_id, for diffing.
        existing_owned: dict[int, OwnedCharacter] = {
            o.character_id: o for o in session.exec(select(OwnedCharacter)).all()
        }
        seen_char_ids: set[int] = set()

        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames or [])
            v2 = _is_v2_format(fields)
            report.format_version = "v2" if v2 else "v1"
            unknown = [f for f in fields if f not in KNOWN_COLUMNS and f not in COLUMN_ALIASES]
            if unknown:
                report.warnings.append(f"unknown columns ignored: {unknown}")

            class _SilentReport:
                fuzzy_matched = 0
                def warn(self, msg: str) -> None:
                    report.fuzzy_warnings.append(msg)
            silent = _SilentReport()

            for raw_row in reader:
                row = _normalize_row(raw_row)
                report.rows += 1
                name = (row.get("Name") or "").strip()
                if not name:
                    report.warnings.append(f"row {report.rows}: empty Name")
                    continue
                char = _find_character(session, name, all_names=all_names, report=silent)
                if char is None:
                    report.unmatched.append(name)
                    continue
                report.matched += 1
                seen_char_ids.add(char.id)

                proposed = _build_owned_kwargs(row, char_id=char.id, v2=v2)
                current = existing_owned.get(char.id)
                diff = CharacterDiff(name=char.name, matched=True, is_new=current is None)
                new_lb = proposed.get("limit_break") or 0
                new_pow = proposed.get("power") or 0
                # Heuristic: low Power + uninvested LB ≡ baseline character,
                # not a real "lost gear" signal. Threshold tuned to ~LV1
                # base Power for SSRs (typically 4-7k).
                if new_lb == 0 and new_pow < 10_000:
                    diff.looks_uninvested = True
                if current is None:
                    diff.power_delta = new_pow  # full credit as positive
                else:
                    cp = current.power or 0
                    diff.power_delta = new_pow - cp
                    for key in DIFFED_FIELDS:
                        cur_v = getattr(current, key, None)
                        new_v = proposed.get(key)
                        if cur_v != new_v:
                            diff.changes[key] = (cur_v, new_v)
                    # "Stripped" = was MLB-tier invested, now low Power.
                    # Real signal — the user upgraded them but lost their
                    # gear, or the CSV scraper failed for this character.
                    if cp >= 50_000 and new_pow < 10_000 and new_lb >= 3:
                        diff.looks_stripped = True
                report.diffs.append(diff)

        # Characters in DB but absent from CSV
        for cid, owned in existing_owned.items():
            if cid in seen_char_ids:
                continue
            char = next((c for c in all_chars if c.id == cid), None)
            if char is not None:
                report.db_only.append(char.name)

    return report


def build_owned_from_row(
    session: Session,
    row: dict,
    *,
    char: Character,
    v2: bool,
    report: "ImportReport",
) -> OwnedCharacter:
    """Build a transient ``OwnedCharacter`` from one parsed CSV row.

    Upserts cube rows into the live DB (cubes are shared across
    players, not per-snapshot) and attaches ``ol_gear`` /
    ``buff_summary`` to the returned instance, but does **not** add
    it to the session. Callers decide whether to persist the result
    as a live row (``import_csv``) or serialize it for a snapshot
    (``snapshot_from_csv``).

    Doll/Treasure parsing handles both the legacy ``Treasure *``
    columns and the 2026-04-29+ ``Doll/Treasure *`` columns.
    """
    battle_cube = _upsert_cube(session, row.get("Battle Cube"), row.get("Battle Cube Stats"))
    arena_cube = _upsert_cube(session, row.get("Arena Cube"), row.get("Arena Cube Stats"))
    if battle_cube and battle_cube.id:
        report.cubes_upserted += 1
    if arena_cube and arena_cube.id:
        report.cubes_upserted += 1

    treasure_skill_raw = row.get("Doll/Treasure Skill Levels") or ""
    treasure_skill_levels: list[int] = []
    for tok in treasure_skill_raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            treasure_skill_levels.append(int(tok))
        except ValueError:
            report.warn(f"unparseable Doll/Treasure skill level: {tok!r}")

    kwargs = _build_owned_kwargs(row, char_id=char.id, v2=v2)
    kwargs["battle_cube_id"] = battle_cube.id if battle_cube else None
    kwargs["arena_cube_id"] = arena_cube.id if arena_cube else None
    kwargs["costumes"] = parse_costumes(row.get("Costumes"))
    kwargs["raw_ocr"] = {"csv_row": row}
    owned = OwnedCharacter(**kwargs)
    owned.ol_gear = [_build_gear(row, i, report=report) for i in range(1, 5)]
    owned.buff_summary = _build_buff_summary(row.get("Equipment Effects Summary"))
    return owned


def import_csv(
    csv_path: Path,
    *,
    db_path: Optional[Path] = None,
    replace_existing: bool = True,
) -> ImportReport:
    engine = make_engine(db_path)
    init_db(engine)
    report = ImportReport()

    with get_session(engine) as session:
        all_chars = session.exec(select(Character)).all()
        all_names = [c.name for c in all_chars]

        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames or [])
            normalized_fields = {COLUMN_ALIASES.get(f, f) for f in fields}
            missing_required = [
                c for c in REQUIRED_COLUMNS if c not in normalized_fields
            ]
            if missing_required:
                report.warn(f"CSV missing required columns: {missing_required}")
            unknown = [
                f for f in fields
                if f not in KNOWN_COLUMNS and f not in COLUMN_ALIASES
            ]
            if unknown:
                report.warn(f"CSV has unknown columns (ignored): {unknown}")
            v2 = _is_v2_format(fields)
            report.format_version = "v2" if v2 else "v1"

            for raw_row in reader:
                row = _normalize_row(raw_row)
                report.rows += 1
                name = (row.get("Name") or "").strip()
                if not name:
                    report.warn(f"row {report.rows}: empty Name, skipping")
                    report.unmatched += 1
                    continue
                char = _find_character(session, name, all_names=all_names, report=report)
                if char is None:
                    report.unmatched += 1
                    report.warn(f"row {report.rows}: no Character match for '{name}'")
                    continue
                report.matched += 1

                if replace_existing:
                    session.exec(
                        delete(OwnedCharacter).where(OwnedCharacter.character_id == char.id)
                    )

                owned = build_owned_from_row(
                    session, row, char=char, v2=v2, report=report,
                )
                session.add(owned)
            session.commit()

            # Slice #72: snapshot the roster post-import. Diff route can
            # compare the current state to any previous snapshot to
            # surface "what changed since last week."
            try:
                from .snapshots import take_snapshot
                snap_path = take_snapshot(session, label="post-csv-import")
                report.warn(f"snapshot saved: {snap_path.name}")
            except Exception as exc:  # pragma: no cover - defensive
                report.warn(f"snapshot failed: {exc}")

    return report
