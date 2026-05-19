"""Auto-import daemon: subscribes to Syncthing's event API and runs
``ingest_root()`` when the watched folder reports completion.

Run via ``nikkeoptimizer auto-import``. Designed for launchd
(``KeepAlive=true``). Single-instance enforced by ``flock``.

Audit log lands at ``<repo>/logs/auto_import.log`` — one human-readable
stanza per run, rotated at 5MB.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .roster.promo_tournament_ingest import IngestStats, ingest_root

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STAGING = _REPO_ROOT / "incoming-captures" / "champion_arena"
DEFAULT_ROOKIE_STAGING = _REPO_ROOT / "incoming-captures" / "rookie_arena"
DEFAULT_LOG_PATH = _REPO_ROOT / "logs" / "auto_import.log"
DEFAULT_LOCK_PATH = Path("/tmp/nikke-autoimport.lock")
SYNCTHING_CONFIG = Path.home() / "Library/Application Support/Syncthing/config.xml"
STATE_DIR = Path.home() / "Library/Application Support/NikkeOptimizer/state"
LAST_EVENT_FILE = STATE_DIR / "syncthing_last_event_id.txt"

LOG_ROTATE_BYTES = 5 * 1024 * 1024  # 5 MB
DEBOUNCE_SECONDS = 5
POLL_TIMEOUT_S = 60  # long-poll window held open by Syncthing

# Per-tournament soft watchdog for the player_data scrape pass.
# Mid-run snapshot writes persist to the status sidecar after each
# player, so a watchdog abort still makes forward progress.
DEFAULT_MAX_SCRAPE_MINUTES = 90.0


# ---------------------------------------------------------------------------
# Syncthing config parsing
# ---------------------------------------------------------------------------


@dataclass
class SyncthingConfig:
    api_key: str
    address: str           # "127.0.0.1:8384"
    folder_id: str         # the folder ID whose path contains our staging dir
    folder_path: Path
    folder_label: str      # human-readable label from config.xml; falls
                           # back to folder_id when the user hasn't set one


def load_syncthing_config(
    staging: Path, *, config_path: Path = SYNCTHING_CONFIG
) -> SyncthingConfig:
    """Parse Syncthing's config.xml and find the folder containing
    ``staging``.

    Picks the longest-matching folder path (handles nested Syncthing
    folders, though we don't actually have any).
    """
    if not config_path.exists():
        raise RuntimeError(f"Syncthing config not found at {config_path}")
    tree = ET.parse(config_path)
    root = tree.getroot()
    gui = root.find("gui")
    if gui is None:
        raise RuntimeError(f"no <gui> element in {config_path}")
    api_key_el = gui.find("apikey")
    address_el = gui.find("address")
    if api_key_el is None or address_el is None:
        raise RuntimeError(f"missing <apikey> or <address> in {config_path}")
    api_key = (api_key_el.text or "").strip()
    address = (address_el.text or "").strip()
    if not api_key:
        raise RuntimeError(f"empty <apikey> in {config_path}")

    staging_resolved = staging.resolve()
    best: Optional[tuple[str, Path, str]] = None  # (id, path, label)
    for folder in root.findall("folder"):
        fid = folder.get("id")
        fpath = folder.get("path")
        flabel = (folder.get("label") or "").strip()
        if not fid or not fpath:
            continue
        folder_path = Path(fpath).resolve()
        try:
            staging_resolved.relative_to(folder_path)
        except ValueError:
            continue
        if best is None or len(str(folder_path)) > len(str(best[1])):
            best = (fid, folder_path, flabel)
    if best is None:
        raise RuntimeError(
            f"no Syncthing folder contains staging path {staging_resolved}"
        )
    return SyncthingConfig(
        api_key=api_key,
        address=address,
        folder_id=best[0],
        folder_path=best[1],
        folder_label=best[2] or best[0],
    )


# ---------------------------------------------------------------------------
# Event subscription
# ---------------------------------------------------------------------------


def _http_get(url: str, *, api_key: str, timeout: float) -> list[dict]:
    req = urllib.request.Request(url, headers={"X-API-Key": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else []


def _load_last_event_id() -> int:
    if not LAST_EVENT_FILE.exists():
        return 0
    try:
        return int(LAST_EVENT_FILE.read_text().strip())
    except ValueError:
        return 0


def _save_last_event_id(event_id: int) -> None:
    LAST_EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_EVENT_FILE.write_text(str(event_id))


def poll_for_completion(
    config: SyncthingConfig,
    *,
    since: int,
    timeout_s: int = POLL_TIMEOUT_S,
) -> tuple[list[dict], int]:
    """Long-poll Syncthing for ``FolderCompletion`` events.

    Returns ``(matching_events, max_seen_id)``. ``matching_events`` is
    filtered to events for ``config.folder_id`` with ``completion ==
    100``. ``max_seen_id`` is the highest event id returned by Syncthing
    (used to advance ``since`` on the next poll).
    """
    url = (
        f"http://{config.address}/rest/events"
        f"?events=FolderCompletion"
        f"&since={since}"
        f"&timeout={timeout_s}"
    )
    events = _http_get(url, api_key=config.api_key, timeout=timeout_s + 15)
    matching = [
        e for e in events
        if e.get("data", {}).get("folder") == config.folder_id
        and e.get("data", {}).get("completion") == 100
    ]
    max_id = max((e.get("id", 0) for e in events), default=since)
    return matching, max_id


def get_current_event_id(config: SyncthingConfig) -> int:
    """Return the latest FolderCompletion event id without blocking.

    Used at startup to skip the buffered backlog — the startup-ingest
    pass already covers anything that happened while the daemon was
    down.

    **Why FolderCompletion-specific, not global**: Syncthing's event
    ids are monotonic across ALL event types. Querying `since=0`
    without a type filter returns the highest global id — but the
    daemon polls *only* for FolderCompletion events, which can lag
    the global counter by 10,000+ ids when other event types fire
    rapidly (LocalIndexUpdated, RemoteDownloadProgress, ItemStarted).

    Observed 2026-05-17: global max was 13785, latest FolderCompletion
    was id 119. Daemon stored 13785, polled `events=FolderCompletion
    &since=13785`, and never saw the existing id-119 event — the
    rookie-run sync that emitted it sat unprocessed until the user
    kickstart-ed the daemon.

    Anchoring to FolderCompletion-specific ids fixes this: we know
    the next FolderCompletion event will get an id > whatever our
    type-filtered max is right now, so the `since=` filter always
    catches it whenever Syncthing fires it.
    """
    url = (
        f"http://{config.address}/rest/events"
        f"?events=FolderCompletion&since=0&timeout=1"
    )
    events = _http_get(url, api_key=config.api_key, timeout=10)
    return max((e.get("id", 0) for e in events), default=0)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _rotate_log_if_needed(log_path: Path) -> None:
    if not log_path.exists() or log_path.stat().st_size < LOG_ROTATE_BYTES:
        return
    rotated = log_path.with_suffix(log_path.suffix + ".1")
    if rotated.exists():
        rotated.unlink()
    log_path.rename(rotated)


def format_audit_entry(
    *,
    when: datetime,
    trigger: str,
    staging: Path,
    stats: IngestStats,
    duration_s: float,
) -> str:
    ts = when.strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"=== {ts} — trigger: {trigger} ===",
        f"Staging:  {staging}",
        f"Tournaments processed: {stats.tournaments}",
    ]
    if stats.tournament_folders:
        lines.append("Folders:  " + ", ".join(stats.tournament_folders))
    lines.extend([
        (
            f"DB:       {stats.tournaments} tournament(s), "
            f"{stats.groups} group(s), {stats.matches} match(es), "
            f"{stats.screenshots} screenshot(s)"
        ),
        (
            f"Files:    copied={stats.files_copied} "
            f"skipped={stats.files_skipped} "
            f"wrong_size={len(stats.files_wrong_size)}"
        ),
    ])
    if stats.files_wrong_size:
        lines.append("Wrong-dim PNGs (left in staging, not copied):")
        for path, size in stats.files_wrong_size[:20]:
            lines.append(f"  · {path} ({size[0]}×{size[1]})")
        if len(stats.files_wrong_size) > 20:
            lines.append(f"  · …and {len(stats.files_wrong_size) - 20} more")
    if stats.ocr_screenshots or stats.ocr_skipped:
        lines.append(
            f"OCR:      processed={stats.ocr_screenshots} "
            f"fields={stats.ocr_fields} cached={stats.ocr_skipped}"
        )
    if stats.player_data_sidecars:
        lines.append(
            f"PlayerData sidecars: {stats.player_data_sidecars}"
        )
    if stats.scrape_attempted:
        counts = "  ".join(
            f"{k}={v}" for k, v in sorted(stats.scrape_status_counts.items())
        )
        lines.append(
            f"Scrape:   tournaments={stats.scrape_attempted} "
            f"snapshots_written={stats.scrape_snapshots_written}"
            + (f"  ({counts})" if counts else "")
        )
    elif stats.scrape_skipped_reason:
        lines.append(f"Scrape:   skipped — {stats.scrape_skipped_reason}")
    if stats.self_refresh_attempted:
        lines.append(
            f"SelfRfsh: tournaments={stats.self_refresh_attempted} "
            f"chars_updated={stats.self_refresh_chars_updated}"
        )
    elif stats.self_refresh_skipped_reason:
        lines.append(f"SelfRfsh: skipped — {stats.self_refresh_skipped_reason}")
    if stats.errors:
        lines.append(f"Errors:   {len(stats.errors)}")
        for err in stats.errors[:10]:
            lines.append(f"  · {err}")
        if len(stats.errors) > 10:
            lines.append(f"  · …and {len(stats.errors) - 10} more")
    else:
        lines.append("Errors:   none")
    lines.append(f"Duration: {duration_s:.1f}s")
    lines.append("")  # trailing blank line between entries
    return "\n".join(lines) + "\n"


def append_audit_entry(
    log_path: Path,
    *,
    trigger: str,
    staging: Path,
    stats: IngestStats,
    duration_s: float,
    when: Optional[datetime] = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log_if_needed(log_path)
    entry = format_audit_entry(
        when=when or datetime.now(timezone.utc),
        trigger=trigger,
        staging=staging,
        stats=stats,
        duration_s=duration_s,
    )
    with log_path.open("a") as fp:
        fp.write(entry)


# ---------------------------------------------------------------------------
# Lock + ingest wrapper
# ---------------------------------------------------------------------------


@contextmanager
def single_instance_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive flock or raise RuntimeError."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fp = open(lock_path, "w")
    try:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"another auto-import process holds {lock_path}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
    finally:
        fp.close()


def _blablalink_cookies_present() -> bool:
    """Probe whether the persistent Playwright profile has a Cookies db.

    Used by the daemon to opt into the player_data scrape pass only
    when the user has run ``shiftyspad-login`` at least once. Doesn't
    validate cookie freshness — expired cookies surface as per-player
    "No Search Results" in the scrape, which lands in the audit stanza.
    """
    from .data.scrapers.blablalink import default_browser_profile_dir
    return (default_browser_profile_dir() / "Default" / "Cookies").is_file()


def _merge_stats(into: IngestStats, other: IngestStats) -> None:
    """Sum the counters of ``other`` into ``into`` so a single audit
    stanza can cover ingests across multiple staging roots (champion +
    rookie). String fields and lists are concatenated; status_counts
    dicts are key-merged with addition.
    """
    into.tournaments += other.tournaments
    into.groups += other.groups
    into.matches += other.matches
    into.screenshots += other.screenshots
    into.tournament_folders.extend(other.tournament_folders)
    into.files_copied += other.files_copied
    into.files_skipped += other.files_skipped
    into.files_moved_deleted += other.files_moved_deleted
    into.files_wrong_size.extend(other.files_wrong_size)
    into.ocr_screenshots += other.ocr_screenshots
    into.ocr_fields += other.ocr_fields
    into.ocr_skipped += other.ocr_skipped
    into.player_data_sidecars += other.player_data_sidecars
    into.scrape_attempted += other.scrape_attempted
    into.scrape_snapshots_written += other.scrape_snapshots_written
    for k, v in other.scrape_status_counts.items():
        into.scrape_status_counts[k] = into.scrape_status_counts.get(k, 0) + v
    if other.scrape_skipped_reason and not into.scrape_skipped_reason:
        into.scrape_skipped_reason = other.scrape_skipped_reason
    into.self_refresh_attempted += other.self_refresh_attempted
    into.self_refresh_chars_updated += other.self_refresh_chars_updated
    if other.self_refresh_skipped_reason and not into.self_refresh_skipped_reason:
        into.self_refresh_skipped_reason = other.self_refresh_skipped_reason
    into.errors.extend(other.errors)


def run_ingest_and_log(
    staging: Path,
    *,
    trigger: str,
    log_path: Path,
    rookie_staging: Path = DEFAULT_ROOKIE_STAGING,
    max_scrape_minutes: float = DEFAULT_MAX_SCRAPE_MINUTES,
) -> IngestStats:
    """Run BOTH champion + rookie ingest passes and append a combined
    audit entry.

    Errors during either ingest are caught and logged to the audit file
    so a failure doesn't kill the daemon.

    The daemon opts into both BlablaLink scrape passes (player_data +
    rookie opponents) when BlablaLink cookies are present in the
    persistent Playwright profile. When absent, both scrapes are
    skipped and the audit stanza calls out the missing login.
    """
    from .roster.rookie_arena_ingest import ingest_rookie_root

    t0 = time.time()
    cookies_ok = _blablalink_cookies_present()
    stats = IngestStats()
    # Champion-family pass (promotion_tournament / champions_duel /
    # league / promotion_tournament_player_data).
    try:
        champion_stats = ingest_root(
            staging_root=staging,
            move=False,
            scrape_player_data=cookies_ok,
            max_scrape_minutes=max_scrape_minutes,
        )
        _merge_stats(stats, champion_stats)
    except Exception as exc:  # noqa: BLE001
        log.exception("ingest_root raised: %s", exc)
        stats.errors.append(f"ingest_root raised: {exc!r}")

    # Rookie-arena pass (incoming-captures/rookie_arena/<date_TS>/).
    if rookie_staging.is_dir():
        try:
            rookie_stats = ingest_rookie_root(
                staging_root=rookie_staging,
                move=False,
                scrape_rookie_opponents=cookies_ok,
                refresh_self_from_loadouts=cookies_ok,
                max_scrape_minutes=max_scrape_minutes,
            )
            _merge_stats(stats, rookie_stats)
        except Exception as exc:  # noqa: BLE001
            log.exception("ingest_rookie_root raised: %s", exc)
            stats.errors.append(f"ingest_rookie_root raised: {exc!r}")

    if not cookies_ok:
        stats.scrape_skipped_reason = (
            "no BlablaLink cookies — run `nikkeoptimizer shiftyspad-login`"
        )

    duration = time.time() - t0
    append_audit_entry(
        log_path,
        trigger=trigger,
        staging=staging,
        stats=stats,
        duration_s=duration,
    )
    log.info(
        "ingest done: %s (%.1fs) — audit: %s", stats, duration, log_path
    )
    return stats


# ---------------------------------------------------------------------------
# Daemon entry point
# ---------------------------------------------------------------------------


def run_daemon(
    *,
    staging: Path = DEFAULT_STAGING,
    log_path: Path = DEFAULT_LOG_PATH,
    lock_path: Path = DEFAULT_LOCK_PATH,
    poll_timeout_s: int = POLL_TIMEOUT_S,
) -> int:
    """Main daemon loop. Returns process exit code (0 on clean exit).

    Loop shape:
      1. Acquire single-instance lock.
      2. Run one startup ingest (catches up anything synced while down).
      3. Learn current Syncthing event id (skip the buffered backlog).
      4. Long-poll for FolderCompletion events for our folder.
      5. On event: mark ``pending_since``; on quiet for ``DEBOUNCE_SECONDS``
         after that mark, run ingest + audit entry.
      6. GOTO 4.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    staging = staging.resolve()
    log.info("staging:    %s", staging)
    log.info("audit log:  %s", log_path)

    config = load_syncthing_config(staging)
    log.info(
        "syncthing:  folder_id=%s path=%s api=%s",
        config.folder_id, config.folder_path, config.address,
    )

    with single_instance_lock(lock_path):
        # 1. Startup ingest.
        run_ingest_and_log(
            staging, trigger="startup", log_path=log_path,
        )

        # 2. Skip the buffered event backlog so we don't re-fire on
        # completions that happened pre-startup.
        try:
            last_id = get_current_event_id(config)
        except (urllib.error.URLError, OSError) as exc:
            log.warning("couldn't read current event id (%s) — starting from 0", exc)
            last_id = _load_last_event_id()
        _save_last_event_id(last_id)
        log.info("starting event subscription from id=%d", last_id)

        pending_since: Optional[float] = None

        while True:
            try:
                matching, max_id = poll_for_completion(
                    config, since=last_id, timeout_s=poll_timeout_s,
                )
            except (urllib.error.URLError, OSError) as exc:
                log.warning("poll error: %s — sleeping 10s", exc)
                time.sleep(10)
                continue

            if max_id > last_id:
                last_id = max_id
                _save_last_event_id(last_id)

            if matching:
                pending_since = time.time()
                log.info(
                    "FolderCompletion(folder=%s): %d event(s), debouncing %ds",
                    config.folder_label, len(matching), DEBOUNCE_SECONDS,
                )

            if pending_since is not None:
                elapsed = time.time() - pending_since
                if elapsed >= DEBOUNCE_SECONDS:
                    run_ingest_and_log(
                        staging,
                        trigger=f"FolderCompletion(folder={config.folder_label})",
                        log_path=log_path,
                    )
                    pending_since = None
                else:
                    time.sleep(max(0.0, DEBOUNCE_SECONDS - elapsed))


# ---------------------------------------------------------------------------
# Web-tab helpers: daemon status, audit-log parsing, launchctl control
# ---------------------------------------------------------------------------


LAUNCHD_LABEL = "com.nikkeoptimizer.autoimport"
LAUNCHD_PLIST = Path.home() / "Library/LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


@dataclass
class DaemonStatus:
    """Snapshot of the launchd agent's current state."""
    installed: bool            # plist present under ~/Library/LaunchAgents
    loaded: bool               # launchctl knows about it
    running: bool              # state = running with a live pid
    pid: Optional[int]
    last_exit_code: Optional[str]   # raw text, e.g. "(never exited)" or "0"
    raw: str                   # full `launchctl print` body (or error text)


def daemon_status() -> DaemonStatus:
    """Query launchd for the current state of the auto-import agent.

    Never raises — returns ``installed=False/loaded=False/running=False``
    when launchctl errors. ``raw`` carries the underlying output for
    display in the UI.
    """
    installed = LAUNCHD_PLIST.exists()
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DaemonStatus(
            installed=installed, loaded=False, running=False,
            pid=None, last_exit_code=None, raw=f"launchctl error: {exc}",
        )

    if result.returncode != 0:
        return DaemonStatus(
            installed=installed, loaded=False, running=False,
            pid=None, last_exit_code=None,
            raw=result.stderr.strip() or result.stdout.strip(),
        )

    body = result.stdout
    # `launchctl print` output has `state = running` and `pid = 12345`
    # on their own indented lines. Parse defensively.
    state_match = re.search(r"^\s*state\s*=\s*(\S+)", body, re.MULTILINE)
    pid_match = re.search(r"^\s*pid\s*=\s*(\d+)", body, re.MULTILINE)
    exit_match = re.search(r"^\s*last exit code\s*=\s*(.+)$", body, re.MULTILINE)

    state = state_match.group(1) if state_match else ""
    pid = int(pid_match.group(1)) if pid_match else None
    return DaemonStatus(
        installed=installed,
        loaded=True,
        running=(state == "running" and pid is not None),
        pid=pid,
        last_exit_code=exit_match.group(1).strip() if exit_match else None,
        raw=body,
    )


@dataclass
class AuditEntry:
    """One parsed stanza from the audit log."""
    when_iso: str              # raw timestamp string from the header ("… UTC")
    when_local: str            # converted to system local time, e.g. "5:22 PM PDT"
    trigger: str               # "startup" / "FolderCompletion(folder=…)" / …
    body: str                  # full stanza minus the `=== … ===` header line


_AUDIT_HEADER_RE = re.compile(
    r"^=== (?P<when>.+?) — trigger: (?P<trigger>.+?) ===\s*$", re.MULTILINE,
)
_AUDIT_TS_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC$"
)


