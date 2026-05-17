# NikkeOptimizer — context for future Claude sessions

This file is the first thing Claude should read on a fresh session.
It exists so we don't have to re-explain the project from scratch every
time. Pair it with `plan.md` (current state + what's left) and
`BACKLOG.md` (granular notes + DSL gaps + feedback).

---

## What this project is

A **PvP team optimization AI** for the mobile gacha game **Goddess of
Victory: NIKKE**. Helps a player decide which 5-Nikke teams to field
across the game's three PvP modes:

| Mode | Lineup | Constraint |
|---|---|---|
| **Rookie Arena** | 1 attack team + 1 defense team | None |
| **SP Arena** | 3 attack + 3 defense | Defense Nikkes unique across the 3 defense teams |
| **Champions Arena** | 5 teams, season-locked | Each team plays both attack/defense via 50/50 coin flip |

All three modes are **fully auto-resolved** in-game — the player
doesn't control units mid-match. So the optimization problem is "pick
the right K Nikkes from your roster," not "play the match well." Match
length is capped at 5 minutes; defender wins on timeout.

---

## Architecture (4 layers)

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 4 — ML / RL (NOT STARTED)                             │
│  Self-play, transformer over (my_team, opponent) → win_prob  │
├──────────────────────────────────────────────────────────────┤
│  Layer 3 — Scoring                                           │
│  (a) Heuristic scorer (Phase 2, shipped)                     │
│  (b) DSL-driven simulator: static eval + timeline + damage   │
│      formula resolution (Phase 3, partial)                   │
├──────────────────────────────────────────────────────────────┤
│  Layer 2 — Roster (user's investment state)                  │
│  CSV import → SQLite. Arena-screenshot OCR also lands here.  │
├──────────────────────────────────────────────────────────────┤
│  Layer 1 — Static character database                         │
│  Scraped from Prydwen + NikkeAPI mirror; skill DSL library.  │
└──────────────────────────────────────────────────────────────┘
```

Phase status:
- **Phase 1 (data + import)**: shipped, polished
- **Phase 2 (heuristic optimizer)**: shipped (rookie / SP / Champions / counter / counter-sp / explain)
- **Phase 3 (simulator)**: 3/3 slices shipped — static eval, time-windowed eval, damage-formula resolution. State machines + filter enforcement still TODO.
- **Phase 4 (ML)**: not started

---

## File layout

```
NikkeOptimizer/
  BACKLOG.md                          # granular open items + DSL gaps
  CLAUDE.md                           # ← you are here
  plan.md                             # current state + what's left
  pyproject.toml                      # deps + scripts (`nikkeoptimizer` entry)

  src/nikke_optimizer/
    cli/main.py                       # typer CLI; `nikkeoptimizer <cmd>`
    auto_import.py                    # Syncthing-event-driven ingest daemon + audit log
    data/
      db.py                           # SQLite engine + path resolution
      models.py                       # SQLModel schema (Character, OwnedCharacter, AccountState, ...)
      enums.py                        # Element / WeaponClass / BurstType / Manufacturer / Rarity
      scrapers/
        prydwen.py                    # Prydwen.gg character data scraper
        blablalink.py                 # BlablaLink CDN per-character stat tables (Playwright)
        shiftyspad.py                 # BlablaLink player-profile scraper (live + snapshot modes)
        shiftyspad_decoder.py         # gear/cube/treasure/bond tid resolvers (cached tables)
        blablalink_user_lookup.py     # name → openid search + level verify + triage CSV (lookup-players)
    roster/
      csv_importer.py                 # CSV → OwnedCharacter rows (v1 + v2 format, dry-run diff)
      shiftyspad_importer.py          # ShiftyPad → OwnedCharacter (live) + RosterSnapshot (Champions)
      arena.py                        # arena screenshot extractors
      arena_importer.py               # arena import pipeline + CP cross-validation auto-confirm
      portrait_matcher.py             # Apple Vision feature-print matching
      portrait_library.py             # labeled portrait library loader
      _vision_features.py             # pyobjc Vision wrapper
    simulator/
      dsl.py                          # Effect / Trigger / Target / EffectKind / ScalingSource
      registry.py                     # auto-loaded character library
      library/                        # hand-encoded characters (one .py per)
      evaluator.py                    # static team evaluator (post-burst-chain snapshot)
      timeline.py                     # time-windowed evaluator with buff lifecycles
      damage.py                       # Team A vs Team B damage-formula resolution
      base_stats.py                   # BlablaLink-driven stat formula (level/grade/core → ATK/HP/DEF/Power)
      account_buffs.py                # Outpost research → buff dict helper
    optimizer/
      models.py                       # CharacterView, ScoreBreakdown, TeamCandidate
      scoring.py                      # heuristic scorer + ScoringWeights + rescore_with_evaluator
      constraints.py                  # burst-chain validity check
      rookie.py / sp_arena.py / champions.py / counter.py
      snapshot_views.py               # CharacterView ← RosterSnapshot (Champions LV-400 clamp)
    web/
      app.py                          # FastAPI; create_app(db_path, portrait_library)
      templates/                      # Jinja2 (server-rendered, no JS framework)
      capture_warnings.py             # per-row + set-completeness warnings
      evaluator_helper.py             # optimizer ↔ simulator bridge
      static/style.css

  tests/
    fixtures/
      prydwen/                        # scraper fixtures (kept)
      screenshots/                    # only test-referenced files (5MB)
    test_simulator_*.py               # 78 tests, no DB/OCR deps
    test_arena*.py                    # require macOS + sqlmodel + portrait library
    ...

  scripts/
    migrations/                       # NNNN_*.sql + apply_migrations.py (idempotent, dual-DB)
    launchd/                          # auto-import daemon plist + install instructions
    debug/                            # exploratory scripts (.gitignored dumps/ subdir)

  logs/                               # gitignored; auto-import daemon writes here
    auto_import.log                   # human-readable audit, one stanza per ingest run
    auto_import.{stdout,stderr}.log   # launchd supervisor capture
```

---

## Where data lives

The user's data dir is `~/Library/Application Support/NikkeOptimizer/`
on macOS (via `platformdirs.user_data_dir`). Three things live there:

| Path | What | Notes |
|---|---|---|
| `nikke_optimizer.sqlite3` | DB (Character, OwnedCharacter, AccountState, Cube, ArenaMatch, ...) | 183 owned chars, 206 static, 17 cubes, 15+ captures |
| `portraits/` | 335 labeled `.webp` images | Used by Vision matcher; auto-discovered at startup |
| `screenshots/` | User's gameplay screenshots organized by mode | Champion_Arena/ Special_Arena/ Rookie_Arena/ Cubes/ loose/ |
| `uploads/` | Files uploaded via the web drop-zone | Auto-routed to the right importer |
| `config.json` | Persistent user settings | Currently just `{"username": "Nika"}` |
| `blablalink/` | Mirrored BlablaLink character JSONs | `nikke_list_<lang>_v2.json` + `<lang>/roledata/<rid>-v2-<lang>.json` (~189 files, ~25MB) |

Resolution order for the user's in-game name (used by CP cross-validation
auto-confirm to identify which team in a capture is the user's own):
1. `NIKKE_OPTIMIZER_USERNAME` env var
2. `username` key in `config.json`
3. Fallback heuristic: 3-of-5 captured CPs match the owned roster's CPs

Other env overrides:
- `NIKKE_OPTIMIZER_DB` — DB path
- `NIKKE_OPTIMIZER_PORTRAITS` — portrait library path
- `NIKKE_OPTIMIZER_USERNAME` — see above (also persistable via `nikkeoptimizer set-username <name>`)

---

## Tech stack

- Python 3.12+
- **Web**: FastAPI + uvicorn + Jinja2 (server-rendered HTML, no JS framework)
- **DB**: SQLite + SQLModel
- **OCR**: PaddleOCR for text + Apple Vision feature-prints for portrait matching (pyobjc-framework-Vision/Quartz/Cocoa — macOS only)
- **CLI**: typer + rich
- **Tests**: pytest. Simulator suite is pure-Python (no sqlmodel/PIL needed); arena/CSV/web tests require the full deps.

Install: `pip install -e .` from project root. Pulls everything (~2GB
because of paddleocr/paddlepaddle).

For simulator-only work: `pip install pytest` and run with
`PYTHONPATH=src python -m pytest tests/test_simulator_*.py`.

---

## Common commands

```sh
nikkeoptimizer web                          # web UI (auto-discovers portrait library)
nikkeoptimizer roster                       # list owned characters in CLI
nikkeoptimizer diff-csv <path>              # dry-run: show diff vs DB before importing
nikkeoptimizer import-csv <path>            # import roster from CSV (v1 + v2 format)
nikkeoptimizer optimize rookie --top-k 5    # CLI optimizer
nikkeoptimizer counter <capture_id>         # counter-pick a captured opponent
nikkeoptimizer simulate <name1> ... <name5> # static evaluator on a team
nikkeoptimizer skill <name>                 # inspect encoded skill DSL
nikkeoptimizer skill-coverage               # DSL-encoded vs DB total
nikkeoptimizer fetch-roledata <id|name>     # mirror BlablaLink character stat tables
nikkeoptimizer fetch-roledata --all         # mirror every character (~30 min @ rate 9.5)
nikkeoptimizer roledata-coverage            # cross-reference simulator library vs cache
nikkeoptimizer set-research --general 300   # set Outpost research levels (singleton)
nikkeoptimizer refresh --name "Mint"        # refresh a single character from Prydwen (or all)
nikkeoptimizer ingest-tournaments \         # one-shot relocate + OCR pass over staging
  --staging incoming-captures/champion_arena
nikkeoptimizer auto-import                  # foreground daemon mode (normally launchd-run)
```

### Auto-import daemon (Syncthing → ingest)

Installed as a user launchd agent that auto-starts at login. See
`scripts/launchd/README.md` for the full operator manual; the
high-frequency commands:

```sh
# Status / live tail / restart / stop.
launchctl print gui/$UID/com.nikkeoptimizer.autoimport | grep -E 'state|pid|last exit'
tail -f logs/auto_import.log              # human-readable audit, one stanza per run
tail -f logs/auto_import.stderr.log       # Python tracebacks / PaddleOCR progress
launchctl kickstart -k gui/$UID/com.nikkeoptimizer.autoimport   # restart
launchctl bootout    gui/$UID/com.nikkeoptimizer.autoimport     # stop (auto-restart at login)
```

How it works:
- Reads Syncthing's API key + folder ID from
  `~/Library/Application Support/Syncthing/config.xml` at startup.
- Long-polls `GET /rest/events?events=FolderCompletion` filtered to
  the folder whose path contains `incoming-captures/`.
- On `completion: 100`, debounces 5s, then calls `ingest_root()`
  in-process (PaddleOCR stays warm across runs).
- Single-instance via `flock /tmp/nikke-autoimport.lock`. Last seen
  event id persisted to
  `~/Library/Application Support/NikkeOptimizer/state/syncthing_last_event_id.txt`
  so a restart skips already-handled events.
- **Copy-only** — never moves or deletes from `incoming-captures/`;
  staging stays Syncthing's domain.
- Source PNGs are dimension-checked against
  `REFERENCE_PNG_SIZE = (1510, 2013)` in `promo_tournament_ingest.py`.
  Mismatches are warn + skip + listed in the audit stanza; never
  copied to the archive.

### ShiftyPad (BlablaLink player-profile scraper)

```sh
nikkeoptimizer shiftyspad-login                                # one-time browser login (cookies persist ~30d)
nikkeoptimizer fetch-shiftyspad <uid>                          # dry-run sync to live OwnedCharacter table
nikkeoptimizer fetch-shiftyspad <uid> --apply                  # actually write
nikkeoptimizer fetch-shiftyspad <uid> --names "Alice,Modernia" # subset by name
nikkeoptimizer fetch-shiftyspad <uid> --max-chars 3            # safety cap during dev

# Champions Arena snapshots — sparse RosterSnapshot per (season, player).
# Always writes (no dry-run); re-running replaces the prior snapshot.
nikkeoptimizer fetch-shiftyspad <uid> --snapshot --season 30                    # self snapshot (auto player name)
nikkeoptimizer fetch-shiftyspad <uid> --snapshot --season 30 \
    --player-username "Aerin" --names "Crown,Modernia,Liter"                    # opponent snapshot, sparse

# Convenience: derive the name list from already-captured match data
nikkeoptimizer snapshot-names --season 30 --player Aerin                        # prints comma-separated

# Stubs for new characters BlablaLink knows about but Prydwen hasn't covered yet
nikkeoptimizer stub-character "Mint"                                            # minimal Character row from BlablaLink

# Player-lookup triage (no DB writes): name+level list → 31-col CSV
# of who's on NA, who's Public, plus the base64 uid to pipe into fetch-shiftyspad.
nikkeoptimizer lookup-players players.csv                                       # → ~/Downloads/nikke_player_lookup_<date>.csv
nikkeoptimizer lookup-players - --tolerance 20 --only "Agito,Royalvio"          # stdin + subset
```

The `web` command auto-launches the default browser; pass `--no-open`
for headless. Default port 8765.

The ShiftyPad scraper paces detail-page navigations at random 3-7s
intervals (per [[blablalink-scraper-behavior]]) — a full 186-char
sync takes ~15 min. Subset/snapshot scrapes that target a handful of
chars finish in well under a minute.

### Player-lookup triage flow

`lookup-players` is the *triage* step before `fetch-shiftyspad`: given
a `(name, expected_level)` list, it calls BlablaLink's `SearchUser` +
`GetUserGamePlayerInfo` to find each player's `intl_openid` on NA
(`area_id == "82"`), then navigates `/shiftyspad/home` once to capture
the same XHRs `fetch-shiftyspad` would (`BasicInfo`, `OutpostInfo`,
`GetUserCharacters` — the latter just to read its return code for the
`My Nikkes` public/private flag). All 31 CSV fields are derived from
typed JSON paths, not innerText regex.

Output schema is tuned for hand-off: every Found row carries a `UID`
column (the base64 string `fetch-shiftyspad` takes positionally) and a
`Worth Fetching` flag (yes iff roster *or* outpost is Public). The CLI
prints ready-to-paste `nikkeoptimizer fetch-shiftyspad <uid>` lines
at the end of the run. `Status` values: `Found` / `No Search Results`
/ `Not On NA` / `Level Mismatch`. Default tolerance ±15 (widen for
older lists). No DB writes — pure JSON → CSV. Source: SKILL.md (the
original Claude-in-Chrome flow), reimplemented in Python.

---

## Skill DSL — the load-bearing model

The simulator runs on a declarative DSL of every character's skills.
Each character lives in `simulator/library/<name>.py` and registers
itself by calling `register_character(_SKILL)` at import time. The
`registry` module auto-imports every file in `library/` at startup, so
adding a new character is a one-file change.

The DSL has 4 primitive types:
- `Trigger` — when does the skill fire? (`ON_BURST_USE`, `ON_HIT`, `ON_TIMER`, `CONDITIONAL`, ...)
- `Target` — who's affected? Includes `filter_element` / `filter_weapon` / `filter_role` for narrowing.
- `Effect` — what happens? (`BUFF_ATK`, `BUFF_TRUE_DAMAGE`, `DEAL_DAMAGE`, `GRANT_SHIELD`, ...). Has `scaling_source` (NONE / CASTER_ATK / CASTER_MAX_HP / CASTER_DEF) for cross-stat buffs like "ATK +30% of caster's ATK".
- `SkillEffect` — bundles one Trigger + a tuple of Effects.

**Encoding rule**: every magnitude must come from the live
`Character.skill_*_description` text in the DB. Never encode from
memory. The DB has the canonical max-skill-level prose.

**Full list of EffectKinds**: see `simulator/dsl.py`. Notable damage-type
kinds added in slice #55: `BUFF_TRUE_DAMAGE`, `BUFF_ATTACK_DAMAGE`,
`BUFF_PIERCE_DAMAGE`, `BUFF_SHIELD_DAMAGE`, `BUFF_CORE_DAMAGE`,
`BUFF_DAMAGE_TO_PARTS`, `BUFF_SUSTAINED_DAMAGE`, `BUFF_BURST_SKILL_DAMAGE`.

**80 characters encoded** as of 2026-04-28. Coverage is the meta + most
collab carries; the long tail (~120 chars) is unencoded.

---

## BlablaLink stat formula (slice 2026-05-08)

Reverse-engineered from BlablaLink's character page JS bundle and verified
against in-game displayed numbers to the digit. Implementation lives in
`simulator/base_stats.py` (`BaseStats.compute_full(...)`).

**Formula** for each stat ∈ {ATK, HP, DEF}:
```
F = floor(level_<stat>[lv-1] * (1 + grade*grade_ratio*1e-4)
          + grade*grade_<stat>)
basic = round(
    (F + floor(class_buff + manufacturer_buff + recycle_buff) + round(bond_buff))
    * (1 + core*core_<stat>*1e-4)
)
total = basic + equip + cube + treasure
```

**Per-character data** (level table, grade/core multipliers, crit) is
mirrored from the BlablaLink CDN via `nikkeoptimizer fetch-roledata`.
The CDN URLs are content-hashed at runtime by their JS, so we use a
headless Chromium (Playwright) to load their character page and capture
JSON responses. Cache lands at `<user_data_dir>/blablalink/`.

**Account-wide buff rates** (from `simulator/account_buffs.py`, derived
from observed in-game values):

  - General Research: +450 HP / level
  - Class research:   +750 HP, +5 DEF / level
  - Manufacturer research: +25 ATK, +5 DEF / level

Set via `nikkeoptimizer set-research --general 300 --attacker 179 ...`.
Singleton row in `AccountState` table.

**Per-character buffs** (bond, class rank, manufacturer rank flat stats)
land in `OwnedCharacter` from the v2 CSV format (2026-05-08+). Optimizer
uses these directly when present; falls back to AccountState-derived
buffs for unowned characters (counter-pick scoring).

After v2 CSV import, `predicted_base_atk/hp/def` on `CharacterView`
reproduce displayed in-game stats **to the digit** for owned characters
(172/172 exact match in May 2026 validation).

---

## ShiftyPad scraper + Champions snapshots

The ShiftyPad scraper (`data/scrapers/shiftyspad.py` + `roster/shiftyspad_importer.py`)
pulls a player's profile + roster + per-character details via 4 BlablaLink
endpoints. Two write modes:

**Live mode** (default): writes to `OwnedCharacter` / `AccountState` —
the user's current roster. Partial-update semantics (preserves OL gear
rows that the CSV importer populated). Dry-run by default; pass
`--apply` to commit.

**Snapshot mode** (`--snapshot --season N`): writes to `RosterSnapshot`
+ `RosterSnapshotCharacter`. Always writes; replaces any prior
snapshot for the same `(season_number, player_username)`. Sparse by
design — only chars passed via `--names` (or all chars when omitted)
get per-char rows. Account-level fields land on the snapshot row from
`outpost_info`.

### OL gear decoding (the load-bearing find)

Every gear `option_id` (the 3 rolled bonuses per piece) is decoded
from `state_effects[i].function_details[0].function_value` (integer ×
100 = percent) returned alongside `character_details` in the same
endpoint. Combined with cached static CDN tables (`yu-75` gear, `bl-25`
bonus groups, `qe-66` bond, per-tid cube/treasure files under
`<user_data_dir>/blablalink/tables/`), the scraper renders exact
in-game gear stats — validated formula `(base × (10 + lv) + 5) // 10`.

The static tables auto-cache from page navigations
(`maybe_persist_table_response` in `shiftyspad_decoder.py`), so a
single full scrape pre-warms the decoder for every cube/treasure the
player has equipped.

### Champions snapshot resolution

`ArenaMatch` rows for Champions mode link to two `RosterSnapshot`
rows via `user_snapshot_id` + `opponent_snapshot_id` FKs (migration
0001). `optimizer/snapshot_views.py:load_views_for_match()` returns
the right `CharacterView` list per side, applying the Champions
**LV-400 cap at resolution time** (snapshots store the player's
actual sync level — clamping is mode-specific).

When `fetch-shiftyspad --snapshot --season N` runs, it auto-links any
existing Champions `ArenaMatch` rows in that season where
`player_username` appears as user or opponent. Match-season membership
is derived via `data/seasons.season_for_date(match.captured_at.date())`.

### Stub characters (Mint case)

When BlablaLink ships a new Nikke before Prydwen does, the scraper
flags her as `unmatched`. Workflow:

1. `nikkeoptimizer stub-character "Mint"` — creates a minimal
   `Character` row from BlablaLink data (rarity/element/weapon/class/mfr).
   Marked with `source = "blablalink_stub"`.
2. Future scrapes report her under "stubs awaiting Prydwen refresh"
   with the upgrade hint.
3. When Prydwen catches up: `nikkeoptimizer refresh --name Mint`
   overwrites the stub with full review data; `source` flips to
   `"prydwen"`; the warning silently disappears.

### Schema migrations

`scripts/migrations/0001_arena_match_snapshot_fks.sql` is the first
migration shipped via `scripts/migrations/apply_migrations.py`. The
runner detects existing columns + uses `CREATE INDEX IF NOT EXISTS`,
so it's idempotent. Always applied to BOTH databases per
[[dual-DB-ALTER]] memory; missing DBs (e.g. `/tmp/nikke_test.sqlite3`
when not yet created) are gracefully skipped.

For new migrations: drop a `NNNN_description.sql` in `scripts/migrations/`,
re-run `apply_migrations.py`. Update the SQLModel definition in the
same change so a fresh DB built from `SQLModel.metadata.create_all`
gets the same shape.

---

## CSV format versions

The importer handles both:
- **v1** (pre-2026-05-08): basic columns, treasure data partial.
- **v2** (2026-05-08+): adds `Limit Break` ("3/3" current/max format),
  `Core Level` ("max" or 0-7), bond/class/mfr rank levels +
  per-character flat stats, full gear stats per slot. Detected
  automatically by presence of the `Limit Break` column.

`csv_parsers.parse_stats_block` accepts `,`, `;`, or `/` as separators
across the three CSV format generations.

`nikkeoptimizer diff-csv <path>` runs a dry-run: shows per-character
field diffs, classifies "stripped" vs "uninvested baseline", and
flags Power drops worth investigating before any writes happen.

---

## Memory system

There's a persistent memory at
`~/.claude/projects/-Users-sleepingcounty-git-other-NikkeOptimizer/memory/`.
Read `MEMORY.md` there for the live index. Highlights worth knowing:

- **No DB migrations** — column adds rebuild dev DB; or use the
  scripts/migrations/ runner now landing as a pattern.
- **Dual-DB ALTER pattern** — when adding columns, alter both
  `/tmp/nikke_test.sqlite3` AND the user's main DB.
- **BlablaLink scraper behavior** — must mimic human browsing
  (one char at a time, randomized delays, no bulk fetches even when
  the API allows it). Account-flagging risk.
- **NIKKE synchro level semantics** — outpost cap vs per-char
  actual vs CSV column are three distinct things; Champions overrides
  sync to 400 in-match (applied at resolution, not at snapshot time).
- **Don't trust my memory for NIKKE attributes** — query the
  Character table first.

When you learn something non-obvious about how the user works or about
a project constraint, save it there. Format and rules are in the
auto-memory section of the system prompt.

---

## Test running

The full suite hits sqlmodel + paddleocr + pyobjc, which may not be in
every Python env. Two tiers:

**Simulator-only (always works in this repo's `.venv` / base):**
```sh
PYTHONPATH=src python -m pytest \
  tests/test_simulator_dsl.py \
  tests/test_simulator_evaluator.py \
  tests/test_simulator_timeline.py \
  tests/test_simulator_damage.py
# 78 tests
```

**Full suite:** needs the project installed (`pip install -e .`) plus
the macOS Vision framework. Currently 154+ tests when env is complete.

---

## Conventions worth preserving

- **No `git add -A`** when staging — the test fixtures dir has churn.
- **No DB migrations** — adding a column to a SQLModel table requires
  rebuilding the dev DB. We've used in-place `ALTER TABLE` for SQLite
  twice (per-Nikke power columns) but it's manual and brittle.
- **Server-rendered HTML, no JS framework.** A single inline `<script>`
  block for drag-and-drop is the only JS; everything else is form
  submits + redirects. Keep it that way unless there's a strong reason.
- **Tests should skip cleanly when their fixture is missing** —
  arena/portrait tests use `pytest.skip` rather than failing, since
  not all environments have the labeled portrait library.
- **DSL encoding always cites the source description** at the top of
  each library file. Future changes should preserve that comment block
  so future-you can verify the magnitudes against the in-game text.

---

## Known gotchas / things that bit us before

- **CSV name mismatches**: collab characters use short names in CSV
  ("Chisato") but the DB has full names ("Chisato Nishikigi"). The
  CSV importer's `_find_character` has a 5-tier fallback; if you see
  silent drops, that's the path.
- **`/tmp/nikke_test.sqlite3`** was a historical dev DB used in earlier
  sessions before the canonical `user_data_dir` location took over.
  Tests that reference `/tmp/nikke_test.sqlite3` skip when not found.
- **Distance threshold 0.62** is the portrait-matcher confidence floor.
  Below = auto-confirm, above + small rank-1/rank-2 gap = needs review.
  Slice #60 added CP cross-validation that promotes borderline matches
  on the user's own team when captured CP matches owned roster CP.
- **Burst chain offsets** in the timeline are fixed (10/11/12/13/14
  seconds) — not derived from gauge dynamics. This is a known
  approximation; replacing it is a future Phase 3 slice.
- **State machines** (Crown's Relax, SW:HA's Lock-On, MP gauge,
  Anti A.T. Field, Memory Absorption, Hero Level, Highway to Hell, ...)
  are encoded as headline effects with descriptive notes, NOT as actual
  state machines. The simulator doesn't track them yet.
