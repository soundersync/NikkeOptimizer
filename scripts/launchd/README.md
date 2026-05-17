# Auto-import launchd agent

Installs `nikkeoptimizer auto-import` as a user-level launchd agent that:

- Starts at login (`RunAtLoad=true`)
- Auto-restarts if it crashes (`KeepAlive=true`, throttled to ≥30s)
- Subscribes to Syncthing's event API and runs `ingest-tournaments`
  whenever the `incoming-captures/` folder reports completion
- Writes a human-readable audit log at
  `<repo>/logs/auto_import.log` (rotated at 5MB → `.log.1`)
- Captures the launchd supervisor's stdout/stderr at
  `<repo>/logs/auto_import.{stdout,stderr}.log`

## Install / uninstall

```sh
# Install: copy the plist + bootstrap into launchd.
cp scripts/launchd/com.nikkeoptimizer.autoimport.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.nikkeoptimizer.autoimport.plist

# Uninstall: remove from launchd + delete plist.
launchctl bootout gui/$UID/com.nikkeoptimizer.autoimport
rm ~/Library/LaunchAgents/com.nikkeoptimizer.autoimport.plist
```

## Day-to-day operations

```sh
# Check it's running. Look for `state = running` and a recent pid.
launchctl print gui/$UID/com.nikkeoptimizer.autoimport | grep -E 'state|pid|last exit'

# Stop temporarily. Will auto-restart at next login unless you also
# rm the plist. Use kickstart (below) to bring it back without
# logging out.
launchctl bootout gui/$UID/com.nikkeoptimizer.autoimport

# Restart (after editing the plist, or to force a clean cycle).
launchctl kickstart -k gui/$UID/com.nikkeoptimizer.autoimport

# Manual foreground run (debugging — bypasses launchd, single-instance
# lock still applies so stop the daemon first).
nikkeoptimizer auto-import
```

## Watching what it does

The daemon writes one stanza per ingest run to the audit log:

```sh
tail -f logs/auto_import.log
```

Each stanza looks like:

```
=== 2026-05-17 00:14:33 UTC — trigger: FolderCompletion(folder=fvgg3-kq4jv) ===
Staging:  /Users/sleepingcounty/git-other/NikkeOptimizer/incoming-captures/champion_arena
Tournaments processed: 1
DB:       1 tournament(s), 7 group(s), 14 match(es), 42 screenshot(s)
Files:    copied=42 skipped=0 wrong_size=0
OCR:      processed=42 fields=287 cached=0
Errors:   none
Duration: 187.3s
```

Wrong-dim PNGs (anything ≠ 1510×2013) are listed by full path and
left in staging — they're never copied to the archive. Errors
section caps at 10 entries with a `…and N more` line.

The launchd supervisor logs (Python tracebacks, PaddleOCR progress,
startup messages) land separately:

```sh
tail -f logs/auto_import.stderr.log     # most useful
tail -f logs/auto_import.stdout.log     # usually empty
```

## When the daemon won't start

Most failures land in `logs/auto_import.stderr.log`. Common ones:

- **`Syncthing config not found`** — Syncthing isn't installed, or
  its config moved off the default
  `~/Library/Application Support/Syncthing/config.xml`. The daemon
  needs Syncthing running on this Mac.
- **`no Syncthing folder contains staging path`** — the
  `incoming-captures/` path isn't covered by any Syncthing folder.
  Check the path in Syncthing's GUI matches what the daemon expects.
- **`another auto-import process holds /tmp/nikke-autoimport.lock`** —
  a previous daemon process didn't exit cleanly. `kickstart -k` should
  resolve; if not, `rm /tmp/nikke-autoimport.lock` and restart.

## What to edit if paths change

The plist hard-codes two paths:

- `ProgramArguments[0]` — full path to the `nikkeoptimizer` binary
  (currently `/Users/sleepingcounty/miniconda3/bin/nikkeoptimizer`).
  If you reinstall the project into a different env, update this.
- `WorkingDirectory` + `StandardOutPath` + `StandardErrorPath` —
  all currently `/Users/sleepingcounty/git-other/NikkeOptimizer`.
  Update together if the repo moves.

After editing, restart the agent:

```sh
launchctl kickstart -k gui/$UID/com.nikkeoptimizer.autoimport
```
