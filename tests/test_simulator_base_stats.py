"""Tests for the BlablaLink-sourced base stat tables.

These tests rely on real cached roledata under
``<user_data_dir>/blablalink/<lang>/roledata/``. Tests skip cleanly if
the cache is missing — CI envs without the mirrored data won't fail.
"""

from __future__ import annotations

import pytest

from nikke_optimizer.data.scrapers.blablalink import (
    DEFAULT_LANG,
    cache_path_for_roledata,
)
from nikke_optimizer.simulator.base_stats import (
    BaseStats,
    list_cached_resource_ids,
)


def _require_cached(resource_id: int) -> None:
    if not cache_path_for_roledata(str(resource_id), DEFAULT_LANG).is_file():
        pytest.skip(
            f"resource_id={resource_id} not cached; "
            f"run `nikkeoptimizer fetch-roledata {resource_id}`"
        )


def test_emma_base_stats_at_level_1_no_lb_no_core():
    """Emma at LV1, grade=0, core=0 should equal the level-1 lookup."""
    _require_cached(90)  # Emma
    bs = BaseStats.from_cache(90)
    stats = bs.compute(level=1, grade=0, core=0)
    # No multipliers active — should be exactly the level-1 list values.
    assert stats["atk"] == bs.attack_list[0]
    assert stats["hp"] == bs.hp_list[0]
    assert stats["def"] == bs.defence_list[0]


def test_emma_grade_zero_core_zero_is_unchanged_at_max_level():
    _require_cached(90)
    bs = BaseStats.from_cache(90)
    stats = bs.compute(level=bs.max_level, grade=0, core=0)
    assert stats["atk"] == bs.attack_list[-1]
    assert stats["hp"] == bs.hp_list[-1]
    assert stats["def"] == bs.defence_list[-1]


def test_core_multiplier_is_2_percent_per_level():
    """All NIKKE characters use 200 basis points per core level (= 2%)."""
    _require_cached(90)
    bs = BaseStats.from_cache(90)
    base = bs.compute(level=200, grade=0, core=0)
    with_core_7 = bs.compute(level=200, grade=0, core=7)
    # Each stat should be ~14% higher (7 cores * 2% = 14%)
    for stat in ("atk", "hp", "def"):
        ratio = with_core_7[stat] / base[stat]
        assert 1.139 < ratio < 1.141, f"{stat} ratio {ratio} not ≈ 1.14"


def test_grade_applies_both_multiplicative_and_flat():
    """Limit-break adds (grade_ratio * grade) multiplier AND flat grade_<stat>."""
    _require_cached(90)
    bs = BaseStats.from_cache(90)
    no_lb = bs.compute(level=200, grade=0, core=0)
    full_lb = bs.compute(level=200, grade=3, core=0)
    # Should be strictly higher; exact multiplier is per-character but
    # the standard SSR is grade_ratio=200 (= 2% per LB) + flat additions.
    for stat in ("atk", "hp", "def"):
        assert full_lb[stat] > no_lb[stat]


def test_level_must_be_in_range():
    _require_cached(90)
    bs = BaseStats.from_cache(90)
    with pytest.raises(ValueError):
        bs.compute(level=0)
    with pytest.raises(ValueError):
        bs.compute(level=bs.max_level + 1)


def test_emma_metadata_round_trip():
    _require_cached(90)
    bs = BaseStats.from_cache(90)
    assert bs.resource_id == 90
    assert bs.name == "Emma"
    assert bs.rare == "SSR"
    assert bs.char_class == "Supporter"
    assert bs.max_level == 1200


def test_class_attackers_share_stat_curves():
    """Maxwell + the standard SSR Attacker baseline (sed_id=5101) share
    the same per-level table — different characters, same archetype."""
    if not (
        cache_path_for_roledata("150", DEFAULT_LANG).is_file()
        and cache_path_for_roledata("200", DEFAULT_LANG).is_file()
    ):
        pytest.skip("Julia (150) and Rupee (200) not both cached")
    julia = BaseStats.from_cache(150)
    rupee = BaseStats.from_cache(200)
    # Same class baseline → same per-level curves
    assert julia.attack_list == rupee.attack_list
    assert julia.hp_list == rupee.hp_list
    assert julia.defence_list == rupee.defence_list


