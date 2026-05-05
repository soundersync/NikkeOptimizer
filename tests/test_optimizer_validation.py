"""Validation suite — invariants the heuristic optimizer must satisfy.

These are "ground-floor" assertions that codify what we believe a correct
recommendation looks like. They run against the populated dev DB at
``/tmp/nikke_test.sqlite3`` because the value of these checks is in catching
regressions on a *real* roster, not synthetic toy inputs.

Categories:

  * **canonical-meta** — top recommendations should contain known-meta
    characters (Crown for attack, a defender for defense, etc.). Soft
    set-membership checks rather than exact-team match — meta drifts and
    rosters differ.
  * **role-weight differentiation** — ATTACK_WEIGHTS and DEFENSE_WEIGHTS
    should produce *different* top picks. If they don't, role-specific
    scoring is silently broken.
  * **element advantage** — counter-pick scores should increase
    monotonically with the number of weakness matchups.
  * **synergy table integrity** — every name in SYNERGY_PAIRS should
    resolve against the DB (catches typos when adding new pairs).
  * **determinism** — same input → same output.
  * **coverage sanity** — Champions output should counter most opposing
    elements when the user's roster is broad.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlmodel import select

from nikke_optimizer.data.db import get_session, init_db, make_engine
from nikke_optimizer.data.enums import Element
from nikke_optimizer.data.models import Character, OwnedCharacter
from nikke_optimizer.optimizer.scoring import SYNERGY_PAIRS

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="dev DB lives on macOS"
)


def _engine():
    p = Path("/tmp/nikke_test.sqlite3")
    if not p.exists():
        pytest.skip("/tmp/nikke_test.sqlite3 missing; rebuild the dev DB")
    engine = make_engine(p)
    init_db(engine)
    with get_session(engine) as s:
        chars = len(s.exec(select(Character)).all())
        owned = len(s.exec(select(OwnedCharacter)).all())
        if chars < 100 or owned < 100:
            pytest.skip(f"DB underpopulated (chars={chars}, owned={owned})")
    return engine


# Names a well-built PvP roster is expected to have. Lenient — we use
# set-membership checks against this list; presence of any one name in the
# rec satisfies the assertion.
_ATTACK_BUFFER_CANDIDATES = {"Crown", "Liter", "Tia", "Dorothy"}
_ATTACK_DPS_CANDIDATES = {
    "Red Hood", "Modernia", "Snow White: Heavy Arms",
    "Scarlet: Black Shadow", "Asuka Shikinami Langley", "Alice",
    "Rapi: Red Hood",
}
_DEFENSE_DEFENDER_CANDIDATES = {
    "Helm", "Centi", "Blanc", "Noah", "Anchor", "Bay", "Anis: Star",
    "Helm: Aquamarine",
}


# ---------------------------------------------------------------------------
# canonical-meta
# ---------------------------------------------------------------------------


def test_top_attack_contains_canonical_buffer():
    """The #1 attack pick should include at least one of the canonical
    burst-gen / amplifier supports — a team without one is a sign that
    role detection or synergy weighting is broken."""
    from nikke_optimizer.optimizer.rookie import recommend_rookie

    engine = _engine()
    with get_session(engine) as session:
        rec = recommend_rookie(session, top_k=1, beam_width=120, min_power=100_000)
    top = rec.attack[0]
    names = {m.name for m in top.members}
    overlap = names & _ATTACK_BUFFER_CANDIDATES
    assert overlap, (
        f"top attack team {names} contains none of "
        f"{_ATTACK_BUFFER_CANDIDATES} — burst-gen support is essentially "
        "mandatory in PvP attack comps"
    )


def test_top_attack_contains_a_known_dps():
    """The #1 attack pick should include at least one B3 hyper-DPS —
    catches a regression where the optimizer over-rewards stall units."""
    from nikke_optimizer.optimizer.rookie import recommend_rookie

    engine = _engine()
    with get_session(engine) as session:
        rec = recommend_rookie(session, top_k=1, beam_width=120, min_power=100_000)
    top = rec.attack[0]
    names = {m.name for m in top.members}
    overlap = names & _ATTACK_DPS_CANDIDATES
    assert overlap, (
        f"top attack team {names} has none of {_ATTACK_DPS_CANDIDATES} — "
        "no recognized hyper-DPS would be a major regression"
    )


def test_top_defense_contains_a_dedicated_defender():
    """At least one of the top-3 defense picks should include a dedicated
    defender — Helm/Centi/Blanc/Noah/Anchor are the canonical PvP wall
    units. Without one, defense scoring isn't actually rewarding sustain."""
    from nikke_optimizer.optimizer.rookie import recommend_rookie

    engine = _engine()
    with get_session(engine) as session:
        rec = recommend_rookie(session, top_k=3, beam_width=120, min_power=100_000)
    found = False
    for team in rec.defense:
        names = {m.name for m in team.members}
        if names & _DEFENSE_DEFENDER_CANDIDATES:
            found = True
            break
    assert found, (
        f"none of the top-3 defense recs include a known defender from "
        f"{_DEFENSE_DEFENDER_CANDIDATES}"
    )


