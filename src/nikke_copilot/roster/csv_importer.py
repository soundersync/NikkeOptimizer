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
    # Skill descriptions are now in the canonical CSV; recognized so the
    # importer doesn't warn about them.
}

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
            "warnings": self.warnings,
        }


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

                battle_cube = _upsert_cube(session, row.get("Battle Cube"), row.get("Battle Cube Stats"))
                arena_cube = _upsert_cube(session, row.get("Arena Cube"), row.get("Arena Cube Stats"))
                if battle_cube and battle_cube.id:
                    report.cubes_upserted += 1
                if arena_cube and arena_cube.id:
                    report.cubes_upserted += 1

                # Slice #134 — read 2026-04-29+ Doll/Treasure columns,
                # falling back to the legacy "Treasure ..." columns when
                # missing. The new format adds rarity (SSR=Treasure,
                # SR/R=Doll) and skill levels.
                treasure_name_raw = (
                    (row.get("Doll/Treasure Name") or row.get("Treasure Name") or "")
                    .strip() or None
                )
                treasure_phase_raw = (
                    row.get("Doll/Treasure Phase") or row.get("Treasure Phase")
                )
                treasure_stats_raw = (
                    row.get("Doll/Treasure Stats") or row.get("Treasure Stats")
                )
                treasure_rarity_raw = (
                    (row.get("Doll/Treasure Rarity") or "").strip() or None
                )
                treasure_skill_raw = row.get("Doll/Treasure Skill Levels") or ""
                treasure_stats = parse_stats_block(treasure_stats_raw)
                treasure_skill_levels: list[int] = []
                for tok in treasure_skill_raw.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    try:
                        treasure_skill_levels.append(int(tok))
                    except ValueError:
                        report.warn(f"unparseable Doll/Treasure skill level: {tok!r}")
                # Burst cooldown can come either from a dedicated column
                # (legacy CSV format) or as a "20.0 s" prefix on the
                # Burst Description (current CSV format).
                burst_desc_raw = row.get("Burst Description")
                burst_cd = parse_cooldown(row.get("Burst Cooldown"))
                if burst_cd is None:
                    burst_cd = parse_burst_cooldown_from_description(burst_desc_raw)
                owned = OwnedCharacter(
                    character_id=char.id,
                    sync_level=parse_int(row.get("Synchro Level")),
                    rank=parse_int(row.get("Rank")),
                    squad=(row.get("Squad") or "").strip() or None,
                    core=parse_int(row.get("Core Level")),
                    manufacturer_level=parse_int(row.get("Manufacturer Level")),
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
                    battle_cube_id=battle_cube.id if battle_cube else None,
                    arena_cube_id=arena_cube.id if arena_cube else None,
                    costumes=parse_costumes(row.get("Costumes")),
                    raw_ocr={"csv_row": row},
                )
                owned.ol_gear = [_build_gear(row, i, report=report) for i in range(1, 5)]
                owned.buff_summary = _build_buff_summary(row.get("Equipment Effects Summary"))
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
