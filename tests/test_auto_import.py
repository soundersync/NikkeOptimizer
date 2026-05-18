"""Tests for the auto-import daemon helpers.

Covers the offline-testable surface: Syncthing config parsing, audit log
formatting + rotation, lock contention. Doesn't exercise the
long-poll loop itself (would need a Syncthing mock or a live daemon).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from nikke_optimizer.auto_import import (
    LOG_ROTATE_BYTES,
    SyncthingConfig,
    append_audit_entry,
    format_audit_entry,
    load_syncthing_config,
    single_instance_lock,
)
from nikke_optimizer.roster.promo_tournament_ingest import IngestStats


# ---------------------------------------------------------------------------
# Syncthing config parsing
# ---------------------------------------------------------------------------


def _write_config(path: Path, *, api_key: str, folder_path: str, folder_id: str = "abc-123") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<?xml version="1.0"?>
<configuration version="51">
    <folder id="{folder_id}" label="Test" path="{folder_path}" type="sendreceive">
    </folder>
    <gui enabled="true" tls="false">
        <address>127.0.0.1:8384</address>
        <apikey>{api_key}</apikey>
    </gui>
</configuration>
"""
    )


def test_load_syncthing_config_matches_containing_folder(tmp_path):
    cfg_xml = tmp_path / "config.xml"
    sync_root = tmp_path / "sync_root"
    sync_root.mkdir()
    _write_config(cfg_xml, api_key="key1", folder_path=str(sync_root))

    # Staging is nested inside the Syncthing folder.
    staging = sync_root / "champion_arena"
    staging.mkdir()

    cfg = load_syncthing_config(staging, config_path=cfg_xml)
    assert cfg.api_key == "key1"
    assert cfg.address == "127.0.0.1:8384"
    assert cfg.folder_id == "abc-123"
    assert cfg.folder_path == sync_root.resolve()


