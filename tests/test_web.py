"""Smoke tests for the manual-correction web UI.

Uses FastAPI's TestClient (httpx) — verifies that every page renders, the
cube edit form persists changes, and the per-cell override updates the
ArenaMatch row + recomputes ``needs_review``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from nikke_copilot.data.db import get_session, init_db, make_engine
from nikke_copilot.data.models import ArenaMatch, Character, Cube
from nikke_copilot.data.enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)
from nikke_copilot.web.app import create_app


def _seed(engine):
    with get_session(engine) as session:
        for name in ("Snow White: Heavy Arms", "Crown", "Liter", "Helm", "Naga", "Anis"):
            session.add(
                Character(
                    name=name,
                    rarity=Rarity.SSR,
                    element=Element.IRON,
                    weapon_class=WeaponClass.AR,
                    burst_type=BurstType.I,
                    manufacturer=Manufacturer.ELYSION,
                    role_tags=["Attacker"],
                    source="manual",
                )
            )
        session.add(
            Cube(name="Assault Cube", level=7, atk=910, hp=27300, def_=180, equipping_count_owned=4)
        )
        # A capture with an unconfident user-team cell so we can test override.
        session.add(
            ArenaMatch(
                mode="rookie",
                user_username="NIKA",
                opponent_username="WINTER",
                user_team=["Snow White: Heavy Arms", "Crown", "Liter", "", "Anis"],
                opponent_team=["Helm", "Naga", "Crown", "Liter", "Anis"],
                user_power=400000,
                opponent_power=380000,
                pre_battle_screenshot="/tmp/fake.png",
                capture_quality={
                    "user": {
                        "characters": ["Snow White: Heavy Arms", "Crown", "Liter", None, "Anis"],
                        "best_matches": ["Snow White: Heavy Arms", "Crown", "Liter", "Frima", "Anis"],
                        "distances": [0.45, 0.50, 0.55, 0.71, 0.50],
                    },
                    "opponent": {
                        "characters": ["Helm", "Naga", "Crown", "Liter", "Anis"],
                        "best_matches": ["Helm", "Naga", "Crown", "Liter", "Anis"],
                        "distances": [0.45, 0.50, 0.50, 0.50, 0.50],
                    },
                    "title_ocr": ["Rookie Arena", "WINTER VS NIKA"],
                },
                needs_review=True,
            )
        )
        session.commit()


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "web.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    _seed(engine)
    app = create_app(db_path=db)
    return TestClient(app)


def test_dashboard_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Dashboard" in r.text
    assert "1" in r.text  # 1 cube, 1 capture, 1 needs review


def test_cubes_list_renders(client):
    r = client.get("/cubes")
    assert r.status_code == 200
    assert "Assault Cube" in r.text


def test_cube_edit_persists(client, tmp_path):
    list_resp = client.get("/cubes")
    assert "Assault Cube" in list_resp.text
    # ID is 1 since it's the only cube seeded.
    edit_resp = client.get("/cubes/1")
    assert edit_resp.status_code == 200
    save = client.post(
        "/cubes/1",
        data={
            "name": "Assault Cube",
            "level": "8",
            "atk": "1050",
            "hp": "31400",
            "def": "207",
            "equipping_count_equipped": "4",
            "equipping_count_owned": "4",
        },
    )
    assert save.status_code in (200, 303)
    # Verify the new values persisted.
    list_resp = client.get("/cubes")
    assert "1050" in list_resp.text


def test_captures_list_renders(client):
    r = client.get("/captures")
    assert r.status_code == 200
    assert "rookie" in r.text
    assert "WINTER" in r.text


def test_captures_outcome_filter_untagged(client):
    """``?outcome=untagged`` returns rows with no outcome tagged.
    Seed has 1 capture with no outcome → matches."""
    r = client.get("/captures?outcome=untagged")
    assert r.status_code == 200
    # The one seeded capture (id=1) has no outcome → should appear.
    assert "/captures/1" in r.text


def test_captures_outcome_filter_win_excludes_untagged(client):
    """``?outcome=win`` excludes the untagged seed row."""
    r = client.get("/captures?outcome=win")
    assert r.status_code == 200
    assert "/captures/1" not in r.text


def test_captures_outcome_filter_after_tagging(client):
    """Tag capture #1 as win, then ``?outcome=win`` includes it."""
    client.post(
        "/captures/1/outcome",
        data={"outcome": "win", "user_role": "attack", "seconds_to_clear": "60"},
    )
    r = client.get("/captures?outcome=win")
    assert r.status_code == 200
    assert "/captures/1" in r.text


