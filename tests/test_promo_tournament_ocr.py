"""Unit tests for the OCR pipeline's pure helpers.

PaddleOCR itself is not exercised here — the helpers being tested are
the slug classifier, number / percent normalizers, the round-strip
WIN/LOSE position parser, and the character fuzzy matcher. They run
without PaddleOCR + numpy + Pillow, so this suite stays fast.
"""

from __future__ import annotations

import pytest

from nikke_optimizer.roster.promo_tournament_ocr import (
    CharIndex,
    classify_slug,
    match_character,
    normalize_number,
    normalize_percent,
    parse_round_winner,
)


# ---------------------------------------------------------------------------
# classify_slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug,expected",
    [
        # Skipped (image-only) regions.
        ("char1.portrait", "skip"),
        ("char3.doll", "skip"),
        ("char5.portrait", "skip"),
        # LB stars + Core badge — color + targeted OCR.
        ("char1.lb_core", "lb_core"),
        ("char5.lb_core", "lb_core"),
        # Number fields (CP, atk, def, heal).
        ("team_cp", "number"),
        ("char1.cp", "number"),
        ("char5.cp", "number"),
        ("left.char1.atk", "number"),
        ("right.char3.def", "number"),
        ("left.char5.heal", "number"),
        # Percent fields.
        ("left.char1.hp", "percent"),
        ("right.char5.hp", "percent"),
        # Character names.
        ("left.char1.name", "char_name"),
        ("right.char3.name", "char_name"),
        # Round strips.
        ("round1_strip", "round_strip"),
        ("round5_strip", "round_strip"),
        # Plain text.
        ("player_name", "text"),
        ("winner_name", "text"),
        ("left_name", "text"),
        ("right_name", "text"),
    ],
)
def test_classify_slug(slug: str, expected: str):
    assert classify_slug(slug) == expected


