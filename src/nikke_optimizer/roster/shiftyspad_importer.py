"""ShiftyPad → DB mapping.

Translates the JSON payloads returned by
``data.scrapers.shiftyspad`` into ``OwnedCharacter`` / ``AccountState``
row updates. v1 scope is deliberately narrow — the fields the
BlablaLink API exposes directly, no derived stats and no OL gear
bonus decoding (that needs lookup tables we don't have yet).

Fields populated per character:

  - ``sync_level`` ← home roster ``lv``   (always from home — see below)
  - ``core`` ← detail ``core`` (or home ``core`` fallback)
  - ``limit_break`` ← detail ``grade`` (or home ``grade`` fallback)
  - ``power`` ← detail ``combat`` (or home ``combat`` fallback)
  - From detail only:
    ``skill1_level`` / ``skill2_level`` / ``burst_skill_level``
    ← ``skill1_lv`` / ``skill2_lv`` / ``ulti_skill_lv``
  - ``bond_rank`` ← detail ``attractive_lv``

**Why sync_level always comes from home, never detail**: the two
endpoints expose different things under the same field name.
``home.GetUserCharacters[i].lv`` is the **displayed/effective sync
level** (655 if in a sync slot, else the per-char stored level).
``detail.GetUserCharacterDetails[i].lv`` is the **stored individual
level** only — equals 1 for any never-manually-leveled character even
if they're currently synced to the outpost cap. Writing detail.lv
would corrupt sync_level for in-slot chars (A2 has stored=200 but
displays at 655). The home roster is the only signal that respects
the synchro slot bonus.

Skipped in v1 (require additional lookup tables we don't mirror yet):
  - OL gear (option_id → bonus type)
  - Cube assignment (Cube table has no ``tid`` column)
  - Costumes list (costume_tid → display name)
  - Treasure/Doll (favorite_item_tid → name + rarity)
  - Per-character flat stat values (bond/class/mfr ATK/HP/DEF).
    AccountState-level research is still imported; the simulator's
    ``account_buffs`` helpers fall back to those values.

For ``AccountState``:

  - ``synchro_level`` ← outpost ``synchro_level``
  - ``general_research_level`` ← research ``tid=1001``
  - ``class_{attacker,defender,supporter}_level`` ← tid 1101/1102/1103
  - ``mfr_{elysion,missilis,tetra,pilgrim,abnormal}_level``
    ← tid 1201/1202/1203/1204/1205

Privacy:
  - If the outpost payload is per-field-redacted (PRIVACY_SENTINEL on
    research entries), we skip the research updates but still pick up
    the always-public fields (synchro_level, outpost_battle_level).
  - If the roster is wholly private, we skip OwnedCharacter writes
    entirely.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir
from sqlmodel import Session, select

from ..data.db import get_session, init_db, make_engine
from ..data.models import AccountState, Character, OwnedCharacter
from sqlmodel import delete

from ..data.enums import BurstType, Element, Manufacturer, Rarity, WeaponClass
from ..data.models import ArenaMatch, RosterSnapshot, RosterSnapshotCharacter
from ..data.scrapers.shiftyspad import (
    PRIVACY_SENTINEL,
    CharacterDetailPayload,
    HomePayload,
)
from ..data.scrapers.shiftyspad_decoder import (
    decode_cube,
    decode_favorite_item,
    decode_gear_bonus,
    decode_gear_piece,
)
from .csv_importer import _find_character

# Marker used in Character.source for rows synthesized from BlablaLink data
# when Prydwen hasn't shipped the character yet. Looked for by the scraper
# report ("stubs awaiting refresh") and by `nikkeoptimizer refresh` when it
# wants to upgrade stubs.
STUB_SOURCE_MARKER = "blablalink_stub"

log = logging.getLogger(__name__)


# Maps `recycle_room_researches[].tid` → AccountState attribute name.
# Order in tids 1201-1205 was verified empirically against a player
# with distinct mfr levels — see exploration session 2026-05-15.
RESEARCH_TID_TO_FIELD: dict[int, str] = {
    1001: "general_research_level",
    1101: "class_attacker_level",
    1102: "class_defender_level",
    1103: "class_supporter_level",
    1201: "mfr_elysion_level",
    1202: "mfr_missilis_level",
    1203: "mfr_tetra_level",
    1204: "mfr_pilgrim_level",
    1205: "mfr_abnormal_level",
}


# Fields tracked by the dry-run differ for OwnedCharacter. Mirror the
# subset _build_owned_kwargs_from_detail() actually writes.
DIFFED_FIELDS = (
    "sync_level", "core", "limit_break",
    "skill1_level", "skill2_level", "burst_skill_level",
    "power", "bond_rank",
)


# ---------------------------------------------------------------------------
# Name-code resolution
# ---------------------------------------------------------------------------


def _default_nikke_list_path() -> Path:
    return (
        Path(user_data_dir("NikkeOptimizer", appauthor=False))
        / "blablalink" / "en" / "nikke_list_en_v2.json"
    )


@dataclass
class NameCodeIndex:
    """Lookup tables built once from the BlablaLink nikke_list mirror.

    The BlablaLink API uses two different IDs:
      - ``name_code`` — used in request bodies and as the stable key
        for the character (e.g. 5004 = Modernia).
      - ``resource_id`` — used in URLs (``/shiftyspad/nikke?nikke=<rid>``).

    Plus we need ``name_code → English name`` to resolve into our
    ``Character`` table by name.
    """

    name_code_to_name: dict[int, str]
    name_code_to_resource_id: dict[int, int]

    @classmethod
    def from_mirror(cls, path: Optional[Path] = None) -> "NameCodeIndex":
        path = path or _default_nikke_list_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing BlablaLink nikke_list mirror at {path}. "
                f"Run `nikkeoptimizer fetch-roledata --all` (or even just one "
                f"character) to populate it."
            )
        data = json.loads(path.read_text())
        nm: dict[int, str] = {}
        rid: dict[int, int] = {}
        for entry in data:
            try:
                code = int(entry["name_code"])
                name = (entry.get("name_localkey") or {}).get("name")
                resource_id = int(entry["resource_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if name:
                nm[code] = name
            rid[code] = resource_id
        return cls(name_code_to_name=nm, name_code_to_resource_id=rid)


# ---------------------------------------------------------------------------
# JSON → kwargs
# ---------------------------------------------------------------------------


def _build_owned_kwargs_from_detail(
    detail: dict, *, char_id: int
) -> dict:
    """Translate one ``GetUserCharacterDetails`` entry into
    OwnedCharacter kwargs.

    Note: ``sync_level`` is intentionally NOT populated here — detail
    ``lv`` is the stored individual level (1 for never-manually-leveled
    chars, even when currently synced). The home-roster ``lv`` is the
    displayed sync level we actually want. Callers merge this dict on
    top of the home-summary dict so summary's sync_level survives.
    """
    return dict(
        character_id=char_id,
        core=detail.get("core"),
        limit_break=detail.get("grade"),
        skill1_level=detail.get("skill1_lv"),
        skill2_level=detail.get("skill2_lv"),
        burst_skill_level=detail.get("ulti_skill_lv"),
        power=detail.get("combat"),
        bond_rank=detail.get("attractive_lv"),
    )


def _build_owned_kwargs_from_summary(
    summary: dict, *, char_id: int
) -> dict:
    """Translate one ``GetUserCharacters`` entry (the home-page list)
    into OwnedCharacter kwargs. A subset of the detail mapping for
    when we don't have a per-character detail payload available.
    """
    return dict(
        character_id=char_id,
        sync_level=summary.get("lv"),
        core=summary.get("core"),
        limit_break=summary.get("grade"),
        power=summary.get("combat"),
    )


def _build_account_state_updates(outpost_info: dict) -> dict:
    """Map outpost_info → AccountState fields. Skips redacted
    (PRIVACY_SENTINEL) entries silently.
    """
    updates: dict = {}
    sl = outpost_info.get("synchro_level")
    if isinstance(sl, int) and sl != PRIVACY_SENTINEL:
        updates["synchro_level"] = sl
    for entry in outpost_info.get("recycle_room_researches") or []:
        tid = entry.get("tid")
        lv = entry.get("lv")
        if tid == PRIVACY_SENTINEL or lv == PRIVACY_SENTINEL:
            continue
        field = RESEARCH_TID_TO_FIELD.get(tid)
        if field is None:
            continue
        updates[field] = lv
    return updates


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------


@dataclass
class CharacterDiff:
    """One character's worth of (current → proposed) field changes."""

    name: str
    name_code: int
    matched: bool
    is_new: bool = False  # OwnedCharacter row didn't exist yet
    changes: dict[str, tuple[object, object]] = field(default_factory=dict)
    # Captured-but-not-yet-persisted fields. These exist in the API
    # response and we want to surface them, but adding DB columns is a
    # larger change (dual-DB ALTER) — staged for a future slice.
    extras: dict[str, object] = field(default_factory=dict)


