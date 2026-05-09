"""Tests for account-state research → buff-dict derivation."""

from __future__ import annotations

from nikke_optimizer.data.models import AccountState
from nikke_optimizer.simulator import account_buffs


def _state_with(**kwargs) -> AccountState:
    """Build an AccountState with overrides."""
    return AccountState(id=1, **kwargs)


def test_class_buff_attacker_observed_rates():
    """Attacker R179 → HP 134250, DEF 895, ATK 0 (real in-game value)."""
    s = _state_with(class_attacker_level=179)
    assert account_buffs.class_buff(s, "Attacker") == {"atk": 0, "hp": 134250, "def": 895}


def test_class_buff_defender_observed_rates():
    """Defender R172 → HP 129000, DEF 860, ATK 0 (real in-game value)."""
    s = _state_with(class_defender_level=172)
    assert account_buffs.class_buff(s, "Defender") == {"atk": 0, "hp": 129000, "def": 860}


def test_class_buff_supporter_uses_supporter_level():
    s = _state_with(class_supporter_level=171)
    assert account_buffs.class_buff(s, "Supporter") == {"atk": 0, "hp": 750 * 171, "def": 5 * 171}


def test_class_buff_healer_falls_back_to_supporter():
    """NIKKE has no separate Healer research — Healers use Supporter."""
    s = _state_with(class_supporter_level=100)
    assert account_buffs.class_buff(s, "Healer") == account_buffs.class_buff(s, "Supporter")


def test_class_buff_unknown_class_returns_zero():
    s = _state_with(class_attacker_level=200)
    assert account_buffs.class_buff(s, "WhoKnows") == {"atk": 0, "hp": 0, "def": 0}


def test_manufacturer_buff_pilgrim_observed_rates():
    """Pilgrim R167 → ATK 4175, DEF 835, HP 0 (real in-game value)."""
    s = _state_with(mfr_pilgrim_level=167)
    assert account_buffs.manufacturer_buff(s, "Pilgrim") == {"atk": 4175, "hp": 0, "def": 835}


def test_manufacturer_buff_case_insensitive():
    s = _state_with(mfr_elysion_level=169)
    assert account_buffs.manufacturer_buff(s, "elysion") == account_buffs.manufacturer_buff(s, "Elysion")
    assert account_buffs.manufacturer_buff(s, "ELYSION") == account_buffs.manufacturer_buff(s, "Elysion")


def test_manufacturer_buff_none_returns_zero():
    s = _state_with(mfr_tetra_level=200)
    assert account_buffs.manufacturer_buff(s, None) == {"atk": 0, "hp": 0, "def": 0}


def test_general_research_observed_rate():
    """General Research LV300 → +135000 HP (= 450 HP/level × 300)."""
    s = _state_with(general_research_level=300)
    assert account_buffs.general_research_buff(s) == {"atk": 0, "hp": 135000, "def": 0}


def test_general_research_zero_at_level_zero():
    s = _state_with(general_research_level=0)
    assert account_buffs.general_research_buff(s) == {"atk": 0, "hp": 0, "def": 0}


def test_per_level_rates_are_linear():
    """Doubling the level doubles the buff."""
    a = _state_with(class_attacker_level=100)
    b = _state_with(class_attacker_level=200)
    ba = account_buffs.class_buff(a, "Attacker")
    bb = account_buffs.class_buff(b, "Attacker")
    for k in ("atk", "hp", "def"):
        assert bb[k] == 2 * ba[k]