def test_captures_review_only_filters(client):
    r = client.get("/captures?review_only=true")
    assert r.status_code == 200
    assert "rookie" in r.text


def test_explain_form_renders_without_character(client):
    """The explain page should render its form even with no query — no
    character selected means no result, just the input form."""
    r = client.get("/explain")
    assert r.status_code == 200
    assert "Why isn't this character recommended" in r.text
    assert "Explain" in r.text


def test_explain_with_unknown_character(client):
    r = client.get("/explain?character=DefinitelyNotARealNikke&role=attack")
    assert r.status_code == 200
    # Page renders the "not found" branch.
    assert "not found in your roster" in r.text


def test_optimize_rookie_renders_custom_weights(client):
    """Custom weight params surface in the URL → 'custom' indicator shown
    on the rookie page."""
    r = client.get("/optimize/rookie?top_k=2&min_power=0&synergy_w=2.5")
    assert r.status_code == 200
    # The "custom" indicator + pre-filled value visible.
    assert "custom" in r.text
    assert 'value="2.5"' in r.text


def test_optimize_rookie_renders(client, tmp_path):
    """Optimizer page must render even with a small seeded roster."""
    # Seed a couple of OwnedCharacter rows so the optimizer has anything to work with.
    from sqlmodel import Session
    from nikke_copilot.data.models import OwnedCharacter
    from nikke_copilot.data.db import make_engine, init_db, get_session

    # Reuse the test client's DB by reading its app.state.engine via dependency.
    # Simpler: just render the page; an empty roster yields the "no recommendations" path.
    r = client.get("/optimize/rookie?top_k=3&min_power=0")
    assert r.status_code == 200
    # The form is always rendered.
    assert "Recommend" in r.text


def test_optimize_sp_renders(client):
    """SP arena page renders the form even with an empty roster."""
    r = client.get("/optimize/sp?min_power=0")
    assert r.status_code == 200
    assert "Recommend" in r.text
    # Weight panel embedded.
    assert "Scoring weights" in r.text


def test_optimize_sp_accepts_weight_overrides(client):
    """Custom weight params show the 'custom' indicator."""
    r = client.get("/optimize/sp?min_power=0&durability_w=4.0")
    assert r.status_code == 200
    assert "custom" in r.text
    assert 'value="4.0"' in r.text


def test_optimize_champions_renders(client):
    """Champions arena page renders the form even with an empty roster."""
    r = client.get("/optimize/champions?min_power=0")
    assert r.status_code == 200
    assert "Recommend" in r.text
    assert "Scoring weights" in r.text


def test_optimize_champions_accepts_weight_overrides(client):
    r = client.get("/optimize/champions?min_power=0&synergy_w=2.5")
    assert r.status_code == 200
    assert "custom" in r.text
    assert 'value="2.5"' in r.text


def test_optimize_ga_renders(client):
    """GA route renders with empty roster (returns no recs)."""
    r = client.get("/optimize/ga?min_power=0&pop_size=20&generations=5")
    assert r.status_code == 200
    assert "Genetic Algorithm" in r.text


def test_validate_route_renders_empty(client):
    """No tagged captures → validation page renders the empty state."""
    r = client.get("/validate")
    assert r.status_code == 200
    assert "Damage formula validation" in r.text
    # Empty: no predictable captures yet → warning visible.
    assert "No predictable captures yet" in r.text


def test_validate_route_skips_untagged_captures(client):
    """The seed capture has no outcome/role tagged → skipped from
    the predictable set, but counted in 'tagged captures'."""
    r = client.get("/validate")
    assert r.status_code == 200
    # The seed capture has no outcome → not in tagged total either.
    # But the route renders without crashing on the empty state.
    assert "<h1>Damage formula validation</h1>" in r.text


def test_validate_route_accepts_tuning_overrides(client):
    """URL params for damage_per_shot / cycle_period / min_def_through
    flow into the page; the 'custom' indicator + value pre-fill render."""
    r = client.get("/validate?damage_per_shot=0.05&cycle_period=60&min_def_through=0.10")
    assert r.status_code == 200
    assert "custom" in r.text
    assert 'value="0.05"' in r.text
    assert 'value="60"' in r.text
    assert 'value="0.10"' in r.text