@dataclass
class ShiftyPadReport:
    """Composite result for both dry-run and apply modes."""

    rows: int = 0
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    fuzzy_warnings: list[str] = field(default_factory=list)
    diffs: list[CharacterDiff] = field(default_factory=list)
    account_state_changes: dict[str, tuple[object, object]] = field(default_factory=dict)
    is_roster_private: bool = False
    is_outpost_private: bool = False
    # Profile-level facts surfaced from basic_info.
    profile_summary: dict[str, object] = field(default_factory=dict)
    # Characters whose Character row is currently a BlablaLink stub
    # (source == STUB_SOURCE_MARKER). Reminder to run
    # `nikkeoptimizer refresh --name <X>` once Prydwen has them.
    stubs_awaiting_refresh: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    applied: bool = False

    def changed(self) -> list[CharacterDiff]:
        return [d for d in self.diffs if d.changes or d.is_new]


# Minimal report shim so we can reuse _find_character from csv_importer
# without dragging in its full ImportReport surface.
class _FuzzyReportShim:
    def __init__(self, sink: ShiftyPadReport) -> None:
        self.fuzzy_matched = 0
        self._sink = sink

    def warn(self, msg: str) -> None:
        self._sink.fuzzy_warnings.append(msg)


# ---------------------------------------------------------------------------
# Sync pipeline
# ---------------------------------------------------------------------------


