"""Tests for the static team evaluator (Phase-3 simulator slice 1)."""

from __future__ import annotations

import pytest

from nikke_optimizer.simulator.evaluator import (
    NikkeSnapshot,
    TeamEvaluation,
    evaluate_by_names,
    evaluate_team,
)


# All eight encoded characters — used to construct realistic teams.
_CROWN_COMP = ["Liter", "Crown", "Modernia", "Red Hood", "Snow White: Heavy Arms"]
_DEFENSE_TRIO = ["Helm", "Centi", "Blanc"]


def test_evaluate_crown_comp_returns_5_member_snapshot():
    team = evaluate_by_names(_CROWN_COMP)
    assert team is not None
    assert len(team.members) == 5
    assert {m.name for m in team.members} == set(_CROWN_COMP)


def test_evaluate_returns_none_for_unencoded_team():
    team = evaluate_by_names(["Liter", "DoesNotExist", "Crown", "Crown", "Crown"])
    assert team is None


# ---------------------------------------------------------------------------
# Per-Nikke buff propagation
# ---------------------------------------------------------------------------


def test_crown_burst_grants_team_attack_damage_buff():
    """Crown's burst applies team Attack Damage +36.24% (per source) —
    after the DSL slice this is BUFF_ATTACK_DAMAGE, not BUFF_ATK. The
    evaluator must surface it on attack_damage_buff_pct, propagating
    the buff to every ally after the burst chain fires."""
    team = evaluate_by_names(_CROWN_COMP)
    assert team is not None
    # D1 duty-cycle: Crown's 36.24% buff has duration 15s, so in the
    # 30s PVP_AVG_MATCH model it scales to 18.12. Test now asserts the
    # buff PROPAGATED (>0) and is in the right ballpark for the
    # duty-cycle adjustment.
    for m in team.members:
        assert m.attack_damage_buff_pct >= 15.0, (
            f"{m.name} only has attack_damage_buff_pct="
            f"{m.attack_damage_buff_pct}; Crown's burst (36.24%, 15s "
            "duty-cycled to ~18.12) should propagate to every ally"
        )


def test_crown_burst_grants_team_shield():
    """Crown's burst grants a 10.45%-of-max-HP shield to every ally."""
    team = evaluate_by_names(_CROWN_COMP)
    assert team is not None
    for m in team.members:
        # Crown's max HP at the default base = 1,000,000; 10.45% = 104,500
        assert m.shield_value >= 100_000, (
            f"{m.name} shield is {m.shield_value}; expected ≥100k from Crown"
        )


def test_liter_burst_offensive_buffs_propagate_to_all_allies():
    """Liter's burst grants ATK +66% (BUFF_ATK), Crown grants Attack
    Damage +36.24% (BUFF_ATTACK_DAMAGE post-DSL-slice). Every ally
    should see ≥100% combined offensive buff."""
    team = evaluate_by_names(_CROWN_COMP)
    assert team is not None
    # D1 duty-cycle: Crown 36.24%×0.5 + Liter 66%×~0.5 + S2 14.42%×?
    # = ~30 minimum at the duty-cycled rate. Test now asserts the
    # buffs propagated (>0 per ally) and combined is in the right range.
    for m in team.members:
        combined = m.atk_buff_pct + m.attack_damage_buff_pct
        assert combined >= 30.0, (
            f"{m.name} combined offensive buff={combined}% "
            f"(atk={m.atk_buff_pct}, attack_dmg={m.attack_damage_buff_pct}); "
            "expected ≥30 after duty-cycle scaling of burst-window buffs"
        )


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def test_crown_comp_dps_is_higher_than_baseline():
    """Crown comp's effective ATK should exceed an unbuffed team's ATK
    by a meaningful margin — the burst chain stacks ATK aggressively."""
    team = evaluate_by_names(_CROWN_COMP)
    assert team is not None
    base_atk = 100_000
    baseline_dps = 5 * base_atk
    # The Crown comp should be at least 2× a baseline team's DPS thanks
    # to stacked ATK buffs from Crown burst + Liter burst + Crown S2.
    assert team.dps_estimate >= 2.0 * baseline_dps, (
        f"Crown comp dps_estimate {team.dps_estimate:,.0f} should be ≥ "
        f"2× baseline {baseline_dps:,.0f}"
    )