def _to_local(when_iso: str) -> str:
    """Convert an audit-stanza UTC timestamp ('YYYY-MM-DD HH:MM:SS UTC')
    to the system's local time. Falls back to the original string when
    parsing fails so the UI still renders something."""
    m = _AUDIT_TS_RE.match(when_iso.strip())
    if m is None:
        return when_iso
    try:
        dt = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return when_iso
    local = dt.astimezone()
    # "2026-05-18 5:22 PM PDT" — date + 12-hour clock + tz abbreviation.
    return local.strftime("%Y-%m-%d %-I:%M:%S %p %Z")


def parse_audit_log_entries(
    log_path: Path, *, n: int = 10,
) -> list[AuditEntry]:
    """Return the most recent ``n`` audit stanzas, newest first.

    Reads the whole file (the rotation cap keeps it ≤5MB). Returns an
    empty list when the file is missing or malformed.
    """
    if not log_path.is_file():
        return []
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return []

    headers = list(_AUDIT_HEADER_RE.finditer(text))
    entries: list[AuditEntry] = []
    for i, m in enumerate(headers):
        body_start = m.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        when_iso = m.group("when").strip()
        entries.append(AuditEntry(
            when_iso=when_iso,
            when_local=_to_local(when_iso),
            trigger=m.group("trigger").strip(),
            body=text[body_start:body_end].strip("\n"),
        ))
    # Newest last in the file → reverse for "newest first".
    entries.reverse()
    return entries[:n]