# ---------------------------------------------------------------------------
# Number / percent normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3,587,616", "3587616"),
        ("142 887", "142887"),               # space separator → concat
        ("3587616", "3587616"),
        ("100", "100"),
        ("CP: 1,000,000", "1000000"),
        ("630,336 0", "630336"),             # icon-as-digit drops out
        ("99,157 1", "99157"),
        ("117,866 |", "117866"),
        ("* 820,404", "820404"),             # leading icon
        ("--", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_number(raw, expected):
    assert normalize_number(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("100.00%", "100.00%"),
        ("0.00%", "0.00%"),
        ("0%", "0%"),
        ("100%", "100%"),
        ("HP 87.5%", "87.5%"),
        ("disconnected", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_percent(raw, expected):
    assert normalize_percent(raw) == expected


# ---------------------------------------------------------------------------
# parse_round_winner
# ---------------------------------------------------------------------------


def _bbox(x_center: float, y: float = 100, half_w: float = 30, half_h: float = 12):
    """Helper — build a 4-corner bbox centered at (x_center, y)."""
    return [
        [x_center - half_w, y - half_h],
        [x_center + half_w, y - half_h],
        [x_center + half_w, y + half_h],
        [x_center - half_w, y + half_h],
    ]


def test_parse_round_winner_left_won():
    items = [
        (_bbox(150), "ROUND 01", 0.95),
        (_bbox(400), "WIN", 0.99),
        (_bbox(750), "LOSE", 0.99),
    ]
    assert parse_round_winner(items) == "left"


def test_parse_round_winner_right_won():
    items = [
        (_bbox(150), "ROUND 03", 0.95),
        (_bbox(420), "LOSE", 0.99),
        (_bbox(770), "WIN", 0.99),
    ]
    assert parse_round_winner(items) == "right"


def test_parse_round_winner_missing_lose():
    items = [(_bbox(400), "WIN", 0.99)]
    assert parse_round_winner(items) is None


def test_parse_round_winner_missing_win():
    items = [(_bbox(750), "LOSE", 0.99)]
    assert parse_round_winner(items) is None


def test_parse_round_winner_empty():
    assert parse_round_winner([]) is None


def test_parse_round_winner_uppercase_lower():
    """OCR sometimes returns mixed case — parser uppercases internally."""
    items = [
        (_bbox(400), "Win", 0.95),
        (_bbox(750), "lose", 0.95),
    ]
    assert parse_round_winner(items) == "left"


# ---------------------------------------------------------------------------
# match_character — needs rapidfuzz
# ---------------------------------------------------------------------------


@pytest.fixture
def char_index() -> CharIndex:
    """A small deterministic index covering common edge cases."""
    return CharIndex(
        entries=(
            (1, "Anis"),
            (2, "Anis: Sparkling Summer"),
            (3, "Snow White"),
            (4, "Snow White: Innocent Days"),
            (5, "Liberalio"),
            (6, "Cinderella"),
            (7, "Pascal"),
            (8, "Bay"),
            (9, "Rumani"),
            # Alt-form regression cases (without these in the index, the
            # WRatio-tied bug couldn't be reproduced in tests).
            (10, "Vesti"),
            (11, "Vesti: Tactical Upgrade"),
            (12, "Eunhwa"),
            (13, "Eunhwa: Tactical Upgrade"),
            (14, "Soline"),
            (15, "Soline: Frost Ticket"),
            (16, "Maiden"),
            (17, "Maiden: Ice Rose"),
        )
    )


def test_match_character_exact(char_index: CharIndex):
    res = match_character("Anis", char_index)
    assert res is not None
    cid, name, score = res
    assert cid == 1 and name == "Anis"
    assert score >= 99


def test_match_character_truncated(char_index: CharIndex):
    """OCR sometimes truncates the trailing letter ('Liberalio' → 'Liberali')."""
    res = match_character("Liberali", char_index)
    assert res is not None
    cid, name, _ = res
    assert cid == 5 and name == "Liberalio"


def test_match_character_short_form_prefers_base(char_index: CharIndex):
    """'Snow White' should beat 'Snow White: Innocent Days' on a shorter input."""
    res = match_character("Snow White", char_index)
    assert res is not None
    cid, name, _ = res
    assert cid == 3 and name == "Snow White"


def test_match_character_no_match(char_index: CharIndex):
    assert match_character("Definitely Not A Nikke", char_index) is None


def test_match_character_empty_input(char_index: CharIndex):
    assert match_character("", char_index) is None
    assert match_character(None, char_index) is None


def test_match_character_empty_index():
    empty = CharIndex(entries=())
    assert match_character("Anis", empty) is None


# ---------------------------------------------------------------------------
# Alt-form regression — the bug that prompted the fix
# ---------------------------------------------------------------------------


def test_match_alt_form_truncated_tactical(char_index: CharIndex):
    """`'Vesti: Tactical'` (in-game UI truncates "Upgrade") must resolve
    to the alt-form, NOT the base 'Vesti'."""
    res = match_character("Vesti: Tactical", char_index)
    assert res is not None
    cid, name, _ = res
    assert name == "Vesti: Tactical Upgrade"
    assert cid == 11


def test_match_alt_form_heavy_truncation(char_index: CharIndex):
    """Heavily truncated alt-form ('Eunhwa: Tactic') still beats the base."""
    res = match_character("Eunhwa: Tactic", char_index)
    assert res is not None
    _, name, _ = res
    assert name == "Eunhwa: Tactical Upgrade"


def test_match_alt_form_multiple_words(char_index: CharIndex):
    res = match_character("Soline: Frost Ti", char_index)
    assert res is not None
    _, name, _ = res
    assert name == "Soline: Frost Ticket"


def test_match_alt_form_short_alt(char_index: CharIndex):
    res = match_character("Maiden: Ice Rose", char_index)
    assert res is not None
    _, name, _ = res
    assert name == "Maiden: Ice Rose"


def test_match_alt_form_anis_sparkling(char_index: CharIndex):
    """`'Anis: Sparkling'` (truncated alt) must NOT regress to base 'Anis'."""
    res = match_character("Anis: Sparkling", char_index)
    assert res is not None
    _, name, _ = res
    assert name == "Anis: Sparkling Summer"


def test_base_name_stays_base_when_no_colon(char_index: CharIndex):
    """`'Anis'` alone must still match base, not the alt."""
    res = match_character("Anis", char_index)
    assert res is not None
    _, name, _ = res
    assert name == "Anis"


def test_base_name_snow_white_stays_base(char_index: CharIndex):
    res = match_character("Snow White", char_index)
    assert res is not None
    _, name, _ = res
    assert name == "Snow White"
