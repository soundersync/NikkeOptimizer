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
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
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
DEFAULT_LOG_PATH = _REPO_ROOT / "logs" / "auto_import.log"
DEFAULT_LOCK_PATH = Path("/tmp/nikke-autoimport.lock")
SYNCTHING_CONFIG = Path.home() / "Library/Application Support/Syncthing/config.xml"
STATE_DIR = Path.home() / "Library/Application Support/NikkeOptimizer/state"
LAST_EVENT_FILE = STATE_DIR / "syncthing_last_event_id.txt"

LOG_ROTATE_BYTES = 5 * 1024 * 1024  # 5 MB
DEBOUNCE_SECONDS = 5
POLL_TIMEOUT_S = 60  # long-poll window held open by Syncthing


# ---------------------------------------------------------------------------
# Syncthing config parsing
# ---------------------------------------------------------------------------


@dataclass
class SyncthingConfig:
    api_key: str
    address: str           # "127.0.0.1:8384"
    folder_id: str         # the folder ID whose path contains our staging dir
    folder_path: Path


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
    best: Optional[tuple[str, Path]] = None
    for folder in root.findall("folder"):
        fid = folder.get("id")
        fpath = folder.get("path")
        if not fid or not fpath:
            continue
        folder_path = Path(fpath).resolve()
        try:
            staging_resolved.relative_to(folder_path)
        except ValueError:
            continue
        if best is None or len(str(folder_path)) > len(str(best[1])):
            best = (fid, folder_path)
    if best is None:
        raise RuntimeError(
            f"no Syncthing folder contains staging path {staging_resolved}"
        )
    return SyncthingConfig(
        api_key=api_key,
        address=address,
        folder_id=best[0],
        folder_path=best[1],
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
    """Return the latest Syncthing event id without blocking.

    Used at startup to skip the buffered backlog — the startup-ingest
    pass already covers anything that happened while the daemon was
    down.
    """
    url = (
        f"http://{config.address}/rest/events"
        f"?since=0&timeout=1&limit=1"
    )
    events = _http_get(url, api_key=config.api_key, timeout=10)
    if not events:
        # Fall back: ask for the head of the buffer.
        url = f"http://{config.address}/rest/events?since=0&timeout=0"
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
    ]
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


def run_ingest_and_log(
    staging: Path,
    *,
    trigger: str,
    log_path: Path,
) -> IngestStats:
    """Run a single ingest pass and append an audit entry.

    Errors during ingest are caught and logged to the audit file so a
    failure doesn't kill the daemon.
    """
    t0 = time.time()
    try:
        stats = ingest_root(staging_root=staging, move=False)
    except Exception as exc:  # noqa: BLE001
        log.exception("ingest_root raised: %s", exc)
        stats = IngestStats()
        stats.errors.append(f"ingest_root raised: {exc!r}")
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
                    config.folder_id, len(matching), DEBOUNCE_SECONDS,
                )

            if pending_since is not None:
                elapsed = time.time() - pending_since
                if elapsed >= DEBOUNCE_SECONDS:
                    run_ingest_and_log(
                        staging,
                        trigger=f"FolderCompletion(folder={config.folder_id})",
                        log_path=log_path,
                    )
                    pending_since = None
                else:
                    time.sleep(max(0.0, DEBOUNCE_SECONDS - elapsed))
