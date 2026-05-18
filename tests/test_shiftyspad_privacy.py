"""Regression tests for the conservative roster-privacy detection.

Pre-fix bug: when GetUserCharacters didn't land (XHR timeout, page
hydrated slowly, etc.), ``is_roster_private`` stayed at its default
``False`` — making the UI claim "Nikkes public" for players who were
actually private. Caught after the season-29 scrape silently mis-tagged
CHIGLETS, LUCARNE, NANA, BECHO, RUSTY.
"""

from __future__ import annotations

import pytest

from nikke_optimizer.data.scrapers.shiftyspad import (
    PRIVATE_NIKKE_INFO_CODE,
    _derive_roster_state,
)


def test_xhr_missing_treated_as_private():
    """The original silent-failure mode — XHR never landed."""
    private, chars = _derive_roster_state(None)
    assert private is True
    assert chars == []


def test_explicit_private_code():
    private, chars = _derive_roster_state(
        {"code": PRIVATE_NIKKE_INFO_CODE, "msg": "user not allow show nikkeinfo"}
    )
    assert private is True
    assert chars == []


def test_code_zero_with_non_empty_characters_is_public():
    body = {
        "code": 0,
        "data": {"characters": [{"name_code": 5004, "lv": 200, "combat": 150000}]},
    }
    private, chars = _derive_roster_state(body)
    assert private is False
    assert len(chars) == 1
    assert chars[0]["name_code"] == 5004


def test_code_zero_with_empty_characters_is_treated_as_private():
    """Active players always own >=1 NIKKE; empty list with code=0
    means hydration didn't complete."""
    private, chars = _derive_roster_state({"code": 0, "data": {"characters": []}})
    assert private is True
    assert chars == []


def test_code_zero_with_missing_data_block_is_private():
    private, chars = _derive_roster_state({"code": 0})
    assert private is True
    assert chars == []


def test_unknown_error_code_is_private():
    """Any non-zero, non-1301002 code is treated conservatively."""
    private, chars = _derive_roster_state({"code": 9999, "msg": "server error"})
    assert private is True
    assert chars == []


@pytest.mark.parametrize("code", [1, -1, 500, 1301003])
def test_other_codes_default_private(code):
    private, chars = _derive_roster_state({"code": code})
    assert private is True
    assert chars == []