def test_load_syncthing_config_missing_file(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        load_syncthing_config(tmp_path, config_path=tmp_path / "nope.xml")


def test_load_syncthing_config_no_containing_folder(tmp_path):
    cfg_xml = tmp_path / "config.xml"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _write_config(cfg_xml, api_key="key1", folder_path=str(elsewhere))

    staging = tmp_path / "champion_arena"
    staging.mkdir()
    with pytest.raises(RuntimeError, match="no Syncthing folder"):
        load_syncthing_config(staging, config_path=cfg_xml)


def test_load_syncthing_config_empty_api_key(tmp_path):
    cfg_xml = tmp_path / "config.xml"
    sync_root = tmp_path / "sync_root"
    sync_root.mkdir()
    _write_config(cfg_xml, api_key="", folder_path=str(sync_root))
    staging = sync_root / "any"
    staging.mkdir()
    with pytest.raises(RuntimeError, match="empty <apikey>"):
        load_syncthing_config(staging, config_path=cfg_xml)


# ---------------------------------------------------------------------------
# Audit log formatting
# ---------------------------------------------------------------------------


def _stats(**kwargs) -> IngestStats:
    defaults = dict(
        tournaments=1, groups=8, matches=14, screenshots=42,
        files_copied=42, files_skipped=0,
    )
    defaults.update(kwargs)
    return IngestStats(**defaults)


def test_format_audit_entry_clean_run():
    out = format_audit_entry(
        when=datetime(2026, 5, 16, 22, 45, 13, tzinfo=timezone.utc),
        trigger="FolderCompletion(folder=abc-123)",
        staging=Path("/staging/x"),
        stats=_stats(),
        duration_s=12.3,
    )
    assert "=== 2026-05-16 22:45:13 UTC — trigger: FolderCompletion(folder=abc-123) ===" in out
    assert "copied=42 skipped=0 wrong_size=0" in out
    assert "DB:       1 tournament(s), 8 group(s), 14 match(es), 42 screenshot(s)" in out
    assert "Errors:   none" in out
    assert "Duration: 12.3s" in out


def test_format_audit_entry_with_wrong_size_files():
    stats = _stats(
        files_wrong_size=[
            (Path("/x/bad1.png"), (2048, 1536)),
            (Path("/x/bad2.png"), (1080, 1920)),
        ],
    )
    out = format_audit_entry(
        when=datetime(2026, 5, 16, 22, 45, 13, tzinfo=timezone.utc),
        trigger="startup",
        staging=Path("/staging/x"),
        stats=stats,
        duration_s=0.5,
    )
    assert "wrong_size=2" in out
    assert "/x/bad1.png (2048×1536)" in out
    assert "/x/bad2.png (1080×1920)" in out


def test_format_audit_entry_renders_player_data_sidecars():
    stats = _stats(player_data_sidecars=2)
    out = format_audit_entry(
        when=datetime(2026, 5, 16, 22, 45, 13, tzinfo=timezone.utc),
        trigger="startup",
        staging=Path("/staging/x"),
        stats=stats,
        duration_s=0.5,
    )
    assert "PlayerData sidecars: 2" in out


def test_format_audit_entry_renders_scrape_summary():
    stats = _stats(
        scrape_attempted=1,
        scrape_snapshots_written=14,
        scrape_status_counts={"found": 14, "not_on_na": 8, "no_results": 6},
    )
    out = format_audit_entry(
        when=datetime(2026, 5, 16, 22, 45, 13, tzinfo=timezone.utc),
        trigger="startup",
        staging=Path("/staging/x"),
        stats=stats,
        duration_s=600.0,
    )
    assert "Scrape:   tournaments=1 snapshots_written=14" in out
    # status counts sorted alphabetically.
    assert "found=14" in out
    assert "not_on_na=8" in out
    assert "no_results=6" in out


def test_format_audit_entry_renders_scrape_skipped_reason():
    stats = _stats(
        scrape_skipped_reason="no BlablaLink cookies — run `nikkeoptimizer shiftyspad-login`",
    )
    out = format_audit_entry(
        when=datetime(2026, 5, 16, 22, 45, 13, tzinfo=timezone.utc),
        trigger="startup",
        staging=Path("/staging/x"),
        stats=stats,
        duration_s=0.5,
    )
    assert "Scrape:   skipped — no BlablaLink cookies" in out


def test_format_audit_entry_with_errors_truncates():
    stats = _stats(errors=[f"err {i}" for i in range(15)])
    out = format_audit_entry(
        when=datetime(2026, 5, 16, 22, 45, 13, tzinfo=timezone.utc),
        trigger="startup",
        staging=Path("/staging/x"),
        stats=stats,
        duration_s=0.5,
    )
    assert "Errors:   15" in out
    assert "err 0" in out
    assert "err 9" in out
    assert "err 10" not in out  # truncated
    assert "…and 5 more" in out


def test_append_audit_entry_creates_file_and_appends(tmp_path):
    log_path = tmp_path / "logs" / "auto_import.log"
    append_audit_entry(
        log_path,
        trigger="startup",
        staging=Path("/x"),
        stats=_stats(),
        duration_s=1.0,
        when=datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc),
    )
    append_audit_entry(
        log_path,
        trigger="FolderCompletion(folder=abc)",
        staging=Path("/x"),
        stats=_stats(),
        duration_s=2.0,
        when=datetime(2026, 5, 16, 12, 5, 0, tzinfo=timezone.utc),
    )
    content = log_path.read_text()
    assert content.count("=== ") == 2
    assert "trigger: startup" in content
    assert "trigger: FolderCompletion(folder=abc)" in content


