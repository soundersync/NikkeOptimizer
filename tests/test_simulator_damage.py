"""Tests for the damage-formula resolution module (Phase-3 simulator slice 3)."""

from __future__ import annotations

import pytest

from nikke_optimizer.simulator.damage import (
    DamageResolution,
    MATCH_LENGTH_SEC,
    resolve,
    resolve_by_names,
)
from nikke_optimizer.simulator.evaluator import evaluate_by_names


_ATTACK_COMP = ["Liter", "Crown", "Modernia", "Red Hood", "Snow White: Heavy Arms"]
_DEFENSE_TRIO = ["Helm", "Centi", "Blanc", "Bay", "Anchor"]
_TRUE_DAMAGE_COMP = [
    "Liter", "Crown", "Chisato Nishikigi", "Takina Inoue", "Jill Valentine",
]


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_resolve_returns_damageresolution_with_finite_metrics():
    """Sanity — resolve produces a finite DPS/burst/EHP and verdict."""
    result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert result is not None
    assert isinstance(result, DamageResolution)
    assert result.attacker_team_dps > 0, "attack comp should have positive DPS"
    assert result.attacker_burst_payload > 0, "burst payload should be positive"
    assert result.defender_effective_hp > 0, "defender HP pool should be positive"
    assert result.seconds_to_clear_defender > 0


def test_resolve_by_names_returns_none_for_unencoded_team():
    """Should bail cleanly if any character isn't in the registry."""
    assert resolve_by_names(["Liter", "DoesNotExist", "Crown", "Crown", "Crown"], _DEFENSE_TRIO) is None
    assert resolve_by_names(_ATTACK_COMP, ["DoesNotExist"] * 5) is None


def test_resolve_to_dict_serializes_metrics():
    result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert result is not None
    d = result.to_dict()
    for key in (
        "attacker_team_dps",
        "attacker_burst_payload",
        "defender_effective_hp",
        "attacker_atk_damage_per_sec",
        "attacker_true_damage_per_sec",
        "attacker_wins_within_5min",
        "win_margin",
        "notes",
    ):
        assert key in d


# ---------------------------------------------------------------------------
# Damage channel decomposition
# ---------------------------------------------------------------------------


def test_atk_dps_is_dominant_channel_for_traditional_carry():
    """A Crown comp with traditional ATK carries should have ATK channel
    dominate; true-damage and other channels should be small fractions."""
    result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert result is not None
    assert result.attacker_atk_damage_per_sec > 0
    # Crown comp has no true-damage carry — true_dps should be small.
    assert result.attacker_true_damage_per_sec < result.attacker_atk_damage_per_sec


def test_true_damage_carry_team_has_significant_true_damage_channel():
    """Chisato + Takina + Jill stack BUFF_TRUE_DAMAGE — the true-damage
    channel should be a meaningful share of total DPS, well above what
    a no-true-damage team produces."""
    true_result = resolve_by_names(_TRUE_DAMAGE_COMP, _DEFENSE_TRIO)
    base_result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert true_result is not None
    assert base_result is not None
    # True-damage comp should have notably higher true-damage channel.
    assert true_result.attacker_true_damage_per_sec > 0
    assert (
        true_result.attacker_true_damage_per_sec
        > base_result.attacker_true_damage_per_sec
    )


def test_def_reduction_floors_at_5_percent():
    """Even an absurdly high-DEF defender shouldn't reduce damage below
    the 5% floor — the formula caps mitigation."""
    from nikke_optimizer.simulator.damage import _def_reduction_factor
    # 1k ATK vs 1B DEF — would produce ~0% without the floor.
    factor = _def_reduction_factor(1_000.0, 1_000_000_000.0)
    assert factor >= 0.05


# ---------------------------------------------------------------------------
# Outcome verdict
# ---------------------------------------------------------------------------


def test_strong_attack_team_clears_default_defender_within_5min():
    """A canonical Crown attack comp vs a default-stat defender should
    clear within the 5-minute PvP timeout."""
    result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert result is not None
    # The 5-min cap is the timeout — strong attack comps should beat it.
    assert result.attacker_wins_within_5min, (
        f"Attack comp should clear defender in <5min; "
        f"got {result.seconds_to_clear_defender:.1f}s "
        f"(defender HP={result.defender_effective_hp:.0f}, "
        f"DPS={result.attacker_team_dps:.0f})"
    )


def test_win_margin_is_positive_when_attacker_wins():
    result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert result is not None
    if result.attacker_wins_within_5min:
        assert result.win_margin > 0
    else:
        assert result.win_margin <= 0


def test_resolve_is_deterministic():
    """Same inputs → same outputs. The damage formula is steady-state,
    no RNG at this layer."""
    a = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    b = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert a is not None and b is not None
    assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# Burst-as-DPS model (slice #96)
# ---------------------------------------------------------------------------


def test_burst_dps_equivalent_folds_into_team_dps():
    """``attacker_team_dps`` includes the time-averaged burst contribution,
    not just the per-second normal-attack channels. Verifies the slice-#96
    refactor that replaced "burst as t=0 head start" with "burst as
    cycle-averaged DPS"."""
    result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert result is not None
    channel_sum = (
        result.attacker_atk_damage_per_sec
        + result.attacker_true_damage_per_sec
        + result.attacker_other_damage_per_sec
    )
    # team_dps must be at least channel_sum (burst contribution adds to it).
    assert result.attacker_team_dps >= channel_sum
    # And for a Crown comp with non-zero burst payload, the burst
    # equivalent should add a measurable amount to the team DPS.
    if result.attacker_burst_payload > 0:
        assert result.attacker_team_dps > channel_sum


def test_clear_time_no_longer_collapses_to_first_burst_when_burst_huge():
    """Pre-slice-#96 a team whose burst payload exceeded defender HP
    cleared at exactly first_burst_sec (degenerate "1s clear" output).
    Now the clear time scales with HP/DPS instead of being capped."""
    result = resolve_by_names(_ATTACK_COMP, _DEFENSE_TRIO)
    assert result is not None
    # Even when burst payload is large vs defender HP, clear time
    # should be > first_burst_sec by a reasonable margin (DPS clears
    # the rest, not "all burst lands at t=0").
    assert result.seconds_to_clear_defender > 5.0


def test_weapon_class_table_differentiates_classes():
    """Slice #97 — per-WeaponClass damage factor. The table must give
    SR/RL distinctly lower fractions than MG/SMG so the optimizer's
    win-margin output reflects fire-rate differences."""
    from nikke_optimizer.simulator.damage import (
        WEAPON_DAMAGE_PER_SECOND_FRACTION,
    )
    assert WEAPON_DAMAGE_PER_SECOND_FRACTION["MG"] > WEAPON_DAMAGE_PER_SECOND_FRACTION["SR"]
    assert WEAPON_DAMAGE_PER_SECOND_FRACTION["SMG"] > WEAPON_DAMAGE_PER_SECOND_FRACTION["RL"]
    # AR sits between fast and slow extremes.
    assert (
        WEAPON_DAMAGE_PER_SECOND_FRACTION["RL"]
        <= WEAPON_DAMAGE_PER_SECOND_FRACTION["AR"]
        <= WEAPON_DAMAGE_PER_SECOND_FRACTION["MG"]
    )