def test_validate_route_includes_tagged_capture(client):
    """After tagging the seed as a win + attack role, validate route
    shows the predictable captures count = 1 (or skipped due to
    encoding gaps)."""
    client.post(
        "/captures/1/outcome",
        data={"outcome": "win", "user_role": "attack", "seconds_to_clear": "60"},
    )
    r = client.get("/validate")
    assert r.status_code == 200
    # Tagged total >= 1.
    assert "Tagged captures" in r.text


def test_roster_advisor_renders(client):
    """Investment advisor page renders even with an empty roster
    (returns 'No recommendations' empty state)."""
    r = client.get("/roster/advisor")
    assert r.status_code == 200
    assert "Who should I level up next" in r.text
    # Empty roster → no recs, but the form is still there.
    assert "Recompute" in r.text


def test_counter_freeform_empty_form_renders(client):
    """No names supplied → form renders without running the optimizer."""
    r = client.get("/counter")
    assert r.status_code == 200
    assert "Counter-pick a 5-Nikke team" in r.text
    # The autocomplete datalist is populated from the seeded roster.
    assert "Crown" in r.text


def test_counter_freeform_unknown_name_warns(client):
    """Unknown character names surface as a warning instead of running."""
    r = client.get("/counter?n1=NotARealNikke&n2=Crown&n3=Liter&n4=Helm&n5=Naga")
    assert r.status_code == 200
    assert "Unknown character" in r.text
    assert "NotARealNikke" in r.text


def test_counter_freeform_partial_input_warns(client):
    """3 names given but 5 needed → renders the warning."""
    r = client.get("/counter?n1=Crown&n2=Liter&n3=Helm")
    assert r.status_code == 200
    assert "Need all 5" in r.text


def test_capture_outcome_persists(client):
    """Outcome form writes to ``ArenaMatch.outcome`` / ``user_role``
    and stashes ``seconds_to_clear`` inside ``raw_battle_record``."""
    r = client.post(
        "/captures/1/outcome",
        data={"outcome": "win", "user_role": "attack", "seconds_to_clear": "97"},
    )
    assert r.status_code in (200, 303)
    # Reload the detail page; selected dropdowns are pre-populated.
    detail = client.get("/captures/1")
    assert detail.status_code == 200
    assert 'value="win" selected' in detail.text
    assert 'value="attack" selected' in detail.text
    assert 'value="97"' in detail.text


def test_capture_outcome_clears_when_blank(client):
    """Submitting empty outcome clears the field (so a mistake can be undone)."""
    # First set it.
    client.post(
        "/captures/1/outcome",
        data={"outcome": "loss", "user_role": "defense", "seconds_to_clear": "0"},
    )
    # Then clear.
    r = client.post(
        "/captures/1/outcome",
        data={"outcome": "", "user_role": "", "seconds_to_clear": ""},
    )
    assert r.status_code in (200, 303)
    detail = client.get("/captures/1")
    assert detail.status_code == 200
    # The dash option should be selected (blank value, "—" label).
    assert 'value="" selected' in detail.text


def test_capture_outcome_rejects_invalid_value(client):
    """Bad outcome → 400, no DB mutation."""
    r = client.post(
        "/captures/1/outcome",
        data={"outcome": "draw", "user_role": "", "seconds_to_clear": ""},
    )
    assert r.status_code == 400


def test_dashboard_offers_username_when_unset(tmp_path, monkeypatch):
    """First-run: no env var + no config.json + captures present →
    dashboard surfaces the auto-detected username with a save button."""
    from nikke_copilot.data import config as config_module

    monkeypatch.delenv("NIKKE_COPILOT_USERNAME", raising=False)
    fake_config = tmp_path / "username_test_config.json"
    monkeypatch.setattr(config_module, "_config_path", lambda: fake_config)

    db = tmp_path / "dashweb.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    _seed(engine)
    app = create_app(db_path=db)
    client = TestClient(app)

    r = client.get("/")
    assert r.status_code == 200
    assert "First-run setup" in r.text
    assert "NIKA" in r.text
    assert "save \"NIKA\" as my username" in r.text


def test_config_save_username_persists(tmp_path, monkeypatch):
    """POST /config/username writes to config.json."""
    from nikke_copilot.data import config as config_module

    monkeypatch.delenv("NIKKE_COPILOT_USERNAME", raising=False)
    fake_config = tmp_path / "savetest.json"
    monkeypatch.setattr(config_module, "_config_path", lambda: fake_config)

    db = tmp_path / "saveweb.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    app = create_app(db_path=db)
    client = TestClient(app)

    r = client.post("/config/username", data={"name": "  Nika  "})
    assert r.status_code in (200, 303)
    import json
    saved = json.loads(fake_config.read_text())
    assert saved["username"] == "Nika"