# ---------------------------------------------------------------------------
# launchctl control wrappers (thin — used by the web UI buttons)
# ---------------------------------------------------------------------------


@dataclass
class LaunchctlResult:
    ok: bool
    action: str                # "start" / "stop" / "restart"
    returncode: int
    stdout: str
    stderr: str


def _launchctl(args: list[str], action: str) -> LaunchctlResult:
    try:
        r = subprocess.run(
            ["launchctl", *args], capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return LaunchctlResult(
            ok=False, action=action, returncode=-1, stdout="", stderr=str(exc),
        )
    return LaunchctlResult(
        ok=(r.returncode == 0),
        action=action,
        returncode=r.returncode,
        stdout=r.stdout.strip(),
        stderr=r.stderr.strip(),
    )


def launchctl_start() -> LaunchctlResult:
    """Bootstrap the agent into launchd (idempotent — already-loaded
    returns nonzero with a benign message)."""
    if not LAUNCHD_PLIST.exists():
        return LaunchctlResult(
            ok=False, action="start", returncode=-1,
            stdout="",
            stderr=f"plist missing: {LAUNCHD_PLIST}. Install per scripts/launchd/README.md.",
        )
    return _launchctl(
        ["bootstrap", f"gui/{os.getuid()}", str(LAUNCHD_PLIST)], action="start",
    )


def launchctl_stop() -> LaunchctlResult:
    """Bootout the agent (sends SIGTERM to the current ingest)."""
    return _launchctl(
        ["bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], action="stop",
    )


def launchctl_restart() -> LaunchctlResult:
    """Kickstart -k: kill the current instance and start a fresh one."""
    return _launchctl(
        ["kickstart", "-k", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"],
        action="restart",
    )