def test_defense_trio_has_more_ehp_than_attack_only_team():
    """A team of defenders + 2 fillers should out-tank a pure attack
    comp in EHP. Tests that GRANT_SHIELD effects propagate."""
    defense_team = _DEFENSE_TRIO + ["Liter", "Crown"]
    attack_team = _CROWN_COMP

    d = evaluate_by_names(defense_team)
    a = evaluate_by_names(attack_team)
    assert d is not None
    assert a is not None
    # Defense team has Centi (S2 6.38% shield), Blanc (S1 11.8% shield),
    # Crown (burst 10.45% shield). Attack team only has Crown's shield.
    # Defense should have notably more total shield.
    assert d.total_shield > a.total_shield, (
        f"defense total_shield {d.total_shield:,.0f} should exceed attack "
        f"{a.total_shield:,.0f}"
    )


def test_defense_trio_has_higher_sustain_index():
    """Defense team has Blanc's regen + Helm's lifesteal — should have
    a measurable sustain_index (HEAL_PER_SECOND × duration)."""
    defense_team = _DEFENSE_TRIO + ["Liter", "Crown"]
    attack_team = _CROWN_COMP

    d = evaluate_by_names(defense_team)
    a = evaluate_by_names(attack_team)
    assert d is not None
    assert a is not None
    # The attack team has Liter's S2 (cover heal) so non-zero, but the
    # defense trio has multiple regen sources — should be larger.
    assert d.sustain_index > a.sustain_index, (
        f"defense sustain_index {d.sustain_index:.2f} should exceed attack "
        f"{a.sustain_index:.2f}"
    )


