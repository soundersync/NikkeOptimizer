"""Tests for the BlablaLink-driven predicted stats wired into scoring."""

from __future__ import annotations

import pytest

from nikke_optimizer.data.scrapers.blablalink import (
    DEFAULT_LANG,
    cache_path_for_roledata,
)
from nikke_optimizer.optimizer.loader import _predict_base_stats
from nikke_optimizer.optimizer.scoring import _effective_power
from nikke_optimizer.optimizer.models import CharacterView
from nikke_optimizer.data.enums import BurstType, Element, Rarity, WeaponClass


def _require_cached(resource_id: int) -> None:
    if not cache_path_for_roledata(str(resource_id), DEFAULT_LANG).is_file():
        pytest.skip(
            f"resource_id={resource_id} not cached; "
            f"run `nikkeoptimizer fetch-roledata {resource_id}`"
        )


def test_predict_base_stats_returns_positive_for_known_character():
    _require_cached(90)  # Emma
    atk, hp, defv, power = _predict_base_stats(
        "Emma",
        level=200,
        grade=3,
        core=7,
        skill1_level=10,
        skill2_level=10,
        burst_skill_level=10,
    )
    assert atk is not None and atk > 0
    assert hp is not None and hp > 0
    assert defv is not None and defv > 0
    assert power is not None and power > 0


def test_predict_base_stats_unknown_name_returns_none():
    out = _predict_base_stats(
        "ThisCharacterDoesNotExistAnywhere",
        level=1, grade=0, core=0,
        skill1_level=1, skill2_level=1, burst_skill_level=1,
    )
    assert out == (None, None, None, None)


def test_effective_power_uses_captured_power_when_owned():
    v = CharacterView(
        name="Emma", rarity=Rarity.SSR, element=Element.FIRE,
        weapon_class=WeaponClass.MG, burst_type=BurstType.I,
        owned=True, power=12345, predicted_power=99999,
    )
    assert _effective_power(v) == 12345


def test_effective_power_falls_back_to_predicted_for_unowned():
    v = CharacterView(
        name="Emma", rarity=Rarity.SSR, element=Element.FIRE,
        weapon_class=WeaponClass.MG, burst_type=BurstType.I,
        owned=False, power=0, predicted_power=99999,
    )
    assert _effective_power(v) == 99999


def test_effective_power_returns_zero_when_neither_available():
    v = CharacterView(
        name="Emma", rarity=Rarity.SSR, element=Element.FIRE,
        weapon_class=WeaponClass.MG, burst_type=BurstType.I,
        owned=False, power=0, predicted_power=None,
    )
    assert _effective_power(v) == 0