def sync(
    home: HomePayload,
    details: list[CharacterDetailPayload],
    *,
    name_index: Optional[NameCodeIndex] = None,
    db_path: Optional[Path] = None,
    apply: bool = False,
) -> ShiftyPadReport:
    """Compute (and optionally apply) the changes implied by a
    ShiftyPad scrape.

    Behavior:
      - When ``apply=False`` (default), no DB writes happen — the
        report describes the diff.
      - When ``apply=True``, AccountState is updated in place
        (creating the singleton row if needed) and OwnedCharacter
        rows are upserted by ``character_id``. Existing OL gear,
        cubes, costumes, treasure data, and skill descriptions are
        preserved — we only touch the v1 subset.

    The ``details`` list pairs by ``name_code`` with the home
    roster; characters present in the home list but missing details
    fall back to the home-list summary fields.
    """
    name_index = name_index or NameCodeIndex.from_mirror()
    engine = make_engine(db_path)
    init_db(engine)

    report = ShiftyPadReport(
        is_roster_private=home.is_roster_private,
        is_outpost_private=home.is_outpost_private,
    )

    # Profile-level facts. is_banned is a hard warning; nickname /
    # area_id / character_count are useful confirmations for the user.
    if home.basic_info:
        bi = home.basic_info
        for k in ("nickname", "area_id", "lv", "gsn", "character_count",
                  "character_costume_count", "is_banned", "created_at",
                  "last_action_at"):
            if k in bi:
                report.profile_summary[k] = bi[k]
        if bi.get("is_banned"):
            report.warnings.append(
                f"profile is marked is_banned=True — data may be stale or restricted"
            )

    # Index detail payloads by name_code for lookup against the home roster.
    detail_by_code: dict[int, CharacterDetailPayload] = {
        d.name_code: d for d in details if d.detail is not None
    }

    with get_session(engine) as session:
        all_chars = session.exec(select(Character)).all()
        all_names = [c.name for c in all_chars]
        existing_owned: dict[int, OwnedCharacter] = {
            o.character_id: o for o in session.exec(select(OwnedCharacter)).all()
        }
        shim = _FuzzyReportShim(report)

        for summary in home.characters:
            try:
                name_code = int(summary["name_code"])
            except (KeyError, ValueError, TypeError):
                continue
            report.rows += 1
            display_name = name_index.name_code_to_name.get(name_code)
            if not display_name:
                report.unmatched.append(f"name_code={name_code} (no BlablaLink mapping)")
                continue
            char = _find_character(
                session, display_name, all_names=all_names, report=shim,
            )
            if char is None:
                report.unmatched.append(display_name)
                continue
            report.matched += 1

            # Always start from the home summary — it has the right
            # sync_level. Then merge detail fields (gear, skills, bond,
            # etc.) on top if available.
            kwargs = _build_owned_kwargs_from_summary(summary, char_id=char.id)
            detail_payload = detail_by_code.get(name_code)
            detail = detail_payload.detail if detail_payload else None
            if detail:
                kwargs.update(
                    _build_owned_kwargs_from_detail(detail, char_id=char.id)
                )

            # Capture-but-not-yet-persisted fields. Cube / treasure /
            # OL gear are all decoded here; OLGear DB writes happen
            # below (only in apply mode).
            extras: dict[str, object] = {}
            costume_id = summary.get("costume_id") or (detail or {}).get("costume_tid")
            if costume_id:
                extras["costume_id"] = costume_id
            if detail and detail.get("arena_combat") is not None:
                extras["arena_combat"] = detail["arena_combat"]
            if detail:
                # Cubes
                pve_cube = decode_cube(
                    detail.get("harmony_cube_tid", 0),
                    detail.get("harmony_cube_lv", 0),
                )
                if pve_cube:
                    extras["pve_cube"] = (
                        f"{pve_cube.name} lv{pve_cube.lv} "
                        f"({pve_cube.atk}/{pve_cube.hp}/{pve_cube.def_} atk/hp/def)"
                    )
                elif detail.get("harmony_cube_tid"):
                    extras["pve_cube"] = (
                        f"tid={detail['harmony_cube_tid']} (unknown cube)"
                    )
                pvp_cube = decode_cube(
                    detail.get("arena_harmony_cube_tid", 0),
                    detail.get("arena_harmony_cube_lv", 0),
                )
                if pvp_cube:
                    extras["pvp_cube"] = (
                        f"{pvp_cube.name} lv{pvp_cube.lv} "
                        f"({pvp_cube.atk}/{pvp_cube.hp}/{pvp_cube.def_} atk/hp/def)"
                    )
                elif detail.get("arena_harmony_cube_tid"):
                    extras["pvp_cube"] = (
                        f"tid={detail['arena_harmony_cube_tid']} (unknown cube)"
                    )
                # Favorite item
                fi = decode_favorite_item(
                    detail.get("favorite_item_tid", 0),
                    detail.get("favorite_item_lv", 0),
                )
                if fi:
                    extras["favorite_item"] = (
                        f"{fi.name} ({fi.kind} {fi.rarity}) "
                        f"lv{fi.lv} grade{fi.grade}"
                    )
                elif detail.get("favorite_item_tid"):
                    extras["favorite_item"] = (
                        f"tid={detail['favorite_item_tid']} (unknown)"
                    )
                # OL gear — decode each slot's piece + 3 bonuses.
                if detail_payload is not None:
                    gear_summary = _decode_gear_summary(detail, detail_payload.state_effects)
                    if gear_summary:
                        extras["ol_gear"] = gear_summary

            diff = _diff_owned(
                kwargs, existing_owned.get(char.id), display_name, name_code,
            )
            diff.extras = extras
            report.diffs.append(diff)

            if apply:
                _upsert_owned(session, kwargs, existing_owned.get(char.id))

        # AccountState updates from outpost.
        if home.outpost_info:
            updates = _build_account_state_updates(home.outpost_info)
            state = session.exec(select(AccountState)).one_or_none()
            current = (
                {k: getattr(state, k) for k in updates} if state else {k: None for k in updates}
            )
            for k, v in updates.items():
                if current.get(k) != v:
                    report.account_state_changes[k] = (current.get(k), v)
            if apply and updates:
                if state is None:
                    state = AccountState(id=1, **updates)
                    session.add(state)
                else:
                    for k, v in updates.items():
                        setattr(state, k, v)

        # Record any stub Character rows that the user should remember
        # to upgrade once Prydwen has them. (Cheap query — runs even in
        # dry-run so the warning surfaces on every scrape.)
        stub_chars = session.exec(
            select(Character).where(Character.source == STUB_SOURCE_MARKER)
        ).all()
        report.stubs_awaiting_refresh = sorted(c.name for c in stub_chars)

        if apply:
            session.commit()
            report.applied = True

    return report


