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
    data/
      db.py                           # SQLite engine + path resolution
      models.py                       # SQLModel schema (Character, OwnedCharacter, AccountState, ...)
      enums.py                        # Element / WeaponClass / BurstType / Manufacturer / Rarity
      scrapers/
        prydwen.py                    # Prydwen.gg character data scraper
        blablalink.py                 # BlablaLink CDN per-character stat tables (Playwright)
    roster/
      csv_importer.py                 # CSV → OwnedCharacter rows (v1 + v2 format, dry-run diff)
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
```

The `web` command auto-launches the default browser; pass `--no-open`
for headless. Default port 8765.

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
Read `MEMORY.md` there for short hooks pointing to:

- Portrait library data quirks (label byte-duplicates)
- Vision feature-print API gotcha (pyobjc metadata)
- FastAPI Jinja2 signature change (positional args)
- No DB migrations (column adds need rebuild)
- Don't trust memory for NIKKE attributes (query DB first)
- Doll vs Treasure CSV gap (CSV columns mislabeled, no per-Treasure unlock data)

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