def test_compute_power_is_positive_and_scales_with_level():
    _require_cached(90)
    bs = BaseStats.from_cache(90)
    p_low = bs.compute_power(level=50, grade=0, core=0)
    p_high = bs.compute_power(level=500, grade=3, core=7)
    assert p_low > 0
    assert p_high > p_low * 5  # high-investment power should dominate


def test_list_cached_resource_ids_returns_sorted_ints():
    ids = list_cached_resource_ids()
    assert ids == sorted(ids)
    assert all(isinstance(i, int) for i in ids)


def test_resolve_resource_id_by_name_exact_match():
    from nikke_optimizer.simulator.base_stats import resolve_resource_id_by_name

    assert resolve_resource_id_by_name("Emma") == 90


def test_resolve_resource_id_by_name_case_insensitive():
    from nikke_optimizer.simulator.base_stats import resolve_resource_id_by_name

    assert resolve_resource_id_by_name("EMMA") == 90
    assert resolve_resource_id_by_name("emma") == 90


def test_resolve_resource_id_by_name_unknown_returns_none():
    from nikke_optimizer.simulator.base_stats import resolve_resource_id_by_name

    assert resolve_resource_id_by_name("ThisCharacterDoesNotExist") is None


def test_from_name_loads_full_record():
    _require_cached(90)
    bs = BaseStats.from_name("Emma")
    assert bs.resource_id == 90
    assert bs.name == "Emma"


def test_compute_full_matches_in_game_display_rapi_red_hood():
    """End-to-end formula validation against displayed in-game stats.

    Inputs and the expected output are from real screenshots of the
    user's NIKKE account, May 2026:

      - LV654 / Grade 3 / Core 7
      - Equip totals (HP/ATK/DEF) summed from 4 gear slots
      - Bastion Cube (Battle), Shopping Commander Doll
      - Bond R40, Attacker R179 class research, Elysion R169 mfr research
      - Recycle Room → General Research LV300 (+135,000 HP)

    All three displayed stats match to the digit.
    """
    if not (
        cache_path_for_roledata("470", DEFAULT_LANG).is_file()
    ):
        pytest.skip("Rapi: Red Hood (470) not cached")
    bs = BaseStats.from_name("Rapi: Red Hood")
    out = bs.compute_full(
        level=654, grade=3, core=7,
        equip={"atk": 16402, "hp": 368863, "def": 2453},
        cube={"atk": 2780, "hp": 83400, "def": 552},
        treasure={"atk": 9688, "hp": 301800, "def": 2058},
        class_buff={"atk": 0, "hp": 134250, "def": 895},
        manufacturer_buff={"atk": 4225, "hp": 0, "def": 845},
        recycle_buff={"atk": 0, "hp": 135000, "def": 0},
        bond_buff={"atk": 2340, "hp": 52650, "def": 351},
    )
    assert out["atk"] == 402384
    assert out["hp"] == 9365477
    assert out["def"] == 53713


def test_compute_full_matches_in_game_display_moran():
    """Moran (Defender, Tetra, Bond R30) — ATK and DEF match exactly."""
    if not cache_path_for_roledata("862", DEFAULT_LANG).is_file():
        pytest.skip("Moran (862) not cached")
    bs = BaseStats.from_name("Moran")
    out = bs.compute_full(
        level=654, grade=3, core=7,
        equip={"atk": 10936, "hp": 450833, "def": 2999},
        cube={"atk": 2780, "hp": 83400, "def": 552},
        treasure={"atk": 9688, "hp": 301800, "def": 2058},
        class_buff={"atk": 0, "hp": 129000, "def": 860},
        manufacturer_buff={"atk": 4225, "hp": 0, "def": 845},
        recycle_buff={"atk": 0, "hp": 135000, "def": 0},
        bond_buff={"atk": 1094, "hp": 45097, "def": 300},
    )
    assert out["atk"] == 273510
    assert out["def"] == 75334
    # HP also predicted exact (11,262,671) but the screenshot HP digits
    # were partially obscured, so we just sanity-check the order of magnitude.
    assert 11_000_000 < out["hp"] < 11_500_000


def test_compute_full_with_no_buffs_equals_compute():
    """compute_full() with all-zero buffs == compute() (raw base)."""
    _require_cached(90)
    bs = BaseStats.from_name("Emma")
    raw = bs.compute(level=200, grade=3, core=7)
    full_no_buffs = bs.compute_full(level=200, grade=3, core=7)
    assert full_no_buffs == raw