def _diff_owned(
    kwargs: dict,
    existing: Optional[OwnedCharacter],
    name: str,
    name_code: int,
) -> CharacterDiff:
    if existing is None:
        return CharacterDiff(
            name=name, name_code=name_code, matched=True, is_new=True,
            changes={k: (None, v) for k, v in kwargs.items()
                     if k != "character_id" and v is not None},
        )
    changes: dict[str, tuple[object, object]] = {}
    for f in DIFFED_FIELDS:
        if f not in kwargs:
            continue
        new = kwargs[f]
        old = getattr(existing, f, None)
        if new is not None and new != old:
            changes[f] = (old, new)
    return CharacterDiff(
        name=name, name_code=name_code, matched=True, is_new=False, changes=changes,
    )


def _upsert_owned(
    session: Session, kwargs: dict, existing: Optional[OwnedCharacter],
) -> None:
    """Partial-update upsert. Unlike the CSV importer (which replaces
    rows wholesale), we only set the v1 subset and leave other
    columns — OL gear, cubes, costumes, treasure, descriptions —
    untouched.
    """
    if existing is None:
        session.add(OwnedCharacter(**kwargs))
        return
    for k, v in kwargs.items():
        if k == "character_id":
            continue
        if v is None:
            continue
        setattr(existing, k, v)