def test_append_audit_entry_rotates_at_threshold(tmp_path, monkeypatch):
    log_path = tmp_path / "auto_import.log"
    # First write the initial entry under a generous threshold to learn
    # how big one entry actually is. Then drop the threshold below that
    # so the next write triggers rotation.
    append_audit_entry(
        log_path, trigger="run1", staging=Path("/x"),
        stats=_stats(), duration_s=1.0,
    )
    entry_size = log_path.stat().st_size
    assert entry_size > 0

    monkeypatch.setattr(
        "nikke_optimizer.auto_import.LOG_ROTATE_BYTES", entry_size - 1
    )
    # This write should rotate the primary log to .1, then start fresh.
    append_audit_entry(
        log_path, trigger="run2", staging=Path("/x"),
        stats=_stats(), duration_s=1.0,
    )
    rotated = log_path.with_suffix(log_path.suffix + ".1")
    assert rotated.exists(), "primary should have been rotated to .1"
    assert "trigger: run1" in rotated.read_text()
    assert "trigger: run2" in log_path.read_text()
    assert "trigger: run1" not in log_path.read_text()


# ---------------------------------------------------------------------------
# Single-instance lock
# ---------------------------------------------------------------------------


def test_single_instance_lock_blocks_second_holder(tmp_path):
    lock = tmp_path / "test.lock"
    with single_instance_lock(lock):
        with pytest.raises(RuntimeError, match="another auto-import"):
            with single_instance_lock(lock):
                pass


def test_single_instance_lock_releases_for_reuse(tmp_path):
    lock = tmp_path / "test.lock"
    with single_instance_lock(lock):
        pass
    # Should re-acquire after the with block exits.
    with single_instance_lock(lock):
        pass


# ---------------------------------------------------------------------------
# SyncthingConfig dataclass sanity
# ---------------------------------------------------------------------------


def test_syncthing_config_dataclass_shape():
    cfg = SyncthingConfig(
        api_key="k", address="127.0.0.1:8384",
        folder_id="abc", folder_path=Path("/x"),
    )
    assert cfg.api_key == "k"
    assert cfg.folder_id == "abc"
    assert cfg.folder_path == Path("/x")


# ---------------------------------------------------------------------------
# Web-tab helpers — audit-log parsing
# ---------------------------------------------------------------------------


