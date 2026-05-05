"""Tests for the cube same-level cross-validation helper."""

from __future__ import annotations

from nikke_optimizer.data.models import Cube
from nikke_optimizer.web.cube_warnings import compute_cube_warnings


def _cube(id: int, name: str, level: int, atk=None, hp=None, def_=None) -> Cube:
    return Cube(id=id, name=name, level=level, atk=atk, hp=hp, def_=def_)


def test_outlier_atk_flagged():
    """Assist Cube ATK 190 is way off the same-level median (~790)."""
    cubes = [
        _cube(1, "Assault Cube", 7, atk=910, hp=27_300, def_=180),
        _cube(2, "Bastion Cube", 7, atk=900, hp=27_500, def_=190),
        _cube(3, "Endurance Cube", 7, atk=890, hp=27_400, def_=185),
        _cube(4, "Assist Cube", 7, atk=190, hp=27_200, def_=185),  # OCR misread
    ]
    warnings = compute_cube_warnings(cubes)
    assert 4 in warnings
    msg = " ".join(warnings[4])
    assert "ATK" in msg
    assert "190" in msg
    # Other cubes have no warnings.
    for cid in (1, 2, 3):
        assert cid not in warnings


def test_no_warning_when_only_one_cube_at_level():
    """Single cube at a level → no median to compare against → no warning."""
    cubes = [_cube(1, "Solo Cube", 5, atk=500, hp=15_000, def_=100)]
    assert compute_cube_warnings(cubes) == {}


def test_no_warning_for_aligned_cubes():
    """Cubes within tolerance → no flags."""
    cubes = [
        _cube(1, "A", 7, atk=900, hp=27_300),
        _cube(2, "B", 7, atk=920, hp=27_400),
        _cube(3, "C", 7, atk=910, hp=27_350),
    ]
    assert compute_cube_warnings(cubes) == {}


def test_zero_or_none_stats_skipped():
    """Cube with stat=None or 0 doesn't contribute to the median or get flagged."""
    cubes = [
        _cube(1, "A", 7, atk=900, hp=27_300, def_=None),
        _cube(2, "B", 7, atk=920, hp=27_400, def_=None),
        _cube(3, "C", 7, atk=910, hp=27_350, def_=200),  # def_ has no median peer
    ]
    warnings = compute_cube_warnings(cubes)
    # No warning for def_=200 (it's the only DEF value at this level — nothing to
    # compare against).
    assert warnings == {}


def test_levelless_cube_skipped():
    """Cubes without a level (OCR couldn't read) are excluded from comparison."""
    cubes = [
        _cube(1, "A", 7, atk=900),
        _cube(2, "B", 7, atk=910),
        Cube(id=3, name="Mystery", level=None, atk=190),
    ]
    warnings = compute_cube_warnings(cubes)
    assert warnings == {}


def test_outliers_across_two_levels_dont_cross_compare():
    """Cubes at different levels have wildly different stats — they
    must not be cross-compared."""
    cubes = [
        _cube(1, "A", 7, atk=910),
        _cube(2, "B", 7, atk=920),
        _cube(3, "Lv1", 1, atk=100),  # legitimate small value at lv1
        _cube(4, "Lv1", 1, atk=110),
    ]
    assert compute_cube_warnings(cubes) == {}