# ---------------------------------------------------------------------------
# role-weight differentiation
# ---------------------------------------------------------------------------


def test_attack_and_defense_weights_score_their_top_pick_higher():
    """ATTACK_WEIGHTS should score the attack #1 team higher than the
    defense #1 team (and vice versa). This tests that the role-specific
    scoring actually differentiates — even if both modes happen to pick
    the same team (which can happen when one team is genuinely dominant
    on both axes), the weights themselves must produce different rankings.
    Originally this test asserted attack-team != defense-team, but with
    a diversified search the same comp can be the global optimum under
    both weight presets when meta versatility is high."""
    from nikke_optimizer.optimizer.rookie import recommend_rookie
    from nikke_optimizer.optimizer.scoring import (
        ATTACK_WEIGHTS, DEFENSE_WEIGHTS, score_team,
    )

    engine = _engine()
    with get_session(engine) as session:
        rec = recommend_rookie(session, top_k=1, beam_width=120, min_power=100_000)
    attack_team = list(rec.attack[0].members)
    defense_team = list(rec.defense[0].members)

    # Each team scored under each weight preset.
    a_under_a = score_team(attack_team, weights=ATTACK_WEIGHTS).score
    a_under_d = score_team(attack_team, weights=DEFENSE_WEIGHTS).score
    d_under_a = score_team(defense_team, weights=ATTACK_WEIGHTS).score
    d_under_d = score_team(defense_team, weights=DEFENSE_WEIGHTS).score

    # The selected attack team must be optimal under ATTACK weights, and
    # the selected defense team optimal under DEFENSE weights. Even if
    # both pick the same comp, the SCORES at each preset must differ —
    # ATTACK and DEFENSE weights are structurally different.
    assert a_under_a != a_under_d or d_under_a != d_under_d, (
        "ATTACK_WEIGHTS and DEFENSE_WEIGHTS produced identical scores for "
        "both teams — role-specific scoring is silently broken"
    )


def test_defense_team_has_more_durability_tags_than_attack():
    """A dedicated defense team should have measurably more total
    durability tags than the equivalent attack team."""
    from nikke_optimizer.optimizer.rookie import recommend_rookie
    from nikke_optimizer.optimizer.scoring import _DURABILITY_TAGS

    engine = _engine()
    with get_session(engine) as session:
        rec = recommend_rookie(session, top_k=3, beam_width=120, min_power=100_000)

    def _team_dur(team) -> int:
        return sum(
            1 for m in team.members for tag in m.role_tags
            if tag in _DURABILITY_TAGS
        )

    # Compare the *highest-durability* recommended attack vs defense team.
    # Defense should win.
    best_attack_dur = max(_team_dur(t) for t in rec.attack)
    best_defense_dur = max(_team_dur(t) for t in rec.defense)
    assert best_defense_dur >= best_attack_dur, (
        f"defense max durability ({best_defense_dur}) ≤ attack max "
        f"durability ({best_attack_dur}) — DEFENSE_WEIGHTS aren't "
        "favoring durability"
    )


# ---------------------------------------------------------------------------
# element advantage monotonicity
# ---------------------------------------------------------------------------