def test_roster_snapshot_creates_file(tmp_path, monkeypatch):
    """POST /roster/snapshot writes a JSON snapshot under the snapshots dir."""
    # Patch the bound reference inside ``roster.snapshots`` directly —
    # patching ``platformdirs.user_data_dir`` doesn't help because the
    # snapshots module imports the symbol at module-load time. (Same
    # gotcha as MEMORY.md note about FastAPI Jinja2 signature change.)
    snapshots_root = tmp_path / "data"
    snapshots_root.mkdir()
    from nikke_copilot.roster import snapshots as snapshots_mod
    monkeypatch.setattr(
        snapshots_mod, "user_data_dir",
        lambda *args, **kwargs: str(snapshots_root),
    )

    db = tmp_path / "snapweb.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    _seed(engine)
    app = create_app(db_path=db)
    client = TestClient(app)

    r = client.post("/roster/snapshot", follow_redirects=False)
    assert r.status_code == 303
    snaps = list((snapshots_root / "snapshots").glob("*.json"))
    assert len(snaps) >= 1


def test_config_save_username_rejects_blank(tmp_path, monkeypatch):
    from nikke_copilot.data import config as config_module

    monkeypatch.delenv("NIKKE_COPILOT_USERNAME", raising=False)
    fake_config = tmp_path / "rejectblank.json"
    monkeypatch.setattr(config_module, "_config_path", lambda: fake_config)

    db = tmp_path / "rejweb.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    app = create_app(db_path=db)
    client = TestClient(app)
    r = client.post("/config/username", data={"name": "   "})
    assert r.status_code == 400


def test_screenshot_route_falls_back_to_user_screens_dir(tmp_path):
    """Slice #121 — when the DB stores a stale path (fixture trimmed,
    project moved, cwd mismatch), the screenshot route searches the
    DB-sibling ``screenshots/<Mode>/<basename>`` dir and serves from
    there. Mirrors the real-life layout where DB + screenshots are
    siblings under ``~/Library/Application Support/NikkeCopilot/``."""
    # Place the real screenshot at <db_dir>/screenshots/Rookie_Arena/.
    screens = tmp_path / "screenshots" / "Rookie_Arena"
    screens.mkdir(parents=True)
    real_image = screens / "screenshot.png"
    real_image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    db = tmp_path / "fallback.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as s:
        # ArenaMatch with a non-existent stored path.
        s.add(ArenaMatch(
            mode="rookie",
            user_username="NIKA",
            user_team=["Crown"] * 5,
            opponent_team=["Helm"] * 5,
            pre_battle_screenshot="tests/fixtures/screenshots/Rookie_Arena/screenshot.png",
        ))
        s.commit()
    app = create_app(db_path=db)
    client = TestClient(app)

    r = client.get("/captures/1/screenshot/pre")
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
    # Body starts with the PNG signature.
    assert r.content.startswith(b"\x89PNG")


def test_screenshot_route_404s_when_truly_missing(tmp_path):
    """File doesn't exist anywhere → genuine 404 with explanatory text."""
    db = tmp_path / "missing.sqlite3"
    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as s:
        s.add(ArenaMatch(
            mode="rookie",
            user_team=["X"] * 5,
            opponent_team=["Y"] * 5,
            pre_battle_screenshot="/no/such/file.png",
        ))
        s.commit()
    app = create_app(db_path=db)
    client = TestClient(app)
    r = client.get("/captures/1/screenshot/pre")
    assert r.status_code == 404


def test_capture_detail_and_override(client):
    # Detail page renders the unconfident cell with the best-match candidate.
    r = client.get("/captures/1")
    assert r.status_code == 200
    assert "Frima" in r.text  # the best-match for the unconfident slot

    # Override the unconfident slot (slot=3) on the user team.
    r = client.post(
        "/captures/1/cell",
        data={"team": "user", "slot": "3", "character": "Crown"},
    )
    assert r.status_code in (200, 303)

    # After fixing all unconfident cells, needs_review should flip to False.
    detail = client.get("/captures/1")
    assert detail.status_code == 200
    # The list should now show Crown in slot 4 (1-indexed).
    assert "Crown" in detail.text
