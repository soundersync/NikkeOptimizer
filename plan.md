# NikkeCopilot — plan & open work

Forward-looking companion to `CLAUDE.md` (project context) and
`BACKLOG.md` (granular notes). This file answers "what's done, what's
next, what's the long arc?"

Last updated: 2026-04-28 (afternoon — slices #88-#95).

---

## Where we are

**Phase 1 — Data layer + roster import.** Shipped, polished.
- 206 static characters scraped from Prydwen.
- 184/184 owned characters imported from CSV (smart name matcher
  handles 12 collab short-form mismatches).
- 17 cubes captured + extractor; 15 arena captures.
- Manual-correction web UI; per-cell screenshot view; per-Nikke power
  capture; capture completeness warnings.

**Phase 2 — Heuristic optimizer.** Shipped, polished.
- Modes: Rookie, SP Arena (with defense-uniqueness), Champions Arena
  (5-team season planner with matchup coverage).
- Counter-pick mode (CLI + web) for both Rookie and SP.
- "Why not character X?" explainer.
- Role-specific weights (attack vs defense vs balanced).
- 79-pair synergy table.
- Validation suite covering canonical meta, role differentiation,
  element advantage, synergy integrity, determinism.

**Phase 3 — Simulator.** 3/3 slices shipped. Foundations complete; state
machines + filter enforcement still TODO.
- Skill DSL: 4 primitive types, 8 damage-type buff kinds, ScalingSource
  for cross-stat scaling, element/weapon/role filters on Target.
- 80 characters hand-encoded in `simulator/library/` (~39% of DB,
  covers the meta + most collab carries).
- Static team evaluator: post-burst-chain snapshot of 5 Nikkes.
- Time-windowed evaluator: buff lifecycles, queryable at any t.
- Damage-formula resolution: Team A vs Team B comparison using
  published NIKKE damage formula. Returns
  `attacker_wins_within_5min` + win margin.
- Optimizer wired to use simulator signals
  (`buff_amp` + `vs_high_def` rescore components).
- 78 simulator tests passing.

**Phase 4 — ML-driven optimization.** Not started.

---

## Open work, by impact

### Just-shipped (2026-04-28)

- **Slice #61 — Prydwen scraper extended** with `specialities`,
  `pros_raw`, `cons_raw`, `review_raw`, `skill_analysis_raw`,
  `harmony_cubes_info_raw`, `has_treasure`, `high_investment`,
  `is_limited`, `limited_event`, `release_date`, `squad`. Verified on
  Red Hood. DB ALTER TABLE applied in-place; existing rows have
  default values until refresh runs. `flatten_rich_text()` helper for
  Contentful AST → plain text.
- **Research finding**: Prydwen does NOT expose structured tier
  ratings (S/A/B per category) in any of its page-data JSON. The
  tier-list page renders client-side from a flat 206-character list,
  and tier groupings live in a JavaScript bundle. The "auto-scrape
  meta tiers" question is therefore answered: not available; the
  meta-tier multiplier (#65 below) needs a hybrid approach.

### High-leverage product fixes

1. ~~**Investment-floor veto in the optimizer scorer.**~~
   **DONE — slice #89.** ``has_minimum_investment`` (floor=18 by default)
   in `constraints.py` already vetoed sub-floor teams; this slice wired
   the ``NIKKE_COPILOT_MIN_SKILL_SUM`` env override (read at call time
   via ``effective_min_skill_sum()``) and added 8 tests covering
   pass/veto/explainer-mode/env-override/zero-disable cases. All four
   optimizer entry points (rookie / sp_arena / champions / counter)
   now read the env override.

2. ~~**Wire damage resolver into counter-pick mode.**~~ **Already shipped
   in slice #64.** Web counter route surfaces predicted win-margin
   per recommended team. Slice #88 (this session) replaced the
   degenerate 100k/1M/30k stat defaults with per-Nikke
   ``OwnedCharacter.total_atk/hp/def`` (auto-loaded by
   ``evaluate_by_names``) and fixed an ``atk_buff_pct`` double-count
   in ``_per_member_atk_damage_multiplier``. Added
   ``DAMAGE_PER_SHOT_FRACTION = 0.10`` to bring per-shot damage into
   the right ballpark (real NIKKE weapons deal 7-100% of ATK per shot,
   not full ATK). Verdicts moved from "1s clear, +299s margin" to
   "11-30s clear" — still attacker-favored vs realistic NIKKE PvP, so
   per-weapon shot multipliers + FB-window-only burst payload remain
   open calibration TODOs.

3. ~~**Meta-tier weighting on synergy pairs.**~~ **Already shipped.**
   ``META_TIER`` table in `scoring.py` covers ~50 named characters
   with 0.4-1.0 multipliers (Modernia 0.6, Dorothy 0.6, etc.); pair
   bonuses scale by ``min(tier_a, tier_b)``. Heuristic fallback in
   ``_meta_tier_for`` uses 0.85 for defenders/supporters/healers,
   0.7 otherwise.

4. **Per-Nikke power for opponent-side validation.**
   Per-cell CP capture is wired (slice #59). User-side CP is now used
   for auto-confirm. Opponent-side CP could also support
   "consistency across captures": if the same opponent appears in 3
   captures with the same CP per Nikke, confidence on borderline
   matches goes up. Reduces review burden further.

5. **Doll/Treasure CSV gap.**
   CSV columns labeled `Treasure Name/Phase/Stats` actually hold
   Doll data. Real Favorite Item (Treasure) unlock state is missing
   entirely. Required for the 17 Treasure-eligible chars to score
   against their `Bay (Treasure)` / `Centi (Treasure)` / etc. DSL
   encodings. User has Treasures unlocked for most. Plan in
   `BACKLOG.md` under "Roster data gaps."

### Phase 3 simulator completeness

6. ~~**Filter enforcement in evaluator + timeline.**~~ **Already shipped
   (slice #68).** ``evaluate_by_names`` auto-loads identities
   (element/weapon/role) from the DB via ``_load_identities`` and
   threads them into target resolution. Element-/weapon-/role-filtered
   buffs now narrow correctly. (Slice #88 this session added a
   parallel ``per_name_stats`` auto-load for ATK/HP/DEF.)

7. **State machines.**
   Anti A.T. Field, MP gauge (Maiden: Ice Rose), Hero Level
   (Guillotine: WS), Memory Absorption (Nayuta), Highway to Hell
   (Mihara), Combat Assist (Rapi: RH), Drunken (Mast: RM), Calm
   (Yulha), Beast Cage / Last Howl / Red Wolf stages (Red Hood),
   Storage (Marciana / Anchor: IM), and more — all encoded today as
   headline effects with descriptive notes. Each needs a tracker on
   the simulator side. Multi-session work.

8. **Burst-gauge dynamics.**
   Timeline uses fixed burst offsets (10/11/12/13/14 sec). Real model
   would compute per-Nikke gauge fill rates from
   ammo-capacity / charge-speed / weapon-class etc., producing
   accurate burst times. Important for non-2-1-2 burst chains.

9. **Stack-cap source tracking.**
   `AppliedEffect` doesn't track `(target, kind, source_character,
   source_skill_slot)` so the timeline drops cap enforcement and
   sums everything. Crown S2's 3-stack ATK from successive ally
   bursts is not capped; it just accumulates.

10. **Matcher feedback loop.**
    Manual overrides should feed back into the portrait-matcher index
    as labeled exemplars. Reduces residual review-burden over time.

### Smaller open items

- ~~**Match-outcome capture**~~ **DONE — slice #92.** Manual
  win/loss/timeout + user_role + seconds_to_clear tagging via
  capture detail page; outcome surfaces in the captures list.
  ``raw_battle_record["seconds_to_clear"]`` carries the clear time
  without a schema change. Foundation for damage-formula validation.
- **Match-outcome screenshot extractor** — auto-fill the manual
  outcome by reading the post-battle Battle Records screen for
  per-Nikke damage/heal/take stats. Replaces the manual tagging
  flow once it lands.
- **Tier-2 niche encodings** — 120+ chars unencoded. Diminishing
  returns; the meta is covered.
- **Phase 1 regression fixtures** (task #9, perpetually pending).
- ~~**Cube same-level cross-validation**~~ **DONE — slice #93.**
  ``web/cube_warnings.py`` flags any cube whose stat differs from the
  same-level median by >40%. Surfaces on `/cubes` row + count banner.
  0 flags on the user's current DB (Assist Cube already corrected).
- **Champion arena portrait geometry retune** — only 1/5 cells
  confident on the IMG_2153 fixture.
- ~~**Counter-pick free-form opponent input**~~ **DONE — slice #91.**
  New route `/counter` with 5 datalist-backed text inputs and full
  validation; reuses ``recommend_counter`` so output matches the
  capture-driven flow.
- ~~**Counter-pick caching (OptimizerContext)**~~ **DONE — slice #94.**
  ``loader.OptimizerContext`` + ``get_context(session, db_path)``
  cache pre-loaded view lists keyed on DB mtime. Web routes use it.
  Real-world speedup is modest (~3% — beam search dominates) but the
  call surface is now ready for more aggressive caching upstream.
- ~~**ScoreBreakdown panel on SP/Champions web pages**~~ **DONE —
  slice #90.** Both routes now match the rookie page's per-component
  display.
- ~~**Auto-detect username (first-run UX)**~~ **DONE — slice #95.**
  Dashboard banner offers a one-click save when no username is
  configured but captures exist. POST /config/username persists.

---

## Phase 4 — ML optimization (future, multi-month)

Once the simulator is complete enough to produce trustworthy win/loss
verdicts, replace the heuristic scorer with a learned one:

1. **Genetic / beam search over team space**, scored by the simulator,
   to discover non-obvious team compositions.
2. **Self-play RL** — agent picks attack and defense teams against
   itself, learns what wins consistently.
3. **Transformer over `(my_team, opponent_team) → win_prob`** trained
   on synthetic data the simulator generates.
4. **Replace the heuristic scorer in Phase 2 plumbing** with the
   learned model; same solvers (beam search, branch-and-bound for SP
   uniqueness, GA for Champions 5-team plan) consume it.

Validation plan:
- Backtest learned recommendations against held-out match data.
- Track recommendation-acceptance rate from the user.

---

## Recommended near-term path

If picking up this project cold, the open task IDs (from the runtime
task list) are:

1. **#62** — Run `nikkecopilot refresh` so the new Prydwen fields
   actually populate for all 206 characters. ~5 min, just verification.
   Blocks #65, #66.
2. **#63** — Investment-floor veto in the optimizer scorer. Resolves
   the live-testing complaint about Epinel / Rapunzel: PG / Dolla
   appearing in top recommendations. ~30 min, mechanical.
3. **#64** — Wire damage resolver into counter-pick mode. Turns
   abstract scores into concrete win-margin predictions. ~1-2 hours.
4. **#65** — Meta-tier multiplier (hybrid: manual table for known
   meta + heuristic fallback using new Prydwen fields). Resolves the
   Modernia/Dorothy over-credit complaint. ~1-2 hours.
5. **#66** — Web UI character detail pages (renders Prydwen rich-text
   pros/cons/review). Most visible "use of new data." ~2 hours.
6. **#67** — Doll/Treasure CSV gap — proper Favorite Item phase
   capture so the 17 Treasure-eligible chars score against their
   `(Treasure)`-form DSL encodings. Coordination with user (CSV
   format change) + DB rebuild.
7. **#68** — Filter enforcement in evaluator/timeline (element/
   weapon/role-narrowed targets). Unblocks accurate scoring for ~15
   characters with filtered buffs.

After those, the bigger Phase 3 items (state machines, burst-gauge
dynamics, stack-cap source tracking) and Phase 4 (ML).

### Round 2 — small UX wins + foundational pieces (queued 2026-04-28)

| # | Subject | ~Effort | Why |
|---|---|---|---|
| **69** | Auto-detect self-username from captures | 30 min | Eliminates first-run friction |
| **70** | `nikkecopilot doctor` setup verification | 1 hr | Self-diagnosis on env issues |
| **71** | Multi-capture consensus for portrait matcher | 2 hr | Halves review burden alongside #60 |
| **72** | Roster diff / "what changed since last week" | 2 hr | Track investment progress; foundation for #73 |
| **73** | "Suggest who to level up" advisor | 2-3 hr | Turns optimizer into investment advisor; uses slice #61's `high_investment` |
| **74** | Encode 6 more tier-2 chars | 2 hr | Coverage 80 → 86; lower priority than meta-tier work |
| **75** | Phase 3 — Burst-gauge dynamics | multi-session | Foundation for accurate non-2-1-2 chain timing |

---

## Questions / decisions to surface in the next session

- ~~`NIKKE_COPILOT_USERNAME` env var as the gate for CP cross-
  validation~~ — **resolved 2026-04-28**. Username now persisted to
  `<user_data_dir>/config.json` (currently `{"username": "Nika"}`).
  Env var still takes precedence; CLI command
  `nikkecopilot set-username <name>` writes the file.
- ~~Meta-tier source for fix #3~~ — **resolved 2026-04-28**.
  Prydwen does not expose structured tier ratings; #65 will use a
  manual override table refreshed quarterly + a heuristic fallback
  built on slice #61's new fields (recency, is_limited,
  high_investment).
- **Phase 4 timeline.** Are we deferring until the simulator is fully
  trustworthy (state machines + filter enforcement + match-outcome
  validation), or starting an ML feasibility experiment in parallel?

---

## Reference: granular open items

For per-character / per-encoding / per-bug detail, see `BACKLOG.md`.
For accumulated user-preference and project-context memories, see
`~/.claude/projects/-Users-sleepingcounty-git-other-NikkeCopilot/memory/MEMORY.md`.
