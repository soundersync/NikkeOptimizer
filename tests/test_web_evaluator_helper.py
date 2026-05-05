"""Smoke tests for the web evaluator helper.

Verifies that ``evaluations_for`` returns a parallel list with
TeamEvaluation for fully-encoded teams and MissingEncoding for
partially-encoded ones.
"""

from __future__ import annotations

import pytest

from nikke_optimizer.data.enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)
from nikke_optimizer.optimizer.models import (
    CharacterView,
    ScoreBreakdown,
    TeamCandidate,
)
from nikke_optimizer.simulator.evaluator import TeamEvaluation
from nikke_optimizer.web.evaluator_helper import MissingEncoding, evaluations_for


def _view(name: str) -> CharacterView:
    return CharacterView(
        name=name,
        rarity=Rarity.SSR,
        element=Element.IRON,
        weapon_class=WeaponClass.AR,
        burst_type=BurstType.II,
        manufacturer=Manufacturer.ELYSION,
        role_tags=("Attacker",),
        owned=True,
        power=200_000,
    )


def _team(names: list[str]) -> TeamCandidate:
    return TeamCandidate(
        members=tuple(_view(n) for n in names),
        breakdown=ScoreBreakdown(total=10.0),
    )


def test_evaluations_for_fully_encoded_team_returns_evaluation():
    """Crown comp is fully encoded — should get a TeamEvaluation back."""
    crown_comp = _team(
        ["Liter", "Crown", "Modernia", "Red Hood", "Snow White: Heavy Arms"]
    )
    results = evaluations_for([crown_comp])
    assert len(results) == 1
    assert isinstance(results[0], TeamEvaluation)
    # Sanity: the eval should have positive dps.
    assert results[0].dps_estimate > 0


def test_evaluations_for_partial_encoding_returns_missing():
    """A team with one un-encoded member returns MissingEncoding listing
    just that member."""
    team = _team(["Liter", "Crown", "DefinitelyNotEncoded", "Red Hood", "Modernia"])
    results = evaluations_for([team])
    assert len(results) == 1
    miss = results[0]
    assert isinstance(miss, MissingEncoding)
    assert miss.missing == ("DefinitelyNotEncoded",)


def test_evaluations_for_preserves_order():
    """Each input team gets a result at the same index."""
    encoded = _team(["Liter", "Crown", "Modernia", "Red Hood", "Snow White: Heavy Arms"])
    partial = _team(["Liter", "Crown", "X", "Y", "Z"])
    results = evaluations_for([encoded, partial, encoded])
    assert isinstance(results[0], TeamEvaluation)
    assert isinstance(results[1], MissingEncoding)
    assert isinstance(results[2], TeamEvaluation)


def test_missing_encoding_is_falsy():
    """Templates use ``{% if eval %}`` to branch — MissingEncoding must
    evaluate to False so the template can show the 'N/A' panel without
    inspecting the type."""
    miss = MissingEncoding(missing=("X",))
    assert not miss
    if miss:
        pytest.fail("MissingEncoding should be falsy")
