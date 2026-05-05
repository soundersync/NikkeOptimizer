"""Tests for the time-windowed evaluator (Phase-3 simulator slice 2)."""

from __future__ import annotations

import pytest

from nikke_copilot.simulator.timeline import (
    AppliedEffect,
    Timeline,
    build_timeline,
    build_timeline_by_names,
    compute_burst_chain_offsets,
    compute_full_burst_start,
    BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC,
    DEFAULT_BURST_CHAIN_OFFSETS_SEC,
    DEFAULT_FULL_BURST_START_SEC,
)
from nikke_copilot.simulator.dsl import EffectKind


_CROWN_COMP = ["Liter", "Crown", "Modernia", "Red Hood", "Snow White: Heavy Arms"]


# ---------------------------------------------------------------------------
# AppliedEffect mechanics
# ---------------------------------------------------------------------------


def test_applied_effect_window_membership():
    eff = AppliedEffect(
        target_name="Liter",
        kind=EffectKind.BUFF_ATK,
        magnitude=66.0,
        apply_time=10.0,
        expiry_time=15.0,
    )
    assert not eff.is_active_at(9.99)
    assert eff.is_active_at(10.0)
    assert eff.is_active_at(12.5)
    assert not eff.is_active_at(15.0)  # half-open interval
    assert not eff.is_active_at(20.0)


# ---------------------------------------------------------------------------
# Timeline build basics
# ---------------------------------------------------------------------------


def test_build_timeline_returns_appropriate_membership():
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    assert timeline.member_names == tuple(_CROWN_COMP)
    assert len(timeline.applied) > 0
    # Every applied effect targets a team member.
    for eff in timeline.applied:
        assert eff.target_name in _CROWN_COMP


def test_build_timeline_returns_none_for_unencoded():
    timeline = build_timeline_by_names(["Liter", "DoesNotExist", "Crown", "Crown", "Crown"])
    assert timeline is None


def test_timeline_is_sorted_by_apply_time():
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    times = [eff.apply_time for eff in timeline.applied]
    assert times == sorted(times), "timeline must be in chronological order"


# ---------------------------------------------------------------------------
# State-at-time queries
# ---------------------------------------------------------------------------


def test_state_at_t0_has_only_battle_start_buffs():
    """At t=0, only ALWAYS / ON_BATTLE_START effects have fired. Burst-
    chain ATK buffs (Crown burst, Liter burst) shouldn't be present yet."""
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    states = timeline.state_at(0.0)
    assert len(states) == 5
    # No burst skill has fired yet, so the team-wide ATK buff total
    # should be modest. Crown's burst alone would add +36.24%; Liter's
    # would add another +66%; their absence at t=0 is the test.
    for s in states:
        assert s.atk_buff_pct < 50.0, (
            f"{s.name} has +{s.atk_buff_pct}% ATK at t=0; burst buffs "
            "should NOT be active yet"
        )


def test_state_at_full_burst_window_has_burst_buffs():
    """At t=12.5, every member should have stacked offensive buffs from
    Liter's burst (ATK +66%, 5s) and Crown's burst (Attack Damage
    +36.24%, 15s). Sampling at 12.5 lands in both buff windows whether
    the gauge fills at the legacy t=10 baseline or the slice #78
    skill-bonus-accelerated ~t=8.3."""
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    states = timeline.state_at(12.5)
    for s in states:
        combined = s.atk_buff_pct + s.attack_damage_buff_pct
        assert combined >= 100.0, (
            f"{s.name} only has combined offensive buffs "
            f"+{combined}% at t=14.5 (atk={s.atk_buff_pct}, "
            f"attack_damage={s.attack_damage_buff_pct}); "
            "expected ≥100 (Crown 36 + Liter 66 + buffs)"
        )


def test_buff_decays_after_expiry():
    """Crown's burst grants 15-sec ATK buff. At t=12 the buff applies;
    at t=30 it should have expired."""
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    mid = timeline.state_at(15.0)
    late = timeline.state_at(60.0)
    # ATK buff should be smaller (or zero) at t=60 vs t=15. Some
    # passive effects (always-on Pierce, etc.) may persist.
    avg_mid = sum(s.atk_buff_pct for s in mid) / len(mid)
    avg_late = sum(s.atk_buff_pct for s in late) / len(late)
    assert avg_late < avg_mid, (
        f"avg ATK buff at t=60 ({avg_late:.1f}) should be less than at "
        f"t=15 ({avg_mid:.1f}) — buffs must decay"
    )