# ---------------------------------------------------------------------------
# OL gear decoding (extras display)
# ---------------------------------------------------------------------------

# Detail-response keys for each gear slot. Order matters (head/body/arms/legs).
_GEAR_SLOT_PREFIXES = ("head", "torso", "arm", "leg")


def _decode_gear_summary(detail: dict, state_effects: list[dict]) -> list[dict]:
    """Decode all 4 OL gear slots from a detail response.

    Returns a list of dicts (one per slot), each containing the
    leveled stats + the 3 bonus lines. Slots with no equipped piece
    (tid=0) are omitted.
    """
    summary: list[dict] = []
    for slot in _GEAR_SLOT_PREFIXES:
        tid = detail.get(f"{slot}_equip_tid", 0)
        lv = detail.get(f"{slot}_equip_lv", 0)
        if not tid:
            continue
        piece = decode_gear_piece(tid, lv)
        if piece is None:
            summary.append({
                "slot": slot,
                "tid": tid, "lv": lv,
                "name": f"tid={tid} (unknown)",
                "bonuses": [],
            })
            continue
        bonuses: list[str] = []
        for opt_idx in (1, 2, 3):
            oid = detail.get(f"{slot}_equip_option{opt_idx}_id", 0)
            if not oid:
                continue
            b = decode_gear_bonus(oid, state_effects)
            if b is None:
                bonuses.append(f"opt={oid} (unresolved)")
            else:
                bonuses.append(f"{b.raw_label} {b.percent:.2f}%")
        leveled = piece.leveled()
        summary.append({
            "slot": slot,
            "tid": tid, "lv": lv,
            "name": piece.name,
            "tier": piece.tier,
            "stats": f"HP{leveled['hp']}/ATK{leveled['atk']}/DEF{leveled['def']}",
            "bonuses": bonuses,
        })
    return summary


