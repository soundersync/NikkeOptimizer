"""Cube skill-effect modeling.

Every NIKKE cube has a level-scaled skill that's distinct from its raw
ATK/HP/DEF stats. We capture the raw stats from BlablaLink/CSV (already
in ``Cube.atk/hp/def``), but the *skill* effects need to be applied
separately — they're not in the displayed character totals.

For PvP simulation the dominant cube effect is **Quantum Cube's
burst-energy bonus**, which lets the equipped Nikke fill the team
burst gauge significantly faster. A team with 5× Quantum cubes
typically bursts ~3-5 seconds before a team with 5× Bastion cubes,
which often decides Champions Arena matches.

Effect magnitudes are approximate community-published values. Actual
in-game numbers vary by cube level (LV1-15); we interpolate linearly.

Sources cross-referenced May 2026:
- nikke.gg cube tier list + per-level effect tables
- Prydwen cube guide
"""

from __future__ import annotations

from typing import Optional


# Per-cube **per-Nikke** burst-gauge bonus (% gauge per second contributed
# to the team total when this cube is equipped on a member). Values are
# at LV15 (max). Lower levels scale linearly down to LV1.
#
# Calibration approach: a LV15 Quantum on every team member roughly
# halves first-burst time vs no-Quantum. With 5 LV15 Quantums, +1.5%
# per Nikke per sec → +7.5% team rate added to the ~10% baseline →
# ~38% faster first burst.
CUBE_BURST_GEN_BONUS_LV15_PCT_PER_SEC: dict[str, float] = {
    "Quantum Cube":   1.5,   # signature PvP cube — burst energy boost
    "Tempering Cube": 0.4,   # CDR helps secondary bursts more than first
    "Adjutant Cube":  0.3,   # minor burst-related effect
    # Other cubes have no burst-gen contribution
    "Bastion Cube":     0.0,
    "Resilience Cube":  0.0,
    "Endurance Cube":   0.0,
    "Healing Cube":     0.0,
    "Onslaught Cube":   0.0,
    "Wingman Cube":     0.0,
    "Assist Cube":      0.0,
    "Vigor Cube":       0.0,
    "Assault Cube":     0.0,
    "Destruction Cube": 0.0,
    "Piercing Cube":    0.0,
}

# Cube effects that contribute to defender survival via per-second
# heal or damage-reduction proxies. Applied as a flat heal_per_second
# bonus to the equipped Nikke during their proc condition (which we
# treat as always-on for sim purposes).
CUBE_HEAL_PER_SEC_LV15_FRAC_OF_HP: dict[str, float] = {
    "Bastion Cube":    0.005,   # ~0.5% caster HP/sec sustain
    "Resilience Cube": 0.008,   # stronger defensive sustain
    "Healing Cube":    0.012,   # dedicated heal cube
    "Endurance Cube":  0.003,   # mild regen
}


def cube_burst_gen_bonus_pct_per_sec(cube_name: Optional[str], cube_level: Optional[int]) -> float:
    """Return the per-Nikke burst-gauge contribution from this cube.

    Linear interpolation from LV1 (10% of max) to LV15 (100%).
    Returns 0.0 for unknown cubes or empty inputs.
    """
    if not cube_name:
        return 0.0
    base = CUBE_BURST_GEN_BONUS_LV15_PCT_PER_SEC.get(cube_name, 0.0)
    if base == 0.0:
        return 0.0
    lvl = max(1, min(15, cube_level or 1))
    # Linear LV1 → 10% of max, LV15 → 100% of max.
    scale = 0.10 + 0.90 * (lvl - 1) / 14
    return base * scale


def cube_heal_per_sec_frac_of_hp(cube_name: Optional[str], cube_level: Optional[int]) -> float:
    """Return the per-second heal as a fraction of caster HP from cube.

    Linear interpolation LV1→LV15 same as burst gen.
    """
    if not cube_name:
        return 0.0
    base = CUBE_HEAL_PER_SEC_LV15_FRAC_OF_HP.get(cube_name, 0.0)
    if base == 0.0:
        return 0.0
    lvl = max(1, min(15, cube_level or 1))
    scale = 0.10 + 0.90 * (lvl - 1) / 14
    return base * scale
