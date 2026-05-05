"""Delete-route tests for slice #136.

Covers:
  * POST /captures/{id}/delete deletes one row + its upload file
  * POST /sessions/{sid}/delete deletes every row in a session + its files
  * POST /captures/discard-needs-review bulk-deletes flagged rows
  * The safety rail: refuses to delete files outside <db_dir>/uploads/
  * Session-kind recompute after a single-row delete
"""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pytest

# Skip when the full web stack isn't available (FastAPI + sqlmodel).
for _missing in ("fastapi", "sqlmodel", "PIL"):
    if importlib.util.find_spec(_missing) is None:  # pragma: no cover
        pytest.skip(f"{_missing} not available", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import select  # noqa: E402

from nikke_optimizer.data.db import get_session, init_db, make_engine  # noqa: E402
from nikke_optimizer.data.models import ArenaMatch  # noqa: E402
from nikke_optimizer.roster.arena_importer import (  # noqa: E402
    SESSION_KIND_PARTIAL,
)
from nikke_optimizer.web.app import create_app  # noqa: E402


def _make_uploads_dir(db_path: Path) -> Path:
    d = db_path.parent / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seed_session(db_path: Path, session_id: str) -> dict:
    """Seed a complete Champions session backed by real files in uploads/.

    Returns ``{capture_id: file_path}`` so the test can verify file
    cleanup independently of the DB rows.
    """
    uploads = _make_uploads_dir(db_path)
    engine = make_engine(db_path)
    init_db(engine)
    file_map: dict[int, Path] = {}
    with get_session(engine) as session:
        for round_idx in range(1, 6):
            for who in ("NIKA", "OPPONENT"):
                p = uploads / f"loadout_{round_idx}_{who.lower()}.png"
                p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
                row = ArenaMatch(
                    mode="champion",
                    round_index=round_idx,
                    user_username=who,
                    user_team=["A", "B", "C", "D", "E"],
                    session_id=session_id,
                    session_kind="complete",
                    pre_battle_screenshot=str(p),
                    needs_review=(who == "OPPONENT"),  # half flagged
                )
                session.add(row)
                session.flush()
                file_map[row.id] = p
            br_p = uploads / f"br_{round_idx}.png"
            br_p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 16)
            br_row = ArenaMatch(
                mode="champion_battle_record",
                round_index=round_idx,
                user_team=["A", "B", "C", "D", "E"],
                opponent_team=["X", "Y", "Z", "W", "V"],
                session_id=session_id,
                session_kind="complete",
                battle_record_screenshot=str(br_p),
            )
            session.add(br_row)
            session.flush()
            file_map[br_row.id] = br_p
        duel_p = uploads / "duel_result.png"
        duel_p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"z" * 16)
        duel = ArenaMatch(
            mode="champion_duel_result",
            session_id=session_id,
            session_kind="complete",
            battle_record_screenshot=str(duel_p),
        )
        session.add(duel)
        session.flush()
        file_map[duel.id] = duel_p
        session.commit()
    return file_map


def _client(db_path: Path) -> TestClient:
    app = create_app(db_path=db_path, portrait_library=None)
    return TestClient(app)


def test_delete_one_row_removes_screenshot_and_redirects():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "t.sqlite3"
        sid = "delete-test-1"
        files = _seed_session(db_path, sid)

        # Pick the first BR row.
        engine = make_engine(db_path)
        with get_session(engine) as session:
            br = session.exec(
                select(ArenaMatch).where(
                    ArenaMatch.session_id == sid,
                    ArenaMatch.mode == "champion_battle_record",
                )
            ).first()
        assert br is not None
        screenshot = Path(br.battle_record_screenshot)
        assert screenshot.exists()

        client = _client(db_path)
        r = client.post(
            f"/captures/{br.id}/delete",
            data={"return_to": "preview"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert sid in r.headers["location"]
        assert not screenshot.exists(), "upload file should be deleted"

        # Session kind should have downgraded from complete → partial.
        with get_session(engine) as session:
            survivors = list(session.exec(
                select(ArenaMatch).where(ArenaMatch.session_id == sid)
            ).all())
        assert len(survivors) == 15
        assert all(s.session_kind == SESSION_KIND_PARTIAL for s in survivors)


def test_delete_whole_session_clears_all_files():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "t.sqlite3"
        sid = "delete-test-session"
        files = _seed_session(db_path, sid)
        uploads = db_path.parent / "uploads"
        assert len(list(uploads.iterdir())) == 16

        client = _client(db_path)
        r = client.post(f"/sessions/{sid}/delete", follow_redirects=False)
        assert r.status_code == 303

        engine = make_engine(db_path)
        with get_session(engine) as session:
            remaining = list(session.exec(
                select(ArenaMatch).where(ArenaMatch.session_id == sid)
            ).all())
        assert len(remaining) == 0
        assert len(list(uploads.iterdir())) == 0, (
            f"orphaned upload files: {list(uploads.iterdir())}"
        )


def test_bulk_discard_requires_confirm_yes():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "t.sqlite3"
        sid = "delete-test-bulk"
        _seed_session(db_path, sid)
        client = _client(db_path)
        # No confirm → 400
        r = client.post(
            "/captures/discard-needs-review",
            data={},
            follow_redirects=False,
        )
        assert r.status_code == 400


def test_bulk_discard_clears_only_needs_review_rows():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "t.sqlite3"
        sid = "delete-test-bulk2"
        _seed_session(db_path, sid)
        engine = make_engine(db_path)
        with get_session(engine) as session:
            n_review_before = sum(
                1 for r in session.exec(select(ArenaMatch)).all()
                if r.needs_review
            )
            n_total_before = len(list(session.exec(select(ArenaMatch)).all()))
        assert n_review_before > 0

        client = _client(db_path)
        r = client.post(
            "/captures/discard-needs-review",
            data={"confirm": "yes"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        with get_session(engine) as session:
            after = list(session.exec(select(ArenaMatch)).all())
        assert all(not r.needs_review for r in after)
        assert len(after) == n_total_before - n_review_before


def test_safety_rail_refuses_to_delete_files_outside_uploads(tmp_path: Path):
    """The cleanup helper must NEVER touch a file outside <db_dir>/uploads/.
    Verifies the safety rail by giving a row a screenshot path under
    /tmp/ and confirming the file survives the row delete."""
    db_path = tmp_path / "t.sqlite3"
    engine = make_engine(db_path)
    init_db(engine)
    safe_file = tmp_path / "external.png"
    safe_file.write_bytes(b"\x89PNG safe")
    with get_session(engine) as session:
        row = ArenaMatch(
            mode="champion",
            session_id="external-test",
            pre_battle_screenshot=str(safe_file),
        )
        session.add(row)
        session.commit()
        rid = row.id
    client = _client(db_path)
    r = client.post(f"/captures/{rid}/delete", follow_redirects=False)
    assert r.status_code == 303
    # Row gone, but the external file MUST survive.
    assert safe_file.exists(), "external file deleted — safety rail broken"