# ---------------------------------------------------------------------------
# Stub-character workflow (for chars not yet on Prydwen)
# ---------------------------------------------------------------------------

# Translate BlablaLink's machine-readable codes to our enum values.
_BLABLALINK_BURST_MAP: dict[str, BurstType] = {
    "Step1": BurstType.I,
    "Step2": BurstType.II,
    "Step3": BurstType.III,
    "AllStep": BurstType.FLEX,
}

_BLABLALINK_CORPORATION_MAP: dict[str, Manufacturer] = {
    "ELYSION": Manufacturer.ELYSION,
    "MISSILIS": Manufacturer.MISSILIS,
    "TETRA": Manufacturer.TETRA,
    "PILGRIM": Manufacturer.PILGRIM,
    "ABNORMAL": Manufacturer.ABNORMAL,
}


def _blablalink_entry_for_name(name: str, name_index: NameCodeIndex) -> Optional[dict]:
    """Look up the raw nikke_list_en_v2.json entry for a display name.

    Falls back to case-insensitive match.
    """
    path = _default_nikke_list_path()
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    name_lower = name.lower()
    for entry in data:
        local = entry.get("name_localkey") or {}
        if (local.get("name") or "").lower() == name_lower:
            return entry
    return None


def stub_from_shiftyspad(
    name: str,
    *,
    db_path: Optional[Path] = None,
) -> tuple[Optional[Character], str]:
    """Create a minimal Character row from the BlablaLink nikke list.

    Used when a character exists in BlablaLink's roster API but Prydwen
    doesn't have her page yet — typically the first few days after a
    new Nikke drops.

    Returns ``(character, status_message)``. Status is one of:

      - ``"created"`` — new stub row inserted
      - ``"exists"`` — a Character row with that name already exists
        (we don't overwrite — let `refresh` handle real data)
      - ``"not_found"`` — BlablaLink doesn't know this name either

    The stub sets ``source = "blablalink_stub"`` so the scraper report
    can call it out as "still awaiting Prydwen refresh."
    """
    name_index = NameCodeIndex.from_mirror()
    entry = _blablalink_entry_for_name(name, name_index)
    if entry is None:
        return None, "not_found"

    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as session:
        existing = session.exec(
            select(Character).where(Character.name == name)
        ).one_or_none()
        if existing is not None:
            return existing, "exists"

        # Pull what we can from the entry.
        rarity_str = entry.get("original_rare") or "SSR"
        burst_str = entry.get("use_burst_skill") or ""
        corp_str = entry.get("corporation") or ""
        cls_str = entry.get("class") or ""
        element_str = (
            (entry.get("element_id") or {}).get("element", {}).get("element") or ""
        )
        weapon_str = (
            (entry.get("shot_id") or {}).get("element", {}).get("weapon_type") or ""
        )

        char = Character(
            name=name,
            rarity=Rarity(rarity_str),
            element=Element(element_str) if element_str else Element.IRON,
            weapon_class=WeaponClass(weapon_str) if weapon_str else WeaponClass.AR,
            burst_type=_BLABLALINK_BURST_MAP.get(burst_str, BurstType.FLEX),
            manufacturer=_BLABLALINK_CORPORATION_MAP.get(corp_str.upper()),
            role_tags=[cls_str] if cls_str else [],
            source=STUB_SOURCE_MARKER,
        )
        session.add(char)
        session.commit()
        session.refresh(char)
        return char, "created"


def list_stub_characters(db_path: Optional[Path] = None) -> list[Character]:
    """All Character rows currently marked as BlablaLink stubs.

    The scraper report prints these to remind the user to upgrade them
    via ``nikkeoptimizer refresh --name <X>`` when Prydwen catches up.
    """
    engine = make_engine(db_path)
    init_db(engine)
    with get_session(engine) as session:
        return list(
            session.exec(
                select(Character).where(Character.source == STUB_SOURCE_MARKER)
            ).all()
        )


# ---------------------------------------------------------------------------
# Snapshot writer
# ---------------------------------------------------------------------------