def test_burst_payload_aggregates_burst_damage():
    """Burst payload should sum the magnitude × ATK of every member's
    burst-skill DEAL_DAMAGE effects targeting enemies."""
    team = evaluate_by_names(_CROWN_COMP)
    assert team is not None
    # Crown comp has SW:HA + Modernia + Red Hood all dealing burst damage.
    # Even our coarse static evaluator should produce a positive number.
    assert team.burst_payload > 0, (
        "Crown comp burst_payload should be positive — multiple members "
        "have burst-skill DEAL_DAMAGE effects"
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_evaluate_is_deterministic():
    """Same inputs → same outputs. The evaluator has no RNG; this test
    guards against a future regression where, e.g., dict iteration order
    leaks into magnitudes."""
    a = evaluate_by_names(_CROWN_COMP)
    b = evaluate_by_names(_CROWN_COMP)
    assert a is not None and b is not None
    assert a.dps_estimate == b.dps_estimate
    assert a.ehp_estimate == b.ehp_estimate
    assert a.burst_payload == b.burst_payload


# ---------------------------------------------------------------------------
# Snapshot mechanics
# ---------------------------------------------------------------------------


def test_effective_atk_compounds_buffs():
    """A NikkeSnapshot with stacked atk_buff_pct should compute
    effective_atk as base × (1 + total/100). Sanity-check the math."""
    snap = NikkeSnapshot(name="X", base_atk=100_000, atk_buff_pct=50.0)
    assert snap.effective_atk == pytest.approx(150_000.0)
    snap.atk_buff_pct += 50.0
    assert snap.effective_atk == pytest.approx(200_000.0)


def test_team_evaluation_to_dict_serializes_metrics():
    team = evaluate_by_names(_CROWN_COMP)
    assert team is not None
    d = team.to_dict()
    assert "dps_estimate" in d
    assert "members" in d
    assert len(d["members"]) == 5
    assert d["dps_estimate"] > 0


# ---------------------------------------------------------------------------
# DSL slice — damage-type buffs + cross-stat scaling
# ---------------------------------------------------------------------------


def test_chisato_true_damage_buff_does_not_pollute_atk_buff():
    """Chisato's Extrasensory >55% gives self True Damage +48.62%. After the
    DSL slice, this is BUFF_TRUE_DAMAGE (not BUFF_ATK), so it must show up
    in true_damage_buff_pct, not atk_buff_pct."""
    team = evaluate_by_names(["Chisato Nishikigi", "Liter", "Crown", "Modernia", "Red Hood"])
    assert team is not None
    chisato = next(m for m in team.members if m.name == "Chisato Nishikigi")
    # D1 duty-cycle: 48.62% over 10s = ~16.2% sustained. Threshold
    # lowered accordingly; the test still validates the buff lands.
    assert chisato.true_damage_buff_pct >= 15.0, (
        f"Chisato true_damage_buff_pct should be ≥15 after duty-cycle "
        f"scaling of 48.62%/10s, got {chisato.true_damage_buff_pct}"
    )


def test_naga_burst_atk_buff_uses_caster_atk_scaling():
    """Naga's burst is 'ATK +16.18% of caster's ATK' (cross-stat). After the
    DSL slice, allies should get a flat ATK bonus (not a multiplicative
    buff). Default caster.base_atk=100k, so the bonus should be ~16,180."""
    team = evaluate_by_names(["Naga", "Liter", "Crown", "Modernia", "Red Hood"])
    assert team is not None
    # Each ally including Naga gets 16.18% of her ATK as a flat bonus.
    # Naga's base_atk defaults to 100k → 16,180 flat ATK.
    for m in team.members:
        assert m.flat_atk_bonus >= 16_000, (
            f"{m.name} flat_atk_bonus={m.flat_atk_bonus}; expected ≥16k from Naga's "
            f"cross-stat ATK buff (16.18% of caster's 100k ATK)"
        )


def test_jackal_burst_skill_damage_buff_is_distinct_from_atk_buff():
    """Jackal's burst is 'Burst Skill damage +38.91%' (single-target burst
    skills only). After the DSL slice, this is BUFF_BURST_SKILL_DAMAGE,
    so it should not pollute atk_buff_pct."""
    team = evaluate_by_names(["Jackal", "Liter", "Crown", "Modernia", "Red Hood"])
    assert team is not None
    # D1 duty-cycle: Jackal's 38.91% has duration 15s → ~19.5 scaled.
    for m in team.members:
        assert m.burst_skill_damage_buff_pct >= 15.0, (
            f"{m.name} burst_skill_damage_buff_pct={m.burst_skill_damage_buff_pct} "
            "(expected ≥15 after duty-cycle scaling)"
        )


# ---------------------------------------------------------------------------
# Optimizer rescore_with_evaluator (slice #56)
# ---------------------------------------------------------------------------


def test_rescore_with_evaluator_adds_buff_amp_and_vs_high_def_components():
    """A team with stacked true-damage buffs (Chisato + Takina + Jill) should
    pick up positive ``team_buff_amp`` and ``vs_high_def`` contributions
    after rescoring under ATTACK_WEIGHTS — those weights credit damage-type
    buffs and DEF-bypassing carries."""
    from dataclasses import dataclass
    from nikke_optimizer.data.enums import (
        BurstType, Element, Rarity, WeaponClass,
    )
    from nikke_optimizer.optimizer.models import (
        CharacterView, ScoreBreakdown, TeamCandidate,
    )
    from nikke_optimizer.optimizer.scoring import (
        ATTACK_WEIGHTS, DEFENSE_WEIGHTS, rescore_with_evaluator,
    )

    # Build a stub TeamCandidate with the specific carries — the rescorer
    # only reads breakdown.total + member names, not the rest of the view.
    def stub_view(name):
        return CharacterView(
            name=name,
            rarity=Rarity.SSR,
            element=Element.ELECTRIC,
            weapon_class=WeaponClass.AR,
            burst_type=BurstType.III,
            owned=True,
            power=200_000,
        )

    candidate = TeamCandidate(
        members=tuple(stub_view(n) for n in [
            "Chisato Nishikigi", "Takina Inoue", "Jill Valentine", "Liter", "Crown",
        ]),
        breakdown=ScoreBreakdown(total=10.0, power_sum=5.0),
        notes=[],
    )
    evaluation = evaluate_by_names([m.name for m in candidate.members])
    assert evaluation is not None

    rescored_attack = rescore_with_evaluator(
        candidate, evaluation, weights=ATTACK_WEIGHTS
    )
    rescored_defense = rescore_with_evaluator(
        candidate, evaluation, weights=DEFENSE_WEIGHTS
    )

    # ATTACK_WEIGHTS credit damage-type buffs strongly; the rescored total
    # should be strictly higher than the base 10.0.
    assert rescored_attack.breakdown.total > 10.0
    assert rescored_attack.breakdown.team_buff_amp > 0.0
    assert rescored_attack.breakdown.vs_high_def > 0.0

    # DEFENSE_WEIGHTS keep vs_high_def at zero (defenders don't push damage)
    # and only weakly credit team_buff_amp — the attack-side rescore must
    # exceed the defense-side rescore for this carry-stacked team.
    assert rescored_attack.breakdown.total > rescored_defense.breakdown.total

    # Heuristic components are preserved unchanged across rescoring.
    assert rescored_attack.breakdown.power_sum == pytest.approx(5.0)


def test_rescore_with_evaluator_is_no_op_for_balanced_when_no_damage_buffs():
    """A pure-defense team (Helm/Centi/Blanc/Bay/Anchor) has no damage-type
    buffs and zero vs_high_def index, so rescoring shouldn't move the total."""
    from nikke_optimizer.data.enums import (
        BurstType, Element, Rarity, WeaponClass,
    )
    from nikke_optimizer.optimizer.models import (
        CharacterView, ScoreBreakdown, TeamCandidate,
    )
    from nikke_optimizer.optimizer.scoring import (
        BALANCED_WEIGHTS, rescore_with_evaluator,
    )

    def stub_view(name):
        return CharacterView(
            name=name, rarity=Rarity.SSR, element=Element.WATER,
            weapon_class=WeaponClass.RL, burst_type=BurstType.II,
            owned=True, power=200_000,
        )

    candidate = TeamCandidate(
        members=tuple(stub_view(n) for n in [
            "Helm", "Centi", "Blanc", "Bay", "Anchor",
        ]),
        breakdown=ScoreBreakdown(total=8.0),
        notes=[],
    )
    evaluation = evaluate_by_names([m.name for m in candidate.members])
    assert evaluation is not None

    rescored = rescore_with_evaluator(
        candidate, evaluation, weights=BALANCED_WEIGHTS
    )
    # Defense trio has near-zero damage-type buffs and vs_high_def, so the
    # rescored total should be close to (not necessarily equal to — Helm has
    # some damage-buff contribution) the original.
    assert rescored.breakdown.total == pytest.approx(8.0, abs=2.0)


# ---------------------------------------------------------------------------
# Per-Nikke stat calibration (slice #88)
# ---------------------------------------------------------------------------


def test_per_name_stats_overrides_global_defaults():
    """Per-Nikke stats from ``OwnedCharacter`` override the global defaults
    used by ``evaluate_team``. Drives the damage formula off the user's
    actual investment instead of the coarse 100k/1M/30k baseline."""
    from nikke_optimizer.simulator.registry import get as _get
    sets = [_get(name) for name in _CROWN_COMP]
    assert all(s is not None for s in sets)

    # Crown gets a beefy 200k ATK / 2M HP, the rest stay at defaults.
    per_name_stats = {
        "Crown": {"base_atk": 200_000, "base_hp": 2_000_000, "base_def": 60_000},
    }
    eval_with = evaluate_team(sets, per_name_stats=per_name_stats)
    eval_without = evaluate_team(sets)

    crown_with = next(m for m in eval_with.members if m.name == "Crown")
    crown_without = next(m for m in eval_without.members if m.name == "Crown")
    assert crown_with.base_atk == 200_000
    assert crown_with.base_hp == 2_000_000
    assert crown_without.base_atk == 100_000  # still default
    # The other 4 members keep the defaults (per_name_stats is partial).
    others_with = [m for m in eval_with.members if m.name != "Crown"]
    assert all(m.base_atk == 100_000 for m in others_with)


def test_per_name_stats_skips_zero_or_none_values():
    """Missing / 0 stats fall through to the global defaults so partial
    CSV rows don't produce degenerate snapshots."""
    from nikke_optimizer.simulator.registry import get as _get
    sets = [_get(name) for name in _CROWN_COMP]

    per_name_stats = {
        # base_atk=0 should be ignored, base_hp=None should be ignored.
        "Crown": {"base_atk": 0, "base_hp": None, "base_def": 50_000},
    }
    team = evaluate_team(sets, per_name_stats=per_name_stats)
    crown = next(m for m in team.members if m.name == "Crown")
    assert crown.base_atk == 100_000  # fell through to default
    assert crown.base_hp == 1_000_000  # fell through
    assert crown.base_def == 50_000  # used the override