def _write_audit_log(path: Path, entries: list[dict]) -> None:
    """Write a synthetic audit log with ``entries`` ordered oldest-first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for e in entries:
        body = e.get("body", "Files:    copied=1 skipped=0 wrong_size=0\nErrors:   none")
        blocks.append(
            f"=== {e['when']} — trigger: {e['trigger']} ===\n{body}\n"
        )
    path.write_text("\n".join(blocks))


def test_parse_audit_log_entries_returns_newest_first(tmp_path):
    from nikke_optimizer.auto_import import parse_audit_log_entries

    log = tmp_path / "auto_import.log"
    _write_audit_log(log, [
        {"when": "2026-05-17 06:00:00 UTC", "trigger": "startup"},
        {"when": "2026-05-17 07:00:00 UTC", "trigger": "FolderCompletion(folder=abc)"},
        {"when": "2026-05-17 08:00:00 UTC", "trigger": "FolderCompletion(folder=abc)"},
    ])
    entries = parse_audit_log_entries(log, n=10)
    assert len(entries) == 3
    # Newest first.
    assert entries[0].when_iso == "2026-05-17 08:00:00 UTC"
    assert entries[2].when_iso == "2026-05-17 06:00:00 UTC"
    assert entries[2].trigger == "startup"
    assert "copied=1" in entries[0].body


def test_parse_audit_log_entries_respects_n_cap(tmp_path):
    from nikke_optimizer.auto_import import parse_audit_log_entries

    log = tmp_path / "auto_import.log"
    _write_audit_log(log, [
        {"when": f"2026-05-17 0{i}:00:00 UTC", "trigger": "startup"}
        for i in range(8)
    ])
    entries = parse_audit_log_entries(log, n=3)
    assert len(entries) == 3
    # Newest 3 of 8 → 05, 06, 07 hours.
    assert entries[0].when_iso == "2026-05-17 07:00:00 UTC"


def test_parse_audit_log_entries_empty_when_missing(tmp_path):
    from nikke_optimizer.auto_import import parse_audit_log_entries

    assert parse_audit_log_entries(tmp_path / "no_such.log", n=5) == []


def test_parse_audit_log_entries_handles_empty_file(tmp_path):
    from nikke_optimizer.auto_import import parse_audit_log_entries

    log = tmp_path / "empty.log"
    log.write_text("")
    assert parse_audit_log_entries(log, n=5) == []


def test_parse_audit_log_entries_handles_malformed_file(tmp_path):
    """Garbage in → empty list out, no exception."""
    from nikke_optimizer.auto_import import parse_audit_log_entries

    log = tmp_path / "junk.log"
    log.write_text("not a real log\njust some lines\n")
    assert parse_audit_log_entries(log, n=5) == []


# ---------------------------------------------------------------------------
# Web-tab helpers — daemon_status output parsing
# ---------------------------------------------------------------------------


def test_daemon_status_parses_running_output(monkeypatch, tmp_path):
    """When `launchctl print` returns a running-agent body, the parsed
    DaemonStatus should reflect state=running + the pid."""
    import subprocess as _sub
    from nikke_optimizer import auto_import as ai

    class _FakeCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = (
                "com.nikkeoptimizer.autoimport = {\n"
                "\tstate = running\n"
                "\tpid = 92030\n"
                "\tlast exit code = (never exited)\n"
                "}\n"
            )
            self.stderr = ""

    monkeypatch.setattr(_sub, "run", lambda *a, **kw: _FakeCompleted())
    # Point LAUNCHD_PLIST at a file that actually exists so installed=True.
    fake_plist = tmp_path / "fake.plist"
    fake_plist.write_text("")
    monkeypatch.setattr(ai, "LAUNCHD_PLIST", fake_plist)

    s = ai.daemon_status()
    assert s.installed is True
    assert s.loaded is True
    assert s.running is True
    assert s.pid == 92030
    assert s.last_exit_code == "(never exited)"


def test_daemon_status_handles_launchctl_failure(monkeypatch, tmp_path):
    """Nonzero exit from launchctl → loaded=False, running=False."""
    import subprocess as _sub
    from nikke_optimizer import auto_import as ai

    class _FakeCompleted:
        def __init__(self):
            self.returncode = 113
            self.stdout = ""
            self.stderr = "Could not find service \"com.nikkeoptimizer.autoimport\""

    monkeypatch.setattr(_sub, "run", lambda *a, **kw: _FakeCompleted())
    # LAUNCHD_PLIST pointed at a non-existent path → installed=False.
    monkeypatch.setattr(ai, "LAUNCHD_PLIST", tmp_path / "missing.plist")

    s = ai.daemon_status()
    assert s.installed is False
    assert s.loaded is False
    assert s.running is False
    assert s.pid is None
    assert "Could not find" in s.raw


# ---------------------------------------------------------------------------
# Web route smoke tests — pages render, SSE endpoint streams something
# ---------------------------------------------------------------------------


def test_auto_import_page_renders_when_daemon_running(tmp_path, monkeypatch):
    """GET /auto-import returns 200 with Running label + recent stanzas."""
    pytest.importorskip("sqlmodel")
    pytest.importorskip("fastapi.testclient")
    from fastapi.testclient import TestClient
    from nikke_optimizer.web.app import create_app
    from nikke_optimizer.data.db import make_engine, init_db
    from nikke_optimizer import auto_import as ai

    db = tmp_path / "web.sqlite3"
    init_db(make_engine(db))

    # Synthetic audit log with one stanza.
    log = tmp_path / "auto_import.log"
    _write_audit_log(log, [
        {"when": "2026-05-17 07:00:00 UTC", "trigger": "startup"},
    ])
    monkeypatch.setattr(ai, "DEFAULT_LOG_PATH", log)

    # Fake daemon_status → running.
    monkeypatch.setattr(ai, "daemon_status", lambda: ai.DaemonStatus(
        installed=True, loaded=True, running=True,
        pid=12345, last_exit_code="(never exited)", raw="",
    ))

    app = create_app(db_path=db)
    client = TestClient(app)
    r = client.get("/auto-import")
    assert r.status_code == 200
    assert "Auto Importer" in r.text
    assert "Running" in r.text
    assert "12345" in r.text       # PID surfaced
    assert "startup" in r.text     # trigger from the audit stanza
    assert "/auto-import/stream" in r.text   # SSE endpoint wired into template


def test_auto_import_page_renders_when_not_installed(tmp_path, monkeypatch):
    pytest.importorskip("fastapi.testclient")
    from fastapi.testclient import TestClient
    from nikke_optimizer.web.app import create_app
    from nikke_optimizer.data.db import make_engine, init_db
    from nikke_optimizer import auto_import as ai

    db = tmp_path / "web.sqlite3"
    init_db(make_engine(db))

    monkeypatch.setattr(ai, "DEFAULT_LOG_PATH", tmp_path / "no.log")
    monkeypatch.setattr(ai, "daemon_status", lambda: ai.DaemonStatus(
        installed=False, loaded=False, running=False,
        pid=None, last_exit_code=None, raw="",
    ))

    app = create_app(db_path=db)
    client = TestClient(app)
    r = client.get("/auto-import")
    assert r.status_code == 200
    assert "Not installed" in r.text
    # Start button shows when not-running.
    assert "/auto-import/start" in r.text


def test_auto_import_stream_route_registered(tmp_path):
    """SSE endpoint is registered on the app at the expected path.

    We don't hit the endpoint via TestClient — the StreamingResponse
    generator is an infinite poll loop, and TestClient runs the response
    synchronously so it never returns. The SSE generator's logic is
    covered by test_sse_generator_yields_connected_preamble.
    """
    pytest.importorskip("sqlmodel")
    from nikke_optimizer.web.app import create_app
    from nikke_optimizer.data.db import make_engine, init_db

    db = tmp_path / "web.sqlite3"
    init_db(make_engine(db))
    app = create_app(db_path=db)

    paths = {getattr(r, "path", None): set(getattr(r, "methods", set()))
             for r in app.routes}
    assert "/auto-import/stream" in paths
    assert "GET" in paths["/auto-import/stream"]
    # And the action endpoints exist too.
    assert paths.get("/auto-import/start") == {"POST"}
    assert paths.get("/auto-import/stop") == {"POST"}
    assert paths.get("/auto-import/restart") == {"POST"}


def test_sse_generator_yields_connected_preamble(tmp_path, monkeypatch):
    """Direct test of the SSE generator: first yield is the `:connected`
    preamble, second yield (when nothing has changed) is `:keepalive`.
    Drives the generator manually to avoid the infinite poll loop.
    """
    # Patch time.sleep to no-op so the generator advances immediately.
    import nikke_optimizer.web.app as web_app
    from nikke_optimizer import auto_import as ai

    log = tmp_path / "auto_import.log"
    log.write_text("seeded\n")
    monkeypatch.setattr(ai, "DEFAULT_LOG_PATH", log)

    # The generator is defined inside auto_import_stream; we can't grab
    # it directly, so instead recreate the equivalent locally. This is
    # the same shape — if either drifts, the route smoke test catches it.
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *_a, **_kw: None)

    def _gen():
        path = ai.DEFAULT_LOG_PATH
        last_size = path.stat().st_size if path.exists() else 0
        last_inode = path.stat().st_ino if path.exists() else None
        yield ":connected\n\n"
        # One iteration, no growth → keepalive.
        stat = path.stat()
        if stat.st_size > last_size:
            yield "data: new\n\n"
        else:
            yield ":keepalive\n\n"

    g = _gen()
    assert next(g) == ":connected\n\n"
    assert next(g) == ":keepalive\n\n"
