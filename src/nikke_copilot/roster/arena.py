"""Arena screenshot extractors.

Three modes are handled (with overlapping geometry):

  - Rookie Arena pre-battle: opponent (top, defense) vs you (bottom, attack)
  - Special Arena pre-battle: same layout, with a ROUND 01/02/03 selector
  - Champion Arena single-team view: ONE player + ONE round shown in a popup,
    captured 5x per side per matchup

The implementation is intentionally region-driven: we crop fixed proportional
slices and rely on the PortraitMatcher to identify characters. Region constants
are tuned for the user's iPad screenshots (2732x2048) but use proportional math
so they generalize.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

from .ocr import recognize
from .portrait_matcher import PortraitMatcher

log = logging.getLogger(__name__)


@dataclass
class TeamLineup:
    """One team in an arena screenshot.

    For each of the 5 cells we keep both the *confident* match (set only when
    distance ≤ ``confident_distance`` — currently 0.55) and the *best* match
    (always set when the matcher index is non-empty). Downstream code can use
    confident matches for auto-import and surface best-match candidates for
    user confirmation.

    ``cell_powers`` holds the per-Nikke CP shown under each portrait
    (None when OCR couldn't extract). ``power`` is the team total.
    """

    player_username: Optional[str] = None
    power: Optional[int] = None
    characters: list[Optional[str]] = field(default_factory=lambda: [None] * 5)
    best_matches: list[Optional[str]] = field(default_factory=lambda: [None] * 5)
    portrait_distances: list[Optional[float]] = field(default_factory=lambda: [None] * 5)
    cell_powers: list[Optional[int]] = field(default_factory=lambda: [None] * 5)
    raw_ocr_lines: list[str] = field(default_factory=list)


@dataclass
class ArenaPreBattle:
    mode: str
    title: str
    user_team: TeamLineup
    opponent_team: TeamLineup
    raw_title_ocr: list[str] = field(default_factory=list)


@dataclass
class ArenaInfoTeam:
    """Champion Arena 'Arena Info' popup — one player + one round's team."""

    mode: str = "champion"
    player_username: Optional[str] = None
    round_index: Optional[int] = None
    total_power: Optional[int] = None
    team: TeamLineup = field(default_factory=TeamLineup)


@dataclass
class BattleRecordsHeader:
    """Lightweight Battle Records screen identification — just the round.

    The full per-matchup extractor lives in roster/battle_records.py; this
    dataclass is what arena_importer.py uses to associate a Battle Records
    screenshot with the right round of a Champions session before calling
    the heavier extractor.
    """

    mode: str = "champion_battle_record"
    round_index: Optional[int] = None
    raw_ocr_lines: list[str] = field(default_factory=list)


@dataclass
class ChampionsDuelResult:
    """Overall Champions Duel Result screen.

    Shown once per Duel (after all 5 rounds). May surface a winner badge
    (us vs opponent) and a per-round summary; for now we just record that
    this screenshot exists in the session — fine-grained parsing is not
    required for the upload flow.
    """

    mode: str = "champion_duel_result"
    user_won_overall: Optional[bool] = None
    raw_ocr_lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Title detection
# ---------------------------------------------------------------------------


# Iteration order matters — earlier keys win when multiple substrings match.
# Most-specific Champions subtypes come BEFORE the bare "champion" fallback so
# that a Battle Records screen (which has neither "champion" nor "cheer" in
# its title) and a Duel Result screen route to their dedicated handlers.
_TITLE_KEYWORDS = {
    "rookie": ["rookie arena"],
    "special": ["sp arena", "special arena"],
    # Per-round Battle Records screen (Champions). Lists 5 matchups with
    # damage / heal / take / win-loss icons. Full per-row extraction lives
    # in roster/battle_records.py.
    "champion_battle_record": ["battle records"],
    # Overall Champions Duel Result screen — the final aggregate (winner
    # badge + per-round mini-summaries).
    "champion_duel_result": ["champions duel result", "duel result"],
    # Champion 'Arena Info' loadout popup — shown for both your own picks
    # and your opponent's picks, one round at a time. Bare "champion" /
    # "cheer" keywords are kept as fallbacks for landing pages and edge
    # captures; the loadout extractor returns None on a mismatch so a
    # mis-routed file is harmless.
    "champion": ["arena info", "champion", "cheer"],
}


_PUNCT_STRIP_RE = re.compile(r"[^\w\s]")


def detect_title(image: Image.Image) -> tuple[str, list[str]]:
    """Return (mode, ocr_lines) where mode is one of the keys in _TITLE_KEYWORDS or 'unknown'.

    Title text is normalized (lowercase + non-word punctuation stripped) so
    minor OCR variations like ``Champions' Duel Result`` (curly apostrophe)
    vs ``Champions Duel Result`` (no apostrophe) both match the same key.
    """
    w, h = image.size
    # Scan the top 30% — Champions title popups can extend lower than the
    # other modes' title bars (modal headers vs in-screen banner).
    crop = image.crop((0, 0, w, int(h * 0.30)))
    regions = recognize(crop)
    lines = [r.text for r in regions]
    joined = _PUNCT_STRIP_RE.sub("", " ".join(lines).lower())
    for mode, kws in _TITLE_KEYWORDS.items():
        for kw in kws:
            if kw in joined:
                return mode, lines
    return "unknown", lines


# ---------------------------------------------------------------------------
# Region geometry (proportional, calibrated against 2732x2048 iPad)
# ---------------------------------------------------------------------------


# Calibrated against the user's 2732x2048 iPad screenshots. Coordinates are
# proportional to the FULL image, not the dialog. Re-tuned 2026-04-26 after
# saving crops to /tmp/arena_dbg and visually verifying portrait alignment.
_PREBATTLE_REGIONS = {
    "dialog": (0.32, 0.05, 0.68, 0.83),
    "title_strip": (0.32, 0.13, 0.68, 0.18),  # "Rookie Arena" / "SP Arena"
    "winter_vs_nika_strip": (0.32, 0.18, 0.68, 0.22),  # "WINTER VS NIKA"
    "top_team_strip": (0.32, 0.23, 0.68, 0.38),
    "top_power_strip": (0.32, 0.39, 0.68, 0.44),
    "vs_strip": (0.32, 0.44, 0.68, 0.48),
    "bottom_power_strip": (0.32, 0.46, 0.68, 0.50),
    "bottom_team_strip": (0.32, 0.50, 0.68, 0.66),
}

# Distance under which we treat a match as confident. The Vision feature
# embedding is a generic CNN output; arena cells are stylized art with UI
# overlays. Empirically (rookie-arena fixtures, 2026-04-26):
#   * confirmed correct matches cluster at 0.49–0.62
#   * uncertain / wrong matches sit at 0.65–1.00
# A pure threshold misses borderline correct matches (0.60–0.65). We
# additionally accept any rank-1 whose distance is at least RANK_GAP smaller
# than rank-2 — a clear winner is good evidence even when its absolute
# distance is mediocre.
CONFIDENT_DISTANCE = 0.62
RANK_GAP = 0.08

# Champion 'Arena Info' popup. Re-tuned 2026-05-03 against the
# `Full Champions Arena Example` fixture set (Player_1_Round_3.PNG):
#   ROUND 01..05 tabs:   x 0.346-0.651, y 0.482-0.498
#   per-cell powers row: y 0.684-0.702
# So the cards live between, roughly y 0.51-0.68. The header (player
# username + total power) sits above the round tabs at y 0.40-0.47.
_ARENA_INFO_REGIONS = {
    "dialog": (0.28, 0.28, 0.72, 0.78),
    "header_strip": (0.30, 0.40, 0.70, 0.47),  # username + player level
    "power_strip": (0.30, 0.34, 0.70, 0.40),   # "X 4203630" total power
    "round_tabs": (0.30, 0.475, 0.70, 0.510),  # "ROUND 01..05"
    # Kept for backward compat; new path uses _CHAMPION_TILE_BOXES below.
    "team_strip": (0.30, 0.510, 0.70, 0.700),  # 5 character cards
}

# Explicit per-tile boxes for the Champion 'Arena Info' loadout view.
# Derived empirically by the user via `nikkecopilot crop-tool` against
# `Player_1_Round_1.PNG` (slice #138, 2026-05-03). The 5 tiles share
# the same y range; x widths are ~0.063 with ~0.0044 inter-card gaps.
# Even-splitting an enclosing strip would bleed into those gaps because
# the cards aren't perfectly evenly distributed — using explicit boxes
# eliminates that drift.
#
# Each tuple is (x1, y1, x2, y2) image-relative fractions, the full
# card area (icon column + face + LV banner + name + stars), excluding
# the per-Nikke CP value below the card (captured separately).
_CHAMPION_TILE_BOXES: tuple[tuple[float, float, float, float], ...] = (
    (0.3331, 0.5200, 0.3960, 0.6772),
    (0.4008, 0.5200, 0.4641, 0.6772),
    (0.4682, 0.5200, 0.5315, 0.6772),
    (0.5359, 0.5200, 0.5996, 0.6772),
    (0.6040, 0.5200, 0.6673, 0.6772),
)

# Per-mode portrait sub-crop within a single cell. Pre-battle (rookie/special)
# cards are tall and the face sits in the LOWER half (y 0.30-0.85). For
# Champion the explicit tile boxes above already cover the full card, so
# we use an identity sub-crop (the box IS the portrait crop).
_PORTRAIT_BOX_PREBATTLE = (0.28, 0.30, 0.95, 0.85)
_PORTRAIT_BOX_CHAMPION = (0.0, 0.0, 1.0, 1.0)


def _crop_proportional(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    w, h = image.size
    x1, y1, x2, y2 = box
    return image.crop((int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)))


def _crop_grid_cells(image: Image.Image, *, cols: int = 5) -> list[Image.Image]:
    w, h = image.size
    cell_w = w // cols
    cells = []
    for c in range(cols):
        cells.append(image.crop((c * cell_w, 0, (c + 1) * cell_w, h)))
    return cells


# ---------------------------------------------------------------------------
# Power number extraction
# ---------------------------------------------------------------------------


_POWER_RE = re.compile(r"(\d{2}[\d,]{3,})")
# Per-cell CP can be 4-7 digits (~3,000 — ~1,000,000+). Looser than team-total.
_CELL_POWER_RE = re.compile(r"(\d[\d,]{3,})")


def _ocr_power(image: Image.Image) -> Optional[int]:
    regions = recognize(image)
    text = " ".join(r.text for r in regions)
    m = _POWER_RE.search(text.replace(" ", ""))
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


# Strip within each cell where the CP label is rendered. Below the portrait
# (which ends at y≈0.85) but above the bottom rim — y 0.85-1.00.
_CELL_POWER_STRIP = (0.05, 0.85, 0.95, 1.00)


def _ocr_cell_power(cell: Image.Image) -> Optional[int]:
    """Extract the per-Nikke CP shown under one arena portrait card.

    Returns the integer CP or None if OCR can't find a plausible number.
    The strip is the bottom slice of the cell where the in-game UI
    renders the CP value (e.g. '462,878' under Red Hood).
    """
    cw, ch = cell.size
    sx1, sy1, sx2, sy2 = _CELL_POWER_STRIP
    strip = cell.crop(
        (int(cw * sx1), int(ch * sy1), int(cw * sx2), int(ch * sy2))
    )
    regions = recognize(strip)
    text = " ".join(r.text for r in regions)
    m = _CELL_POWER_RE.search(text.replace(" ", ""))
    if not m:
        return None
    try:
        v = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # Sanity-bound: legitimate Nikke CP is 1k–2M. Reject obvious OCR garbage.
    if 1_000 <= v <= 2_000_000:
        return v
    return None


_USERNAME_RE = re.compile(r"([A-Z][A-Z0-9_]{2,})\s*(?:vs|VS)\s*([A-Z][A-Z0-9_]{2,})")


def _parse_usernames(lines: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Parse 'WINTER VS NIKA' style header into (left, right)."""
    joined = " ".join(lines)
    m = _USERNAME_RE.search(joined)
    if m:
        return m.group(1), m.group(2)
    return None, None


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def extract_pre_battle(
    image_path: Path,
    matcher: PortraitMatcher,
    *,
    user_username: Optional[str] = None,
) -> Optional[ArenaPreBattle]:
    image = Image.open(image_path).convert("RGB")
    mode, title_lines = detect_title(image)
    if mode not in ("rookie", "special"):
        log.info("title %r doesn't look like a pre-battle (mode=%s)", title_lines, mode)
        return None

    top_team_img = _crop_proportional(image, _PREBATTLE_REGIONS["top_team_strip"])
    bottom_team_img = _crop_proportional(image, _PREBATTLE_REGIONS["bottom_team_strip"])
    top_power_img = _crop_proportional(image, _PREBATTLE_REGIONS["top_power_strip"])
    bottom_power_img = _crop_proportional(image, _PREBATTLE_REGIONS["bottom_power_strip"])

    top_lineup = _resolve_team(top_team_img, matcher)
    top_lineup.power = _ocr_power(top_power_img)
    bottom_lineup = _resolve_team(bottom_team_img, matcher)
    bottom_lineup.power = _ocr_power(bottom_power_img)

    left_user, right_user = _parse_usernames(title_lines)
    top_lineup.player_username = left_user
    bottom_lineup.player_username = right_user

    user = (
        bottom_lineup
        if user_username and bottom_lineup.player_username == user_username
        else top_lineup
        if user_username and top_lineup.player_username == user_username
        else bottom_lineup  # heuristic: bottom team is normally the user's
    )
    opponent = top_lineup if user is bottom_lineup else bottom_lineup

    return ArenaPreBattle(
        mode=mode,
        title=title_lines[0] if title_lines else "",
        user_team=user,
        opponent_team=opponent,
        raw_title_ocr=title_lines,
    )


def extract_champion_arena_info(
    image_path: Path,
    matcher: PortraitMatcher,
) -> Optional[ArenaInfoTeam]:
    image = Image.open(image_path).convert("RGB")
    mode, title_lines = detect_title(image)
    if mode != "champion":
        return None

    # Header strip contains the player username + total power
    header_img = _crop_proportional(image, _ARENA_INFO_REGIONS["header_strip"])
    header_regions = recognize(header_img)
    header_text = [r.text for r in header_regions]

    # Slice #138: use explicit per-tile boxes for the 5 cards instead
    # of the legacy strip+grid+portrait pattern, which drifted at the
    # outer slots due to inter-card gaps.
    lineup = _resolve_champion_tiles(image, matcher)
    power_img = _crop_proportional(image, _ARENA_INFO_REGIONS["power_strip"])
    total_power = _ocr_power(power_img)

    # Username — try the all-caps ASCII heuristic first, then fall back to
    # any non-empty header token (handles non-ASCII usernames like Chinese
    # or Japanese characters that the all-caps test rejects).
    username = _pick_player_username(header_text)

    # Round index — the "ROUND 01..05" tabs all render at the top of the
    # team strip. The ACTIVE tab is highlighted (saturated purple box);
    # picking the first OCR'd label always returns 01. We detect the
    # active one by sampling per-tab background saturation.
    round_idx = _detect_active_round_tab(image)

    return ArenaInfoTeam(
        player_username=username,
        round_index=round_idx,
        total_power=total_power,
        team=lineup,
    )


_USERNAME_NOISE = {
    "NIKA", "ROUND", "TOP", "GROUP", "ARENA", "INFO",
    "WIN", "LOSS", "VS", "DUEL", "RESULT", "PREVIOUS", "SEASON",
    "WINNER", "BATTLE", "RECORDS", "CHAMPIONS", "CHAMPION",
    "EXIT", "BACK", "REWARD", "RANKING",
}

# Tokens / phrases the fallback "any text token" pass should also reject.
# Includes multi-word in-game UI labels that the all-caps test passes
# through (e.g. "Previous Season" sits next to the player name).
_USERNAME_NOISE_PHRASES = {
    "previous season", "previous season winner", "season winner",
    "battle result", "champions duel", "champions duel result",
    "duel result", "battle records", "arena info", "previous",
}


def _pick_player_username(header_text: list[str]) -> Optional[str]:
    """Pick the most-username-like token from header OCR.

    Two-pass: first prefer the all-caps ASCII heuristic (matches in-game
    English usernames), then fall back to any non-empty token that isn't
    obvious noise. The fallback handles Chinese / Japanese / Korean
    usernames the all-caps test rejects, plus mixed-case display names.
    """
    # Pass 1: classic all-caps ASCII tokens (high signal, low noise).
    for t in header_text:
        cleaned = t.strip()
        if (
            cleaned.isupper()
            and cleaned.isalpha()
            and 3 <= len(cleaned) <= 20
            and cleaned not in _USERNAME_NOISE
        ):
            return cleaned
    # Pass 2: any non-empty, non-noise token. Skip obviously numeric
    # tokens (CP values rendered as bare numbers near the username).
    for t in header_text:
        cleaned = t.strip()
        if not cleaned or cleaned.isdigit() or len(cleaned) > 30:
            continue
        if cleaned.upper() in _USERNAME_NOISE:
            continue
        if cleaned.lower() in _USERNAME_NOISE_PHRASES:
            continue
        # Skip tokens that are pure punctuation / symbols.
        if not any(c.isalnum() for c in cleaned):
            continue
        return cleaned
    return None


def _detect_active_round_tab(image: Image.Image) -> Optional[int]:
    """Find which of ROUND 01..05 is the active (highlighted) tab.

    All five round tabs render in a horizontal strip; the active one has
    a saturated purple/blue background while inactives are gray. Strategy:

      1. OCR the round_tabs strip. Each tab produces a "ROUND 0X" hit
         (sometimes mis-OCR'd as "ROUND U" / "ROUND O", or just "ROUND"
         when the digit confidence is low).
      2. When 5+ candidate tabs are found, sort by x position. The
         POSITION (1..5 from left to right) is the canonical round
         number — ignore the OCR'd digit, which is unreliable.
      3. Sample HSV saturation behind each tab; the highest-saturation
         column is the active one.

    Returns None when fewer than ~3 tabs are detected (likely wrong
    region geometry — caller logs and falls back to None round_index).
    """
    region_box = _ARENA_INFO_REGIONS["round_tabs"]
    strip = _crop_proportional(image, region_box)
    regions = recognize(strip)

    # Collect bboxes for every region whose text starts with "ROUND".
    # The mis-OCR'd cases ("ROUND U" / "ROUND O" for "ROUND 01") all
    # still start with "ROUND".
    tab_bboxes: list[tuple[int, int, int, int]] = []
    for r in regions:
        if re.match(r"^ROUND\b", r.text, re.I):
            tab_bboxes.append(r.bbox)
    if len(tab_bboxes) < 3:
        return None

    # Sort left-to-right; position index becomes the round number.
    tab_bboxes.sort(key=lambda b: b[0])

    # Sample HSV saturation around each tab's bbox to find the active one.
    sw, sh = strip.size
    hsv_strip = strip.convert("HSV")
    saturations: list[float] = []
    for x, y, w, h in tab_bboxes:
        sx1 = max(0, x - w // 4)
        sy1 = max(0, y - h)
        sx2 = min(sw, x + w + w // 4)
        sy2 = min(sh, y + h * 2)
        if sx2 <= sx1 or sy2 <= sy1:
            saturations.append(0.0)
            continue
        sample = hsv_strip.crop((sx1, sy1, sx2, sy2))
        sat_band = sample.getchannel("S")
        # PIL.Image.getdata() is deprecated in Pillow 14+; bytes() yields
        # the same flat sequence and is forward-compatible.
        pixels = bytes(sat_band.tobytes())
        saturations.append((sum(pixels) / len(pixels)) if pixels else 0.0)

    # Active tab is the one with the highest saturation. Position
    # (1-indexed) is its order from the left.
    if not saturations:
        return None
    active_pos = saturations.index(max(saturations)) + 1
    # Clamp to 1..5 (Champions has exactly 5 rounds; if OCR returned 6+
    # spurious "ROUND" hits, keep the 5 leftmost as the canonical tabs).
    if 1 <= active_pos <= 5:
        return active_pos
    return None


def _resolve_champion_tiles(
    image: Image.Image, matcher: PortraitMatcher,
) -> TeamLineup:
    """Match the 5 Champion 'Arena Info' cards using explicit tile boxes.

    Slice #138: replaces the legacy `_resolve_team(team_strip, _crop_grid_cells, portrait_box)`
    pipeline for Champion mode. Each tile box is a precise full-card crop
    (icon column + face + LV banner + name + stars) — derived empirically
    via the crop-tool — so we don't get drift at the outer slots from
    inter-card gaps.
    """
    chars: list[Optional[str]] = []
    best: list[Optional[str]] = []
    distances: list[Optional[float]] = []
    cell_powers: list[Optional[int]] = []
    for box in _CHAMPION_TILE_BOXES:
        portrait = _crop_proportional(image, box)
        top = matcher.match(portrait, top_k=2)
        if not top:
            chars.append(None)
            best.append(None)
            distances.append(None)
        else:
            rank1 = top[0]
            best.append(rank1.character_name)
            distances.append(rank1.distance)
            confident = rank1.distance <= CONFIDENT_DISTANCE
            if not confident and len(top) >= 2:
                confident = (top[1].distance - rank1.distance) >= RANK_GAP
            chars.append(rank1.character_name if confident else None)
        # Per-cell CP — the CP value renders in a strip BELOW the tile
        # box (y ≈ 0.685-0.715 of the full image). Crop a thin strip
        # of equal width directly under each tile and OCR it.
        x1, _, x2, _ = box
        w, h = image.size
        cp_crop = image.crop((
            int(x1 * w), int(0.685 * h),
            int(x2 * w), int(0.715 * h),
        ))
        cell_powers.append(_ocr_cell_power_strip(cp_crop))
    return TeamLineup(
        characters=chars,
        best_matches=best,
        portrait_distances=distances,
        cell_powers=cell_powers,
    )


def _ocr_cell_power_strip(strip: Image.Image) -> Optional[int]:
    """OCR a thin per-tile CP strip; returns the integer or None.

    Slice #138: simpler variant of `_ocr_cell_power` without the cell-
    relative sub-crop math (the caller already passed the right strip).
    """
    regions = recognize(strip)
    text = " ".join(r.text for r in regions)
    m = _CELL_POWER_RE.search(text.replace(" ", ""))
    if not m:
        return None
    try:
        v = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if 1_000 <= v <= 2_000_000:
        return v
    return None


def extract_battle_records_round(image_path: Path) -> Optional[BattleRecordsHeader]:
    """Identify a Battle Records screen and pull the round number.

    The full per-matchup extraction (per-Nikke damage / heal / take, win
    icon) lives in ``roster/battle_records.py``. This helper is the cheap
    "is this the right kind of screen, and which round?" check the importer
    uses to bucket a file before paying the heavier OCR cost.
    """
    image = Image.open(image_path).convert("RGB")
    mode, title_lines = detect_title(image)
    if mode != "champion_battle_record":
        return None
    # Round indicator typically appears near the top of the screen
    # (e.g. "ROUND 03"). Reuse the same OCR scan we already ran.
    full_ocr = recognize(image)
    round_idx: Optional[int] = None
    for r in full_ocr:
        m = re.search(r"ROUND\s*0?(\d)", r.text, re.I)
        if m:
            round_idx = int(m.group(1))
            break
    return BattleRecordsHeader(round_index=round_idx, raw_ocr_lines=title_lines)


def extract_champions_duel_result(image_path: Path) -> Optional[ChampionsDuelResult]:
    """Identify a Champions Duel Result screen.

    Returns the dataclass when the title matches; outcome inference (which
    side won overall) is best-effort — Champions Duel Result lays out a
    winner badge near the center but the layout shifts between
    portrait/landscape captures, so we don't promise a value.
    """
    image = Image.open(image_path).convert("RGB")
    mode, title_lines = detect_title(image)
    if mode != "champion_duel_result":
        return None
    return ChampionsDuelResult(
        user_won_overall=None,
        raw_ocr_lines=title_lines,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_team(
    team_img: Image.Image,
    matcher: PortraitMatcher,
    *,
    portrait_box: tuple[float, float, float, float] = _PORTRAIT_BOX_PREBATTLE,
) -> TeamLineup:
    """Match every cell in a 5-character team strip to a character.

    ``portrait_box`` controls the per-cell sub-crop that gets fed to the
    matcher — different arena modes lay the cards out differently, so the
    pre-battle vs. champion screens use different boxes.
    """
    cells = _crop_grid_cells(team_img, cols=5)
    chars: list[Optional[str]] = []
    best: list[Optional[str]] = []
    distances: list[Optional[float]] = []
    cell_powers: list[Optional[int]] = []
    px1, py1, px2, py2 = portrait_box
    for cell in cells:
        cw, ch = cell.size
        portrait = cell.crop(
            (int(cw * px1), int(ch * py1), int(cw * px2), int(ch * py2))
        )
        # Pull top-2 matches so we can apply the rank-gap heuristic alongside
        # the absolute distance threshold.
        top = matcher.match(portrait, top_k=2)
        if not top:
            chars.append(None)
            best.append(None)
            distances.append(None)
        else:
            rank1 = top[0]
            best.append(rank1.character_name)
            distances.append(rank1.distance)
            confident = rank1.distance <= CONFIDENT_DISTANCE
            if not confident and len(top) >= 2:
                # Clear winner: rank-1 is meaningfully closer than rank-2.
                confident = (top[1].distance - rank1.distance) >= RANK_GAP
            chars.append(rank1.character_name if confident else None)
        # Per-cell CP from the bottom strip. None if OCR fails — UI surfaces
        # absent values as '—'. Independent of portrait match.
        cell_powers.append(_ocr_cell_power(cell))
    return TeamLineup(
        characters=chars,
        best_matches=best,
        portrait_distances=distances,
        cell_powers=cell_powers,
    )