@dataclass
class ShiftyPadSnapshotReport:
    """Result of writing a Champions Arena RosterSnapshot from a scrape."""

    snapshot_id: Optional[int] = None
    season_number: int = 0
    player_username: str = ""
    rows_seen: int = 0          # chars in home roster
    matched: int = 0            # chars resolved to a Character row
    unmatched: list[str] = field(default_factory=list)
    fuzzy_warnings: list[str] = field(default_factory=list)
    chars_written: int = 0      # RosterSnapshotCharacter rows actually written (sparse)
    matches_linked: int = 0     # ArenaMatch rows whose FK was set/updated
    is_roster_private: bool = False
    is_outpost_private: bool = False
    replaced_existing: bool = False
    label: Optional[str] = None


def _build_snapshot_char_payload(
    summary: dict, detail: CharacterDetailPayload, kwargs: dict,
) -> dict:
    """Render one character's snapshot JSON payload.

    Mirrors the field shape ``serialize_owned`` produces from the live
    ``OwnedCharacter`` table, plus shiftyspad-specific extras (PvE/PvP
    cube tids, favorite item tid, arena_combat, decoded OL gear) so a
    snapshot stands alone — the simulator never needs to look back at
    the source response to reconstruct stats.
    """
    payload = {k: v for k, v in kwargs.items() if k != "character_id"}
    d = detail.detail or {}
    payload["arena_combat"] = d.get("arena_combat")
    payload["costume_id"] = summary.get("costume_id") or d.get("costume_tid")
    payload["harmony_cube_tid"] = d.get("harmony_cube_tid")
    payload["harmony_cube_lv"] = d.get("harmony_cube_lv")
    payload["arena_harmony_cube_tid"] = d.get("arena_harmony_cube_tid")
    payload["arena_harmony_cube_lv"] = d.get("arena_harmony_cube_lv")
    payload["favorite_item_tid"] = d.get("favorite_item_tid")
    payload["favorite_item_lv"] = d.get("favorite_item_lv")
    payload["ol_gear"] = _decode_gear_summary(d, detail.state_effects)
    payload["source"] = "shiftyspad"
    return payload


def _link_arena_matches_to_snapshot(
    session: Session,
    *,
    snapshot: RosterSnapshot,
    season_number: int,
    player_username: str,
) -> int:
    """For each Champions ArenaMatch in this season where the player
    appears as user or opponent, set the corresponding FK to the new
    snapshot. Returns count of matches updated.

    Champions Arena loadouts are season-locked, so all matches in
    ``season_number`` for ``player_username`` should resolve against
    the same snapshot. Idempotent — re-linking just rewrites the FK.
    """
    from ..data.seasons import season_for_date

    matches = session.exec(
        select(ArenaMatch).where(ArenaMatch.mode == "champion")
    ).all()
    linked = 0
    for match in matches:
        if not match.captured_at:
            continue
        try:
            match_season = season_for_date(match.captured_at.date())
        except Exception:  # noqa: BLE001
            continue
        if match_season != season_number:
            continue
        changed = False
        if match.user_username == player_username:
            if match.user_snapshot_id != snapshot.id:
                match.user_snapshot_id = snapshot.id
                changed = True
        if match.opponent_username == player_username:
            if match.opponent_snapshot_id != snapshot.id:
                match.opponent_snapshot_id = snapshot.id
                changed = True
        if changed:
            linked += 1
    return linked