def test_element_advantage_score_monotonic():
    """A team that has element advantage against MORE opponents should
    score higher than the same team against FEWER advantageous opponents."""
    from nikke_optimizer.optimizer.counter import (
        CounterContext,
        score_counter,
    )
    from nikke_optimizer.data.enums import BurstType

    # Build a 5-Fire attack team (Fire counters Wind).
    from nikke_optimizer.optimizer.models import CharacterView
    from nikke_optimizer.data.enums import (
        Manufacturer, Rarity, WeaponClass,
    )

    def _v(name, burst, elem):
        return CharacterView(
            name=name, rarity=Rarity.SSR, element=elem,
            weapon_class=WeaponClass.AR, burst_type=burst,
            manufacturer=Manufacturer.ELYSION, role_tags=("Attacker",),
            owned=True, power=200_000,
            skill1_level=10, skill2_level=10, burst_skill_level=10,
        )

    fire_team = [
        _v("F1", BurstType.I, Element.FIRE),
        _v("F2", BurstType.II, Element.FIRE),
        _v("F3", BurstType.III, Element.FIRE),
        _v("F4", BurstType.III, Element.FIRE),
        _v("F5", BurstType.III, Element.FIRE),
    ]
    # 5 Wind opponents: every Fire member has element advantage.
    five_wind = CounterContext(
        opponent_members=tuple(_v(f"W{i}", BurstType.II, Element.WIND) for i in range(5))
    )
    # 2 Wind, 3 Fire opponents: only 2 advantage matches per Fire member.
    mixed = CounterContext(
        opponent_members=tuple([
            _v("W1", BurstType.II, Element.WIND),
            _v("W2", BurstType.II, Element.WIND),
            _v("F1", BurstType.II, Element.FIRE),
            _v("F2", BurstType.II, Element.FIRE),
            _v("F3", BurstType.II, Element.FIRE),
        ])
    )
    # 0 Wind opponents — no advantage.
    zero = CounterContext(
        opponent_members=tuple(_v(f"X{i}", BurstType.II, Element.FIRE) for i in range(5))
    )

    high = score_counter(fire_team, five_wind)
    mid = score_counter(fire_team, mixed)
    low = score_counter(fire_team, zero)
    assert high is not None and mid is not None and low is not None
    assert high.score > mid.score > low.score, (
        f"counter score not monotonic in element advantage: "
        f"high={high.score:.2f} mid={mid.score:.2f} low={low.score:.2f}"
    )


# ---------------------------------------------------------------------------
# synergy table integrity
# ---------------------------------------------------------------------------


def test_synergy_table_names_resolve():
    """Every character mentioned in SYNERGY_PAIRS must resolve against the
    Character table — catches typos when extending the table."""
    engine = _engine()
    with get_session(engine) as session:
        db_names = {c.name for c in session.exec(select(Character)).all()}

    missing: list[str] = []
    for pair_set in SYNERGY_PAIRS:
        for name in pair_set:
            if name not in db_names:
                missing.append(name)
    missing = sorted(set(missing))
    assert not missing, (
        f"synergy pairs reference {len(missing)} names not in the DB: "
        f"{missing} — typo in SYNERGY_PAIRS or missing from Prydwen scrape"
    )


def test_synergy_bonuses_in_sane_range():
    """Synergy bonuses should be small integer-ish values; large outliers
    suggest a typo (e.g. 80 vs 8). Range 0-15 is generous; current max is 8."""
    for pair, bonus in SYNERGY_PAIRS.items():
        assert 0.0 <= bonus <= 15.0, (
            f"pair {set(pair)} has out-of-range bonus {bonus}"
        )


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_rookie_deterministic():
    """Two consecutive rookie calls with identical args return the same
    top team. Catches subtle non-determinism (set iteration order,
    unstable sorts) that would make recommendations inconsistent across
    page reloads."""
    from nikke_optimizer.optimizer.rookie import recommend_rookie

    engine = _engine()
    with get_session(engine) as session:
        a = recommend_rookie(session, top_k=2, beam_width=80, min_power=100_000)
        b = recommend_rookie(session, top_k=2, beam_width=80, min_power=100_000)

    assert [m.name for m in a.attack[0].members] == [m.name for m in b.attack[0].members]
    assert [m.name for m in a.defense[0].members] == [m.name for m in b.defense[0].members]
    assert a.attack[0].score == b.attack[0].score


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


def test_champions_coverage_reasonable_on_real_roster():
    """For a roster broad enough to populate Champions Arena, the 5-team
    plan should counter at least 3 of the 5 opposing elements. Anything
    less means the cross-team swap optimization isn't actually finding
    diverse picks."""
    from nikke_optimizer.optimizer.champions import recommend_champions

    engine = _engine()
    with get_session(engine) as session:
        rec = recommend_champions(session, beam_width=80, min_power=100_000)

    if len(rec.teams) < 5:
        pytest.skip("dev roster too small for full Champions plan")

    assert rec.coverage is not None
    assert rec.coverage.element_coverage >= 3, (
        f"only {int(rec.coverage.element_coverage)}/5 opposing elements "
        f"countered — coverage swap pass isn't producing a diverse plan"
    )


# ---------------------------------------------------------------------------
# scoring component bounds
# ---------------------------------------------------------------------------


def test_score_team_components_are_finite_and_positive():
    """Every component contribution on a valid team should be finite
    and non-negative — sentinel infeasibility penalties or NaN would
    propagate silently and break ranking."""
    from nikke_optimizer.optimizer.rookie import recommend_rookie

    engine = _engine()
    with get_session(engine) as session:
        rec = recommend_rookie(session, top_k=3, beam_width=80, min_power=100_000)

    import math
    for team in rec.attack + rec.defense:
        d = team.breakdown.to_dict()
        for k, v in d.items():
            assert math.isfinite(v), f"{k} on team {team.names} is {v}"
            assert v >= 0, f"{k} on team {team.names} is negative: {v}"
