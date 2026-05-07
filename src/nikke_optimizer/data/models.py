"""SQLModel persistence schema for static character DB and per-user roster.

`Character` represents a Nikke as released by Shift Up — invariant data scraped
from community sources (Prydwen, NikkeAPI). `OwnedCharacter` represents the
user's investment state. The remaining tables capture extracted screenshot data
(OL gear pieces + bonuses, harmony cubes, character icons, arena fixtures).
"""

from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, Field, Relationship, SQLModel

from .enums import (
    BurstType,
    Element,
    Manufacturer,
    OLBonusType,
    OLGearSlot,
    Rarity,
    WeaponClass,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Static character DB (Layer 1)
# ---------------------------------------------------------------------------


class Character(SQLModel, table=True):
    """Static character data — scraped from Prydwen, not user-specific."""

    __tablename__ = "character"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    rarity: Rarity
    element: Element
    weapon_class: WeaponClass
    burst_type: BurstType
    manufacturer: Optional[Manufacturer] = None
    role_tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    base_atk: Optional[int] = None
    base_hp: Optional[int] = None
    base_def: Optional[int] = None
    skill1_description: Optional[str] = None
    skill2_description: Optional[str] = None
    burst_description: Optional[str] = None
    portrait_url: Optional[str] = None

    # --- Prydwen-enrichment fields (slice #61, 2026-04-28) ---
    # Free-form archetype tags ("Buffer", "Burst CD Reduction", "Pierce", ...).
    # Different from role_tags which is the normalized [class] + specialities.
    specialities: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Raw Contentful rich-text JSON strings — preserved verbatim so the
    # web UI can render them as formatted blocks. Plain-text extraction
    # available via `data.scrapers.prydwen.flatten_rich_text()`.
    pros_raw: Optional[str] = Field(default=None)
    cons_raw: Optional[str] = Field(default=None)
    review_raw: Optional[str] = Field(default=None)
    skill_analysis_raw: Optional[str] = Field(default=None)
    harmony_cubes_info_raw: Optional[str] = Field(default=None)
    # Flags Prydwen exposes per character.
    has_treasure: Optional[bool] = Field(default=None)
    high_investment: Optional[bool] = Field(default=None, description="Prydwen flags 'requires significant investment to be useful'")
    is_limited: Optional[bool] = Field(default=None)
    limited_event: Optional[str] = Field(default=None, description="e.g. 'Collaboration', 'Limited Banner'")
    release_date: Optional[str] = Field(default=None, description="ISO date or human-readable string from Prydwen")
    squad: Optional[str] = Field(default=None, description="Story squad affiliation (e.g. 'Goddess Squad')")

    source: Optional[str] = Field(default=None)
    last_updated: datetime = Field(default_factory=_utcnow)

    owned: List["OwnedCharacter"] = Relationship(back_populates="character")
    icons: List["CharacterIcon"] = Relationship(back_populates="character")


class CharacterIcon(SQLModel, table=True):
    """A cropped icon image for a character, used as a template for matching
    team-loadout screenshots back to characters."""

    __tablename__ = "character_icon"

    id: Optional[int] = Field(default=None, primary_key=True)
    character_id: int = Field(foreign_key="character.id", index=True)
    image_path: str = Field(description="Filesystem path to the cropped icon PNG")
    source: Optional[str] = Field(
        default=None,
        description="Origin: 'roster_screenshot', 'prydwen', 'manual'",
    )
    perceptual_hash: Optional[str] = Field(
        default=None,
        index=True,
        description="phash for fast nearest-neighbor lookup",
    )
    confidence: Optional[float] = Field(default=None)
    extracted_at: datetime = Field(default_factory=_utcnow)

    character: "Character" = Relationship(back_populates="icons")


# ---------------------------------------------------------------------------
# Per-user roster (Layer 2)
# ---------------------------------------------------------------------------


class OwnedCharacter(SQLModel, table=True):
    """The user's investment state for a Nikke they own."""

    __tablename__ = "owned_character"

    id: Optional[int] = Field(default=None, primary_key=True)
    character_id: int = Field(foreign_key="character.id", index=True)
    sync_level: Optional[int] = Field(default=None, description="Synchro Device level (1-700+)")
    core: Optional[int] = Field(default=None, description="Core enhancement 0-10")
    limit_break: Optional[int] = Field(default=None, description="0-3, MAX = 3")
    star_count: Optional[int] = Field(default=None, description="1-3 yellow stars")
    phase: Optional[int] = Field(default=None, description="MLB phase 1-15+")

    skill1_level: Optional[int] = Field(default=None, description="1-10")
    skill2_level: Optional[int] = Field(default=None, description="1-10")
    burst_skill_level: Optional[int] = Field(default=None, description="1-10")
    burst_cooldown_seconds: Optional[float] = Field(default=None)
    skill1_name: Optional[str] = Field(default=None, description="In-game skill name, e.g. 'Liter Boost'")
    skill2_name: Optional[str] = Field(default=None)
    burst_name: Optional[str] = Field(default=None)
    skill1_description: Optional[str] = Field(
        default=None,
        description=(
            "Skill 1 description at the user's CURRENT skill level. "
            "Differs from Character.skill1_description when skill_level < 10 "
            "(magnitudes scale). Stored separately so the UI can show the "
            "user's exact percentages."
        ),
    )
    skill2_description: Optional[str] = Field(default=None)
    burst_description: Optional[str] = Field(default=None)

    rank: Optional[int] = Field(default=None, description="In-game roster rank #")
    squad: Optional[str] = Field(default=None)
    manufacturer_level: Optional[int] = Field(default=None)

    # Total stats shown on the character detail header (combat power + HP/ATK/DEF)
    power: Optional[int] = Field(default=None)
    total_hp: Optional[int] = Field(default=None)
    total_atk: Optional[int] = Field(default=None)
    total_def: Optional[int] = Field(default=None)
    power_bonus: Optional[int] = Field(default=None)
    hp_bonus: Optional[int] = Field(default=None)
    atk_bonus: Optional[int] = Field(default=None)
    def_bonus: Optional[int] = Field(default=None)

    # Doll / Treasure (Favorite Item) — the CSV column "Doll/Treasure ..."
    # holds either Doll (Collection Item, SR/R rarity, phase 1-15) OR
    # Treasure (Favorite Item, SSR rarity, phase 0-3) data per row.
    # ``treasure_rarity`` disambiguates: "SSR" → Treasure, "SR"/"R" → Doll.
    # ``is_treasure_unlocked`` (helper) checks rarity == "SSR" + phase >= 1.
    treasure_name: Optional[str] = Field(default=None, description="e.g. 'Antique Compass' (Treasure) or 'Shopping Commander Doll Ltd.' (Doll)")
    treasure_phase: Optional[int] = Field(default=None, description="0-3 for Treasure, 1-15 for Doll")
    treasure_atk: Optional[int] = Field(default=None)
    treasure_def: Optional[int] = Field(default=None)
    treasure_hp: Optional[int] = Field(default=None)
    treasure_rarity: Optional[str] = Field(default=None, description="SSR (Treasure), SR/R (Doll)")
    treasure_skill_levels: List[int] = Field(
        default_factory=list, sa_column=Column(JSON),
        description="2 levels (Doll) or 5 levels (Treasure)",
    )

    # Currently equipped harmony cubes (separate slots for PvE vs PvP).
    battle_cube_id: Optional[int] = Field(default=None, foreign_key="cube.id")
    arena_cube_id: Optional[int] = Field(default=None, foreign_key="cube.id")

    # Owned costume / skin variants for this character. Each entry is a dict
    # with `name` (display label) and `rarity` (one of 'default', 'unique',
    # 'special', 'event'). Used by the portrait matcher to know which skin
    # the user is most likely running in their screenshots.
    costumes: List[dict] = Field(default_factory=list, sa_column=Column(JSON))

    imported_at: datetime = Field(default_factory=_utcnow)
    source_screenshot: Optional[str] = Field(default=None)
    raw_ocr: dict = Field(default_factory=dict, sa_column=Column(JSON))

    character: "Character" = Relationship(back_populates="owned")
    ol_gear: List["OLGear"] = Relationship(
        back_populates="owned_character",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    buff_summary: List["BuffSummaryLine"] = Relationship(
        back_populates="owned_character",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class OLGear(SQLModel, table=True):
    """One of the four Overload (OL) equipment pieces.

    Each piece displays a base stat block (HP + ATK or HP + DEF) and 2-4
    'Change Equipment Effects' bonus lines. Bonus lines live in the
    `OLGearBonus` child table to support the variable count.
    """

    __tablename__ = "ol_gear"

    id: Optional[int] = Field(default=None, primary_key=True)
    owned_character_id: int = Field(foreign_key="owned_character.id", index=True)
    slot: OLGearSlot
    base_hp: Optional[int] = Field(default=None)
    base_atk: Optional[int] = Field(default=None)
    base_def: Optional[int] = Field(default=None)
    icon_confidence: Optional[float] = Field(default=None)

    owned_character: "OwnedCharacter" = Relationship(back_populates="ol_gear")
    bonuses: List["OLGearBonus"] = Relationship(
        back_populates="gear",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class OLGearBonus(SQLModel, table=True):
    """A single 'Change Equipment Effects' line on one OL gear piece.

    The blue/highlighted state distinguishes actively-rolled bonuses (the ones
    that contribute to the character's total stats) from grayed-out potential
    rolls — both are extracted, the optimizer decides how to use each.
    """

    __tablename__ = "ol_gear_bonus"

    id: Optional[int] = Field(default=None, primary_key=True)
    gear_id: int = Field(foreign_key="ol_gear.id", index=True)
    bonus_type: Optional[OLBonusType] = Field(
        default=None, description="None when OCR couldn't map to a known type"
    )
    raw_label: str
    percent: Optional[float] = Field(default=None)
    highlighted: bool = Field(default=False, description="Blue = actively applied")
    text_confidence: Optional[float] = Field(default=None)

    gear: "OLGear" = Relationship(back_populates="bonuses")


class BuffSummaryLine(SQLModel, table=True):
    """An aggregated buff line shown at the top of the Equipment tab.

    Computed by the game as the sum of all active OL bonuses; stored separately
    so we can cross-validate our extraction (sum of OLGearBonus[active] should
    match these totals within rounding).
    """

    __tablename__ = "buff_summary_line"

    id: Optional[int] = Field(default=None, primary_key=True)
    owned_character_id: int = Field(foreign_key="owned_character.id", index=True)
    bonus_type: Optional[OLBonusType] = Field(default=None)
    raw_label: str
    percent: Optional[float] = Field(default=None)
    bonus_amount: Optional[int] = Field(default=None, description="The (+N) suffix when present")
    highlighted: bool = Field(default=False)
    text_confidence: Optional[float] = Field(default=None)

    owned_character: "OwnedCharacter" = Relationship(back_populates="buff_summary")


# ---------------------------------------------------------------------------
# Harmony Cubes
# ---------------------------------------------------------------------------


class Cube(SQLModel, table=True):
    """A unique Harmony Cube TYPE the user owns (e.g. 'Bastion Cube').

    One row per cube type; `equipping_count_owned` records how many copies the
    user has (= max number of Nikkes that can equip this type at once). Stats
    reflect the cube's current upgrade level. Updates of the same cube type
    upsert by `name`.
    """

    __tablename__ = "cube"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, description="e.g. 'Assault Cube'")
    level: Optional[int] = Field(default=None, description="LV.X — None when unknown")
    atk: Optional[int] = Field(default=None)
    hp: Optional[int] = Field(default=None)
    def_: Optional[int] = Field(default=None, sa_column_kwargs={"name": "def"})
    equipping_count_equipped: Optional[int] = Field(default=None)
    equipping_count_owned: Optional[int] = Field(default=None)
    skill_descriptions: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    source_screenshot: Optional[str] = Field(default=None)
    extracted_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Arena fixtures (used to validate the future battle simulator)
# ---------------------------------------------------------------------------


class ArenaMatch(SQLModel, table=True):
    """A captured arena match — pre-battle teams + post-battle outcome.

    These are ground-truth fixtures the simulator must reproduce. One row per
    sub-match (Rookie = 1 row; SP Arena = up to 3 rows; Champion = up to 5).
    """

    __tablename__ = "arena_match"

    id: Optional[int] = Field(default=None, primary_key=True)
    mode: str = Field(description="'rookie', 'special', 'champion'")
    user_username: Optional[str] = Field(default=None, description="My in-game name")
    opponent_username: Optional[str] = Field(default=None)
    user_team: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    opponent_team: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    user_power: Optional[int] = Field(default=None)
    opponent_power: Optional[int] = Field(default=None)
    # Per-Nikke CP from the in-game arena card UI (under each portrait).
    # Length matches user_team / opponent_team — None entries mean OCR
    # couldn't read the cell. Used for cross-validating OCR character
    # match (your stored CP for X should align with the captured CP)
    # and for opponent fingerprinting (low-CP X plays differently from
    # max-CP X).
    user_team_powers: List[Optional[int]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    opponent_team_powers: List[Optional[int]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    user_role: Optional[str] = Field(default=None, description="'attack' or 'defense'")
    outcome: Optional[str] = Field(default=None, description="'win', 'loss', 'timeout'")
    round_index: Optional[int] = Field(
        default=None, description="1-3 for SP Arena rounds; 1-5 for Champion"
    )
    pre_battle_screenshot: Optional[str] = Field(default=None)
    battle_record_screenshot: Optional[str] = Field(default=None)
    raw_battle_record: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Per-Nikke damage/heal/take stats from Battle Records screen",
    )
    capture_quality: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description=(
            "Per-team / per-cell extraction metadata: distances, best-match "
            "candidates, confidence flags. Used by the manual-correction UI "
            "to surface borderline cells the user should verify."
        ),
    )
    needs_review: bool = Field(
        default=False,
        index=True,
        description="True when any cell fell below the confident-match threshold",
    )
    # --- Session grouping (slice #135) ---
    # All captures in one Champions Duel (10 loadouts + 5 round results +
    # 1 overall) share a session_id so completeness validation can say
    # "Round 4 result is missing" and the user can later add results to
    # an existing predictions session without creating a fresh one.
    # Rookie/SP captures may also use sessions but typically map 1:1.
    session_id: Optional[str] = Field(
        default=None, index=True,
        description="UUID shared by all captures in one upload batch / Duel",
    )
    session_label: Optional[str] = Field(
        default=None,
        description="Human-readable label, e.g. 'vs Aerin 2026-05-03'",
    )
    session_kind: Optional[str] = Field(
        default=None, index=True,
        description=(
            "'predictions' (loadouts only), 'partial' (some results), "
            "'complete' (all rounds + duel result), or None for non-Champions"
        ),
    )
    # Set at import time using the same CP-cross-validation heuristic the
    # auto-confirm logic uses. True/False/None — None means "couldn't tell"
    # (no captured username + no CP overlap with the owned roster).
    # Used by the session-completeness matrix to bucket Champions loadouts
    # into P1 (user) vs P2 (opponent) columns; works for non-ASCII
    # usernames where the simple username comparison fails.
    is_user_lineup: Optional[bool] = Field(default=None)
    captured_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Champions Arena — Promotion Tournament archive
# ---------------------------------------------------------------------------
# Distinct from ArenaMatch (which is row-per-screenshot for the live PvP
# capture flow). Promotion Tournament has a hierarchical shape — 1
# tournament → 8 groups → 3 round types → 4/2/1 matches → up to 12 source
# images per match — that ArenaMatch can't model cleanly. Stored under
# <repo>/captures/<YYYY-MM-DD>/promotion_tournament/<group>/<round>/<match>.
# v1: structural ingest only; OCR + portrait matching land in a future
# PromoExtractedField table.


class PromoTournament(SQLModel, table=True):
    __tablename__ = "promo_tournament"

    id: Optional[int] = Field(default=None, primary_key=True)
    captured_at: datetime = Field(
        index=True,
        description="Full timestamp parsed from the staging folder name (YYYYMMDD_HHMMSS).",
    )
    capture_date: date = Field(
        index=True,
        description="Date portion of captured_at — the user's grouping key in the UI.",
    )
    storage_root: str = Field(
        unique=True, index=True,
        description="Absolute path under <repo>/captures/<date>/promotion_tournament/.",
    )
    source_root: Optional[str] = Field(
        default=None,
        description="Original staging path (for traceability after relocation).",
    )
    label: Optional[str] = Field(default=None, description="Optional user-supplied name")
    created_at: datetime = Field(default_factory=_utcnow)


class PromoGroup(SQLModel, table=True):
    __tablename__ = "promo_group"
    __table_args__ = (
        UniqueConstraint("tournament_id", "group_no", name="uq_promo_group_tour_no"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="promo_tournament.id", index=True)
    group_no: int = Field(description="1..8")


class PromoMatch(SQLModel, table=True):
    __tablename__ = "promo_match"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "group_id", "round_label", "match_no",
            name="uq_promo_match_natural",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="promo_tournament.id", index=True)
    group_id: int = Field(foreign_key="promo_group.id", index=True)
    round_label: str = Field(
        index=True,
        description="'round_64' | 'top_32' | 'top_16'",
    )
    match_no: Optional[int] = Field(
        default=None,
        description="1..4 for round_64, 1..2 for top_32, NULL for top_16 single aggregated match.",
    )
    has_loadouts: bool = Field(
        default=True,
        description="False when only results/ exists (top_32 + top_16).",
    )


class PromoMatchScreenshot(SQLModel, table=True):
    __tablename__ = "promo_match_screenshot"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "kind", "side", "round_no",
            name="uq_promo_screenshot_natural",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="promo_match.id", index=True)
    kind: str = Field(
        index=True,
        description="'player_loadout' | 'results_overview' | 'results_duel'",
    )
    side: Optional[str] = Field(
        default=None,
        description="'top' | 'bottom' for loadouts; NULL for results_*",
    )
    round_no: Optional[int] = Field(
        default=None,
        description="1..5 for player_loadout and results_duel; NULL for results_overview.",
    )
    file_path: str = Field(description="Absolute path on disk under storage_root.")