def sync_to_snapshot(
    home: HomePayload,
    details: list[CharacterDetailPayload],
    *,
    season_number: int,
    player_username: str,
    name_index: Optional[NameCodeIndex] = None,
    db_path: Optional[Path] = None,
    label: Optional[str] = None,
    link_matches: bool = True,
) -> ShiftyPadSnapshotReport:
    """Write a Champions Arena ``RosterSnapshot`` from a scrape.

    Sparse by design: only characters with a detail payload land as
    ``RosterSnapshotCharacter`` rows. The home-roster summary is
    consulted only for ``lv`` (effective sync level) and to confirm
    the character is owned. Account-level fields (synchro_level,
    research) come from ``home.outpost_info``.

    Replaces any existing snapshot for ``(season_number, player_username)`` —
    re-running with a larger ``--names`` list cleanly upgrades a
    partial snapshot to a more complete one.

    When ``link_matches=True`` (default), any Champions ``ArenaMatch``
    rows in the same season where ``player_username`` appears as
    user or opponent get their ``*_snapshot_id`` FK set to the new
    snapshot.
    """
    name_index = name_index or NameCodeIndex.from_mirror()
    engine = make_engine(db_path)
    init_db(engine)

    report = ShiftyPadSnapshotReport(
        season_number=season_number,
        player_username=player_username,
        is_roster_private=home.is_roster_private,
        is_outpost_private=home.is_outpost_private,
        label=label,
    )

    detail_by_code: dict[int, CharacterDetailPayload] = {
        d.name_code: d for d in details if d.detail is not None
    }

    with get_session(engine) as session:
        all_chars = session.exec(select(Character)).all()
        all_names = [c.name for c in all_chars]
        shim = _FuzzyReportShim(report)

        # Resolve characters + build payloads — sparse: only detail-fetched chars.
        characters_to_write: list[tuple[int, dict]] = []
        for summary in home.characters:
            try:
                name_code = int(summary["name_code"])
            except (KeyError, ValueError, TypeError):
                continue
            report.rows_seen += 1
            detail_payload = detail_by_code.get(name_code)
            if detail_payload is None or detail_payload.detail is None:
                continue  # sparse: skip chars we didn't fetch details for

            display_name = name_index.name_code_to_name.get(name_code)
            if not display_name:
                report.unmatched.append(f"name_code={name_code} (no mapping)")
                continue
            char = _find_character(
                session, display_name, all_names=all_names, report=shim,
            )
            if char is None:
                report.unmatched.append(display_name)
                continue
            report.matched += 1

            kwargs = _build_owned_kwargs_from_summary(summary, char_id=char.id)
            kwargs.update(
                _build_owned_kwargs_from_detail(detail_payload.detail, char_id=char.id)
            )
            payload = _build_snapshot_char_payload(summary, detail_payload, kwargs)
            characters_to_write.append((char.id, payload))

        # Replace any prior snapshot for this (season, player) wholesale.
        existing = session.exec(
            select(RosterSnapshot).where(
                RosterSnapshot.season_number == season_number,
                RosterSnapshot.player_username == player_username,
            )
        ).first()
        if existing is not None:
            # Clear ArenaMatch FKs pointing at the row we're about to delete.
            session.exec(
                ArenaMatch.__table__.update()
                .where(ArenaMatch.user_snapshot_id == existing.id)
                .values(user_snapshot_id=None)
            )
            session.exec(
                ArenaMatch.__table__.update()
                .where(ArenaMatch.opponent_snapshot_id == existing.id)
                .values(opponent_snapshot_id=None)
            )
            session.exec(
                delete(RosterSnapshotCharacter).where(
                    RosterSnapshotCharacter.snapshot_id == existing.id
                )
            )
            session.delete(existing)
            session.commit()
            report.replaced_existing = True

        snapshot = RosterSnapshot(
            season_number=season_number,
            player_username=player_username,
            label=label or "shiftyspad",
        )
        # Account-level research / synchro fields from outpost.
        if home.outpost_info:
            updates = _build_account_state_updates(home.outpost_info)
            for fld, val in updates.items():
                if hasattr(snapshot, fld) and val is not None:
                    setattr(snapshot, fld, int(val))
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        report.snapshot_id = snapshot.id

        for char_id, payload in characters_to_write:
            session.add(RosterSnapshotCharacter(
                snapshot_id=snapshot.id,
                character_id=char_id,
                data=payload,
            ))
        session.commit()
        report.chars_written = len(characters_to_write)

        if link_matches:
            report.matches_linked = _link_arena_matches_to_snapshot(
                session,
                snapshot=snapshot,
                season_number=season_number,
                player_username=player_username,
            )
            session.commit()

    return report
