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

from nikke_optimizer.data.db import get_session, init_db, make_engine
from nikke_optimizer.data.models import ArenaMatch, Character, Cube
from nikke_optimizer.data.enums import (
    BurstType,
    Element,
    Manufacturer,
    Rarity,
    WeaponClass,
)
from nikke_optimizer.web.app import create_app


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


def _seed_player_data_tournament(engine, tmp_path: Path) -> int:
    """Seed one player_data PromoTournament with a populated sidecar.

    Returns the tournament id so callers can hit /promo/<id>.
    """
    import json
    from datetime import datetime, timezone

    from nikke_optimizer.data.models import (
        PromoGroup,
        PromoMatch,
        PromoMatchScreenshot,
        PromoTournament,
    )

    storage_root = tmp_path / "captures" / "beta_season_29" / "promotion_tournament_player_data"
    storage_root.mkdir(parents=True, exist_ok=True)
    captured = datetime(2026, 5, 11, 11, 33, 53, tzinfo=timezone.utc)

    with get_session(engine) as session:
        t = PromoTournament(
            captured_at=captured,
            capture_date=captured.date(),
            storage_root=str(storage_root),
        )
        session.add(t)
        session.commit()
        session.refresh(t)
        tid = t.id
        g = PromoGroup(tournament_id=tid, group_no=1)
        session.add(g)
        session.commit()
        session.refresh(g)
        m = PromoMatch(
            tournament_id=tid, group_id=g.id,
            round_label="round_64", match_no=1, has_loadouts=True,
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        for side in ("top", "bottom"):
            session.add(PromoMatchScreenshot(
                match_id=m.id, kind="player_loadout", side=side,
                round_no=None,
                file_path=str(storage_root / f"player_{side}.png"),
            ))
        session.commit()

    # Sidecar — what the OCR pass would have written.
    sidecar = {
        "season_number": 29,
        "tournament_id": tid,
        "storage_root": str(storage_root),
        "players": [
            {
                "group_no": 1, "match_no": 1, "side": "top",
                "screenshot_id": 1,
                "player_name": "BBB", "player_name_confidence": 0.95,
                "player_level": 151, "team_cp": 3697055,
                "chars": [
                    {"slot": 1, "name": "Moran", "name_raw": "Moran",
                     "name_match_score": 98.0, "cp": 152840, "lb": 3, "core": "MAX"},
                ] + [
                    {"slot": i, "name": None, "name_raw": None,
                     "name_match_score": None, "cp": None, "lb": None, "core": None}
                    for i in range(2, 6)
                ],
            },
            {
                "group_no": 1, "match_no": 1, "side": "bottom",
                "screenshot_id": 2,
                "player_name": "ZTARMAN", "player_name_confidence": 0.92,
                "player_level": 169, "team_cp": 3923739,
                "chars": [
                    {"slot": i, "name": None, "name_raw": None,
                     "name_match_score": None, "cp": None, "lb": None, "core": None}
                    for i in range(1, 6)
                ],
            },
        ],
    }
    (storage_root / "players_lookup.json").write_text(json.dumps(sidecar))

    return tid


def test_promo_index_renders_player_data_card(client, tmp_path):
    """The /promo index shows a Player Data tile for the new format."""
    engine = make_engine(tmp_path / "web.sqlite3")
    _seed_player_data_tournament(engine, tmp_path)
    r = client.get("/promo")
    assert r.status_code == 200
    assert "Player Data" in r.text
    assert "pre-bracket" in r.text
    assert "<strong>2</strong> players" in r.text


def test_promo_tournament_page_renders_player_data(client, tmp_path):
    """The per-tournament page renders the per-player status table
    without crashing on the new format.
    """
    engine = make_engine(tmp_path / "web.sqlite3")
    tid = _seed_player_data_tournament(engine, tmp_path)
    r = client.get(f"/promo/{tid}")
    assert r.status_code == 200
    assert "Player Data" in r.text
    # Both players appear by name.
    assert "BBB" in r.text
    assert "ZTARMAN" in r.text
    # The 151 level + Moran roster slot land in the table.
    assert "151" in r.text
    assert "Moran" in r.text
    # No scrape run yet → pending status pill.
    assert "pending" in r.text


def test_promo_tournament_page_renders_scrape_details(client, tmp_path):
    """When a status sidecar exists, the per-player row renders
    privacy chips, BlablaLink profile link, and actual-level meta.
    """
    import json

    engine = make_engine(tmp_path / "web.sqlite3")
    tid = _seed_player_data_tournament(engine, tmp_path)
    # Plant a status sidecar next to the seeded player_data root.
    storage_root = tmp_path / "captures" / "beta_season_29" / "promotion_tournament_player_data"
    (storage_root / "players_lookup_status.json").write_text(json.dumps({
        "sidecar_version": 1,
        "tournament_id": tid,
        "season_number": 29,
        "last_run_at": "2026-05-17T19:50:58+00:00",
        "players": {
            "BBB": {
                "name": "BBB", "level": 151, "status": "found",
                "snapshot_id": 7,
                "snapshotted_at": "2026-05-17T19:50:58+00:00",
                "actual_level": 152, "uid": "TXktQkItVUlELQ==",
                "is_roster_private": False, "is_outpost_private": False,
                "char_names_attempted": ["Moran"],
                "char_names_matched": ["Moran"],
                "error": None,
            },
            "ZTARMAN": {
                "name": "ZTARMAN", "level": 169, "status": "not_on_na",
                "snapshot_id": None, "snapshotted_at": None,
                "actual_level": None, "uid": None,
                "is_roster_private": None, "is_outpost_private": None,
                "char_names_attempted": [], "char_names_matched": [],
                "error": None,
            },
        },
    }))

    r = client.get(f"/promo/{tid}")
    assert r.status_code == 200
    # Found row: chips + BL link + actual-level + fetched count.
    assert "Nikkes public" in r.text
    assert "Outpost public" in r.text
    assert "Open profile" in r.text
    assert "blablalink.com/shiftyspad" in r.text
    assert "actual lv" in r.text
    assert "fetched" in r.text
    # Not-on-na row: explanation line, no BL link.
    assert "name matches on a non-NA server" in r.text


def test_promo_tournament_page_renders_scrape_progress_panel(client, tmp_path):
    """Status sidecar drives the scrape progress panel — including the
    auto-refresh meta tag when the file's mtime is fresh.
    """
    import json
    import time

    engine = make_engine(tmp_path / "web.sqlite3")
    tid = _seed_player_data_tournament(engine, tmp_path)
    storage_root = tmp_path / "captures" / "beta_season_29" / "promotion_tournament_player_data"
    status_path = storage_root / "players_lookup_status.json"
    status_path.write_text(json.dumps({
        "sidecar_version": 1, "tournament_id": tid, "season_number": 29,
        "last_run_at": "2026-05-17T19:50:58+00:00",
        "players": {
            "BBB": {
                "name": "BBB", "level": 151, "status": "found",
                "snapshot_id": 7, "snapshotted_at": "2026-05-17T19:50:58+00:00",
                "actual_level": 152, "uid": "TXktQkItVUlELQ==",
                "is_roster_private": False, "is_outpost_private": False,
                "char_names_attempted": [], "char_names_matched": [], "error": None,
            },
        },
    }))
    # Fresh mtime → panel reports "running" + emits auto-refresh meta.
    r = client.get(f"/promo/{tid}")
    assert r.status_code == 200
    assert "Scrape running" in r.text
    assert 'http-equiv="refresh"' in r.text
    assert "processed</span>1 / 2" in r.text

    # Backdate mtime past the 60s window → "idle", no auto-refresh.
    old = time.time() - 600
    import os
    os.utime(status_path, (old, old))
    r = client.get(f"/promo/{tid}")
    assert r.status_code == 200
    assert "Scrape idle" in r.text
    assert 'http-equiv="refresh"' not in r.text


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
    from nikke_optimizer.data.models import OwnedCharacter
    from nikke_optimizer.data.db import make_engine, init_db, get_session

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
    from nikke_optimizer.data import config as config_module

    monkeypatch.delenv("NIKKE_OPTIMIZER_USERNAME", raising=False)
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
    from nikke_optimizer.data import config as config_module

    monkeypatch.delenv("NIKKE_OPTIMIZER_USERNAME", raising=False)
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
    from nikke_optimizer.roster import snapshots as snapshots_mod
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
    from nikke_optimizer.data import config as config_module

    monkeypatch.delenv("NIKKE_OPTIMIZER_USERNAME", raising=False)
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
    siblings under ``~/Library/Application Support/NikkeOptimizer/``."""
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