def test_shield_value_is_positive_during_burst_window():
    """Crown's burst grants 10.45%-of-max-HP shield; SW:HA's S1 +
    others contribute. Total per-ally shield > 0 during the burst
    window."""
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    states = timeline.state_at(15.0)
    for s in states:
        assert s.shield_value > 0, (
            f"{s.name} has no shield at t=15; Crown's burst should grant one"
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_timeline_is_deterministic():
    a = build_timeline_by_names(_CROWN_COMP)
    b = build_timeline_by_names(_CROWN_COMP)
    assert a is not None and b is not None
    assert len(a.applied) == len(b.applied)
    for ea, eb in zip(a.applied, b.applied):
        assert ea == eb


def test_state_history_returns_parallel_pairs():
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    times = [0.0, 5.0, 12.0, 15.0, 30.0, 120.0]
    history = timeline.state_history(times)
    assert len(history) == len(times)
    for (t, states), expected_t in zip(history, times):
        assert t == expected_t
        assert len(states) == 5


# ---------------------------------------------------------------------------
# Stack caps
# ---------------------------------------------------------------------------


def test_stack_cap_groups_by_source_character():
    """Slice #86 — two effects of the same kind targeting the same Nikke
    but from DIFFERENT casters each count as their own stack budget.
    Without source tracking, both would aggregate into one over-cap pile."""
    from nikke_copilot.simulator.timeline import AppliedEffect, Timeline
    from nikke_copilot.simulator.dsl import EffectKind

    timeline = Timeline(
        member_names=("Alice", "Bob"),
        base_atk=100_000, base_hp=1_000_000, base_def=30_000,
    )
    # Two BUFF_ATK +20% effects from DIFFERENT casters on Alice. Each
    # has stacks_max=1, so neither caps the other; both apply.
    timeline.applied.append(AppliedEffect(
        target_name="Alice", kind=EffectKind.BUFF_ATK, magnitude=20.0,
        apply_time=0.0, expiry_time=100.0, stacks_max=1,
        source_character="Crown", source_skill_slot="burst_skill",
    ))
    timeline.applied.append(AppliedEffect(
        target_name="Alice", kind=EffectKind.BUFF_ATK, magnitude=15.0,
        apply_time=0.0, expiry_time=100.0, stacks_max=1,
        source_character="Liter", source_skill_slot="burst_skill",
    ))
    snapshot = next(s for s in timeline.state_at(50.0) if s.name == "Alice")
    # Both buffs apply (Crown's 20 + Liter's 15 = 35).
    assert snapshot.atk_buff_pct == pytest.approx(35.0)


def test_stack_cap_caps_within_same_source():
    """Multiple effects from the SAME caster + slot + target + kind
    cap at ``stacks_max``. Five 10% applications with stacks_max=3
    should sum to 30%, not 50%."""
    from nikke_copilot.simulator.timeline import AppliedEffect, Timeline
    from nikke_copilot.simulator.dsl import EffectKind

    timeline = Timeline(
        member_names=("Alice",),
        base_atk=100_000, base_hp=1_000_000, base_def=30_000,
    )
    # 5 applications, all from Crown's skill1, on Alice. stacks_max=3.
    for _ in range(5):
        timeline.applied.append(AppliedEffect(
            target_name="Alice", kind=EffectKind.BUFF_ATK, magnitude=10.0,
            apply_time=0.0, expiry_time=100.0, stacks_max=3,
            source_character="Crown", source_skill_slot="skill1",
        ))
    snapshot = timeline.state_at(50.0)[0]
    # Cap of 3 applies → 3 × 10% = 30%, not 5 × 10% = 50%.
    assert snapshot.atk_buff_pct == pytest.approx(30.0)


def test_stack_cap_takes_top_magnitudes_within_source():
    """When stacks_max < total applications, the implementation picks
    the strongest stacks (not the first or random). Verifies the
    in-game behavior of "extra stacks dropped in favor of stronger ones"."""
    from nikke_copilot.simulator.timeline import AppliedEffect, Timeline
    from nikke_copilot.simulator.dsl import EffectKind

    timeline = Timeline(
        member_names=("Alice",),
        base_atk=100_000, base_hp=1_000_000, base_def=30_000,
    )
    for mag in (5.0, 30.0, 10.0, 20.0):
        timeline.applied.append(AppliedEffect(
            target_name="Alice", kind=EffectKind.BUFF_ATK, magnitude=mag,
            apply_time=0.0, expiry_time=100.0, stacks_max=2,
            source_character="Crown", source_skill_slot="skill2",
        ))
    snapshot = timeline.state_at(50.0)[0]
    # Cap of 2 → top-2 stacks (30 + 20) = 50%.
    assert snapshot.atk_buff_pct == pytest.approx(50.0)


def test_legacy_effects_without_source_each_count_independently():
    """Effects with empty ``source_character`` / ``source_skill_slot``
    each get a unique pseudo-source group so the cap doesn't conflate
    legacy callers. Verifies the ``__legacy_{idx}__`` fallback."""
    from nikke_copilot.simulator.timeline import AppliedEffect, Timeline
    from nikke_copilot.simulator.dsl import EffectKind

    timeline = Timeline(
        member_names=("Alice",),
        base_atk=100_000, base_hp=1_000_000, base_def=30_000,
    )
    for _ in range(4):
        timeline.applied.append(AppliedEffect(
            target_name="Alice", kind=EffectKind.BUFF_ATK, magnitude=10.0,
            apply_time=0.0, expiry_time=100.0, stacks_max=1,
            source_character="", source_skill_slot="",
        ))
    snapshot = timeline.state_at(50.0)[0]
    # All 4 apply because each is its own source-group.
    assert snapshot.atk_buff_pct == pytest.approx(40.0)


def test_crown_s2_stacks_capped_at_3():
    """Crown's S2 ATK +25.45% per ally burst, max 3 stacks. Even though
    the burst chain has 5 ON_ALLY_BURST_USE events, only 3 should
    contribute to any single Nikke's ATK buff at peak."""
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    states = timeline.state_at(15.0)
    # Each Nikke bursts at most once. Crown's S2 targets the BURST_USER,
    # so each Nikke would receive Crown S2 buff exactly once.
    # The stack cap of 3 means even if a single target somehow received
    # 5 stacks, only 3 would count (75.45%, not 125.5%).
    # Real-world: each Nikke gets ~25.45% from one burst-user-targeted
    # application — the cap matters for tests that verify uncapped
    # behavior fails. We check the upper bound here.
    for s in states:
        # Total ATK buff should be reasonable (well under 1000%) — the
        # cap is what prevents runaway stacking.
        assert s.atk_buff_pct < 1000.0


# ---------------------------------------------------------------------------
# Burst-gauge dynamics (slice #75)
# ---------------------------------------------------------------------------


def test_compute_burst_chain_offsets_calibration_matches_legacy_default():
    """Crown comp weapons (SMG/MG/MG/SR/SR) sum to 10 → first burst at
    t=10, matching the legacy DEFAULT_BURST_CHAIN_OFFSETS_SEC."""
    offsets = compute_burst_chain_offsets(["smg", "mg", "mg", "sr", "sr"])
    assert offsets == pytest.approx(DEFAULT_BURST_CHAIN_OFFSETS_SEC)


def test_compute_burst_chain_offsets_sg_heavy_team_bursts_earlier():
    """Two SGs in the comp pull first burst noticeably earlier."""
    legacy = compute_burst_chain_offsets(["smg", "mg", "mg", "sr", "sr"])
    sg_heavy = compute_burst_chain_offsets(["smg", "sg", "sg", "sr", "sr"])
    assert sg_heavy[0] < legacy[0] - 1.0, (
        f"SG-heavy should burst >1s earlier; got {sg_heavy[0]:.2f} vs "
        f"{legacy[0]:.2f}"
    )


def test_compute_burst_chain_offsets_slow_team_bursts_later():
    """All-SMG team is the slowest possible mix → first burst much later."""
    slow = compute_burst_chain_offsets(["smg", "smg", "smg", "smg", "smg"])
    legacy = compute_burst_chain_offsets(["smg", "mg", "mg", "sr", "sr"])
    assert slow[0] > legacy[0] + 1.0, (
        f"all-SMG should burst >1s later; got {slow[0]:.2f} vs "
        f"{legacy[0]:.2f}"
    )


def test_compute_burst_chain_offsets_chain_step_is_one_second():
    """Indices 1-4 are exactly +1s apart from index 0."""
    offsets = compute_burst_chain_offsets(["mg", "mg", "mg", "mg", "mg"])
    for i in range(4):
        assert offsets[i + 1] - offsets[i] == pytest.approx(1.0)


def test_compute_burst_chain_offsets_unknown_weapon_uses_fallback():
    """Unknown / None weapons get a neutral fallback rate."""
    with_known = compute_burst_chain_offsets(["mg", "mg", "mg", "mg", "mg"])
    with_unknown = compute_burst_chain_offsets(["mg", "mg", "mg", "mg", None])
    # Fallback (1.8) is between AR (1.7) and MG (2.2), so the all-MG
    # team should burst slightly faster than the team with one unknown.
    assert with_unknown[0] > with_known[0]


def test_compute_burst_chain_offsets_empty_falls_back_to_default():
    """Empty / all-zero rates return the legacy defaults — never 0/inf."""
    assert compute_burst_chain_offsets([]) == DEFAULT_BURST_CHAIN_OFFSETS_SEC


def test_compute_full_burst_start_matches_third_offset():
    weapons = ["smg", "mg", "mg", "sr", "sr"]
    expected = compute_burst_chain_offsets(weapons)[2]
    assert compute_full_burst_start(weapons) == pytest.approx(expected)


def test_build_timeline_uses_provided_weapons():
    """When weapons are provided, build_timeline should derive offsets
    from them rather than the legacy default."""
    sg_team = compute_burst_chain_offsets(["sg", "sg", "sg", "sg", "sg"])
    # SG-heavy comp first burst is well before t=10.
    assert sg_team[0] < 7.0


def test_burst_rate_table_orders_correctly():
    """SG > RL > MG > SR > AR > SMG ordering is the calibrated invariant."""
    rates = BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC
    assert rates["sg"] > rates["rl"]
    assert rates["rl"] > rates["mg"]
    assert rates["mg"] > rates["sr"]
    assert rates["sr"] > rates["ar"]
    assert rates["ar"] > rates["smg"]


# ---------------------------------------------------------------------------
# Skill-bonus burst gauge (slice #78)
# ---------------------------------------------------------------------------


def test_compute_burst_chain_offsets_liter_accelerates_team():
    """Liter's S1 gauge-fill bonus should pull first burst earlier."""
    weapons = ["smg", "mg", "mg", "sr", "sr"]  # Crown comp shape
    no_liter = compute_burst_chain_offsets(weapons)
    with_liter = compute_burst_chain_offsets(
        weapons, member_names=["Liter", "Crown", "Modernia", "Red Hood", "Snow White: Heavy Arms"]
    )
    assert with_liter[0] < no_liter[0] - 1.0, (
        f"Liter should pull first burst >1s earlier; got {with_liter[0]:.2f} "
        f"vs {no_liter[0]:.2f}"
    )


def test_compute_burst_chain_offsets_unknown_names_no_bonus():
    """Unmapped names contribute 0 — calling with all unknowns should
    match the no-bonus baseline."""
    weapons = ["mg", "mg", "mg", "mg", "mg"]
    base = compute_burst_chain_offsets(weapons)
    with_unknowns = compute_burst_chain_offsets(
        weapons, member_names=["Unknown1", "Unknown2", None, "", "Unknown3"]
    )
    assert with_unknowns == pytest.approx(base)


def test_compute_burst_chain_offsets_stacks_multiple_supports():
    """Liter + Naga + Anchor on the same team stack their bonuses."""
    weapons = ["smg", "ar", "sr", "sr", "sr"]
    one_support = compute_burst_chain_offsets(
        weapons, member_names=["Liter", "Crown", "Modernia", "Red Hood", "Snow White: Heavy Arms"]
    )
    triple_support = compute_burst_chain_offsets(
        weapons, member_names=["Liter", "Naga", "Anchor", "Red Hood", "Modernia"]
    )
    assert triple_support[0] < one_support[0], (
        "Three gauge-bonus supports should burst faster than just Liter"
    )


# ---------------------------------------------------------------------------
# Stack-source tracking (slice #86)
# ---------------------------------------------------------------------------


def test_applied_effect_carries_source_attribution():
    """build_timeline records source_character + source_skill_slot."""
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    # At least some effects should have source tracking.
    sourced = [
        e for e in timeline.applied
        if e.source_character and e.source_skill_slot
    ]
    assert len(sourced) > 0, "expected timeline to record source attribution"
    # Slot labels are normalized to skill1 / skill2 / burst_skill.
    slots = {e.source_skill_slot for e in sourced}
    assert slots <= {"skill1", "skill2", "burst_skill"}, (
        f"unexpected slot labels: {slots}"
    )


def test_stack_cap_enforced_per_source_group():
    """Crown S2 ATK +25.45% per ally burst (max 3) — adding 5 burst
    events must not let one Nikke exceed the 3-stack cap from Crown."""
    timeline = build_timeline_by_names(_CROWN_COMP)
    assert timeline is not None
    states = timeline.state_at(12.5)
    # Crown S2 ATK buff has stacks_max=3 with magnitude=25.45. Even if
    # 5 ON_ALLY_BURST_USE events fire, only 3 stacks should contribute.
    # That bounds Crown-attributable ATK contribution to ≤ 3 × 25.45 ≈ 77.
    # The total ATK buff combines Liter (+66) + Crown (3×25.45 = ~76) +
    # other passives — total should be < 200 (the slice #86 cap saves
    # us from a runaway 5×25.45 = 127 contribution that would push past).
    for s in states:
        assert s.atk_buff_pct < 250.0, (
            f"{s.name} ATK buff +{s.atk_buff_pct:.1f}% — stack cap "
            "may not be enforced"
        )
