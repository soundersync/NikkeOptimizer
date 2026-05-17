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
