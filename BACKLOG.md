# NikkeOptimizer — Backlog

Captured 2026-04-26 at the Phase-2 → Phase-3 boundary. Items here aren't
blocking progress; they're follow-ups we noted while shipping other slices.
Sorted by phase + rough priority within phase.

---

## Phase 1 leftovers

- **Phase 1 regression fixtures (task #9)** — Add golden-output assertions on
  a curated set of screenshots + CSVs so importers can't silently regress.
  The validation suite covers Phase 2; Phase 1 deserves the same.
- **Assist Cube ATK = 190 is wrong** — OCR misreads "7" as "1" on this
  specific cube screenshot (true value is ~790, matching same-level
  Endurance/Healing). Manual fix via the cubes UI works; would be nice to
  add a same-level cross-validation warning at import time.
- **Champion arena portrait geometry** — Only 1/5 cells are confident on
  the IMG_2153 fixture. Faces sit at y 30–75% of cell post-retune but the
  Vision feature embedding still struggles with the smaller card art.
  Possible improvements: tighter face crop, character-specific image
  classifier head, or a manual-correction flow on capture.
- **Unclassified rookie screenshot** — The 9.46.21 PM screenshot lands as
  "unknown" via the title detector. Investigate the detect_title fallback.
- **Learnable portrait embedding (CLIP fine-tune)** — multi-week, but the
  technically clean answer to "more labels = guaranteed better matches".
  The current Apple Vision feature-print is a *frozen* embedding from a
  generic vision model — we can't teach it to weigh face over UI chrome,
  so identical chrome across Champions cells inflates similarity in the
  small-sample regime (slice #137 diagnosed: 1-2 polluted feedback
  exemplars per character caused round-2 captures to match round-1
  characters). Mitigations shipped: tighter face-only feedback crop,
  no-op feedback save when override value is unchanged, `/feedback/clear`
  route. With 10+ exemplars per character chrome noise averages out and
  the current approach is fine. The "learnable" path:
    1. Use CLIP (open_clip ViT-B/32) or SigLIP as the embedding model.
    2. Fine-tune on collected (crop → character) pairs with a contrastive
       loss — characters with same chrome and different faces should be
       pushed apart in the embedding space.
    3. ~1k labeled exemplars likely enough for meaningful fine-tune; the
       user generates these naturally via the override-cell flow over
       weeks of usage.
    4. Drop-in replacement: matcher already abstracts the embedder via
       `FeaturePrintEmbedder` — swap to a CLIP backend when ready.
  Cost: +~1.5 GB install (torch + open_clip), ~200ms/query CPU vs Apple
  Vision's ~10ms. Worth it once the user has the labeled corpus.

## Optimizer feedback from live testing (2026-04-27)

User-observed cases where the optimizer recommends teams they wouldn't field. Captured during the first end-to-end run against their real 170-character roster.

- **Low-investment Nikkes appearing in top recommendations.** Examples:
  - Rookie #3 includes Epinel (skills 1/1/501, no arena cube) — clearly
    under-leveled but credited because she has burst-gen synergies.
  - Rookie #4 includes Rapunzel: Pure Grace (skills 1/1/1) and Dolla
    (skills 4/4/4) — both undertrained. Rapunzel: PG passes the
    `investment` floor because she's a B1.
  - **Likely cause**: the `investment` component caps at a low penalty
    and isn't multiplicative with team value. A Nikke with skills
    1/1/1 should be a near-veto for top-K, not a soft penalty.
  - **Fix direction**: invest a hard threshold — exclude Nikkes from
    top-K consideration when sum(skill1, skill2, burst_skill) < some
    floor (e.g., 18 = average level 6), or apply a steep multiplicative
    penalty for that case.
- **Tier-2 / older meta units credited as if current meta.** Examples:
  - Champions #1 puts Modernia + Dorothy in the lineup — both are
    older B3/B1 picks no longer top-tier in current PvP meta.
  - **Likely cause**: synergy table treats Crown+Modernia and
    Crown+Dorothy with similar weights to Crown+Red Hood etc., when
    in current meta the latter is materially stronger.
  - **Fix direction**: meta-tier weighting layered on synergy. Each
    pair could have a "current PvP relevance" multiplier (1.0 for
    actively-meta units, 0.6 for past-meta, etc.). Source: Prydwen tier
    list snapshots.
- **Damage-formula default-stat calibration is too soft.** Slice #64 wired
  `resolve_by_names()` into counter-pick. First test against the user's
  roster vs a Helm/Centi/Blanc/Bay/Anchor defense produced "predicted clear
  in 1 second, margin +299s" — the default base stats (100k ATK / 1M HP /
  30k DEF) interact with the team's burst payloads such that burst-alone
  vaporizes the defender. The formula is structurally correct but needs
  per-team-power scaling: pull `OwnedCharacter.total_atk/hp/def` and
  feed those into `evaluate_by_names` instead of using fixed defaults.
  Or: use observed match outcomes to tune the multipliers. Currently
  the verdict is binary (WIN/TIMEOUT) — actual margin numbers should not
  be trusted until calibrated.
- **Damage-formula calibration unverified.** The `vs_high_def_damage_index`
  heuristic credits true-damage / pierce / shield-damage carries, but
  there's no validation against actual match outcomes. A team
  predicted to clear at 87s might actually take 200s+ in-game.
  Validation requires capturing real match outcomes (the
  `raw_battle_record` field is wired but unused).

## Phase 2 polish

### High value, small effort
- **Counter-pick web form for manual opponent input** — Currently `/captures/<id>/counter` requires a captured arena match. Add a free-form 5-name input page so users can counter-pick teams they haven't yet captured.
- **ScoreBreakdown panel in SP / Champions web pages** — The rookie page already shows the per-component breakdown; SP and Champions don't.
- **`optimize rookie` should also surface defense team in the CLI** — Already done. (Leaving this here as proof-read confirmation.)

### Medium effort
- **Weight-tuning sliders in web UI** — Let users tweak ATTACK_WEIGHTS / DEFENSE_WEIGHTS components live and re-rank. Useful for power users with non-meta rosters.
- **"Suggest who to level up" advisor** — Find characters in the roster who would join the top-K if their power was higher. Drives Synchro Device / Core upgrade decisions.
- **Roster comparison** — Snapshot the roster on import-csv; offer a "what changed since last week?" diff view.
- **What-if mode** — Simulate "what if I had character X at +N levels / +1 cube tier?" without actually persisting the change.

### Larger
- **Ground-truth match validation** — Capture actual match *outcomes* (battle records) and check whether the optimizer's recommendation would have won. Eventual feedback loop for the simulator.
- **MMR-style diversity tuning** — Lockout is fully disjoint; soft penalty (Maximal Marginal Relevance) would let attack mode show "5 strong teams that share 1–2 members" instead of fully separate cores.

## Roster data gaps

- **`OwnedCharacter.star_count` is redundant + wrong range** — Field
  description says `"1-3 yellow stars"` but actual range is 0–3
  (LB 0 = no yellow stars; see memory note `limit_break_and_core_mechanics.md`).
  Also fully redundant with `OwnedCharacter.limit_break` (0–3, same
  meaning). Pick one and drop the other when doing a schema cleanup
  pass. No DB rebuild needed if just fixing the docstring; column
  removal needs the no-migrations rebuild.
- **Doll vs Treasure CSV gap** — *(largely resolved 2026-05-09 by v2 CSV format)* The new CSV format (2026-05-08+) writes `Doll/Treasure Name`, `Doll/Treasure Rarity` (SSR=Treasure, SR=Doll), `Doll/Treasure Phase`, `Doll/Treasure Stats`, `Doll/Treasure Skill Levels` — distinguishing the two correctly. Importer handles both formats. ~14% of CSV rows occasionally still ship with empty cube/treasure cells (CSV scraper edge cases on certain characters); workaround is re-export until clean. Pre-v2 context preserved below for archaeology:
  1. Investigate why all 17 Treasure-eligible chars show empty Doll columns — does the in-game export show the Favorite Item in place of the Doll, and does our scraper drop it?
  2. Extend the CSV exporter (user-side) with a `Favorite Item Phase` column: 0 = not unlocked, 1/2/3 = phase.
  3. Rename model fields `treasure_*` → `doll_*` (cosmetic, but otherwise misleading); add `favorite_item_phase: int = 0` to `OwnedCharacter`. Touches the schema → DB rebuild required (no-migrations note still applies).
  4. Wire optimizer scoring to route owned chars with `favorite_item_phase >= 1` to their `(Treasure)` DSL encoding when one exists in the registry.

## Phase 2 architecture / quality

- **Counter-pick rebuilds search per call** — Pool + matcher are recomputed every CLI call. For repeated counters in the same session, a cached `OptimizerContext` would cut runtime ~3×.
- **Champions cross-team swap is O(5²×5²×N)** — Fine on a 150-character pool, slow on 200+. Consider sampling-based swap or restricting to candidates with element/role complementarity.
- **Beam search has inline imports** — `import math` inside `_partial_score`. Move to module top.
- **Test suite hits the live `/tmp/nikke_test.sqlite3`** — Validation tests are coupled to whatever's in dev DB. Consider building a stable `tests/fixtures/golden_db.sqlite3` snapshot so tests aren't fragile to DB rebuilds.
- **No db migrations** — Adding columns requires nuking + rebuilding dev DB. Already documented in memory; revisit when persistence becomes load-bearing.

## Phase 3 prep / open questions

- **Skill DSL coverage** — **110 verified encodings** as of 2026-04-28 (~53% of DB). Latest additions: Helm (Treasure), Bready, Exia, Poli, Miranda, Avistar. Earlier same-day: Crow, Belorta, Crust, Frima, Emma:TU, Admi, Anne:MF, Alice:WB, Dorothy:Serendipity, Diesel:WS, Chime, Aria, Asuka:Wille, Dolla, Brid, D, Cocoa, Drake (Treasure), Brid:ST, Soda:TB, Mihara:BC, Elegg:BS, Sakura:BiS, Snow Crane. Full list: Crown attack-comp, defense quartet (incl. Noah), Tia/Naga/Jackal burst-gen + single-target amp, alt B1s (Dorothy / Anis: Star / Volume / Rapunzel: Pure Grace / Soda / Pepper / Soldier OW / Mary: Bay Goddess), B2 SG-comp Leona, top B3 attackers (SBS / Asuka / Alice / Cinderella / Rapi: Red Hood / Maxwell / 2B / A2 / Drake / Phantom / Trony / Snow White / Rapi / Ein / Maiden: Ice Rose / Privaty: Unkind Maid / Power), collab carries (Asuka / Mari / 2B / A2 / Chisato / Power), anti-shield (D: Killer Wife), defensive supporters (Bay / Anchor / Folkwang / Marciana / Quency / Ade / Anchor: Innocent Maid), tier-2 niche (Mast: Romantic Maid / Anis: Sparkling Summer / Sakura / Diesel / Privaty / Anis), Treasure forms (Bay (Treasure) / Centi (Treasure)), alt B2 (Helm: Aquamarine). All translated directly from the live `Character.*_description` fields.
- **Skill DSL stack-cap source-tracking** — DONE 2026-04-28 (slice #86). `AppliedEffect.source_character` + `source_skill_slot` populate from `build_timeline`'s caster/slot info. `state_at` groups by `(target, kind, source_character, source_skill_slot)` and enforces `stacks_max` per group via top-magnitude pick. Crown S2's 3-stack ATK cap now correctly limits the per-Nikke contribution.
- **DSL slice complete — all 39 library files re-encoded under DSL primitives** — Task #55 (2026-04-27) added 8 damage-type buff kinds (BUFF_ATTACK_DAMAGE / BUFF_TRUE_DAMAGE / BUFF_PIERCE_DAMAGE / BUFF_SHIELD_DAMAGE / BUFF_CORE_DAMAGE / BUFF_DAMAGE_TO_PARTS / BUFF_SUSTAINED_DAMAGE / BUFF_BURST_SKILL_DAMAGE), `ScalingSource` (CASTER_ATK/MAX_HP/DEF) on Effect, and `filter_element` / `filter_weapon` / `filter_role` on Target. Task #57 finished re-encoding all 39 library files using these primitives. **Filter enforcement** in evaluator + timeline still requires threading Character data (element/weapon/role) into the simulator layer — currently filters are stored on Target but not narrowed by the resolver. That's a separate slice.
- **Translation methodology for Prydwen prose → DSL** — The DB has fully-scraped descriptions like "Activates when entering Full Burst. Affects all allies. Effect changes according to the activation time(s)." These need careful structural translation. Some skills have multi-stage state (Crown S2: Relax stacks → Attract → recovery → ATK buff) that the current DSL doesn't fully model. Open question: extend DSL with state machines, or accept that complex skills will be lossy?
- **Magnitude verification per encoding** — Every encoded number must come from the DB description (or in-game UI), not memory. Liter / Crown were encoded directly from `skill1_description` etc.; future entries follow the same rule.
- ~~**Per-LB stat percentages are unknown**~~ (resolved 2026-05-09) —
  Reverse-engineered from BlablaLink's bundle and verified against in-game
  displayed stats. LB applies *both* a multiplicative `grade_ratio` (basis
  points, per-character) and a flat `grade_<stat>` per LB star, all inside
  the core multiplier. Per-character data is now mirrored locally
  (`<user_data_dir>/blablalink/<lang>/roledata/<rid>-v2-<lang>.json`).
  See `simulator/base_stats.py` (`BaseStats.compute_full`) and the
  "BlablaLink stat formula" section in CLAUDE.md.
- **Two skill description sources now plumbed in** (added 2026-04-26):
   - `Character.skill_*_description` — canonical max-skill text from the Prydwen scrape; used for DSL encoding.
   - `OwnedCharacter.skill_*_description` + `skill_*_name` + `burst_cooldown_seconds` — user's level-specific text imported from the updated CSV. Use this for per-user UI display ("your Liter S2 currently restores 42% Cover HP at level 6") and for the eventual simulator's per-user level scaling.
- **DSL semantics gaps surfaced by encoding the Crown attack-comp 5-pack**:
   - **Conditional targeting** (Crown S1): "allies who have / haven't bursted" — encoded with `condition` strings the simulator must interpret.
   - **State-machine mechanics** (Crown S2: 43-attack stack → invulnerable + taunt → team buff; SW:HA: Lock-On / Auto Fire Ready / Seven Dwarves Fully Active triple state). Encoded as headline SkillEffects with notes; simulator needs a state machine.
   - **Cumulative-activation effects** (Liter S1: 1st/2nd/3rd Full Burst differ). Encoded with third-tier values; simulator needs an activation counter.
   - **Multi-stage burst progression** (Red Hood: Beast Cage → Last Howl → Red Wolf). Encoded as 3 SkillEffects with stage-specific conditions; once-per-battle CD-reduction effects live in notes (DSL has no per-battle-cap flag).
   - **Cross-stat conversions** (Red Hood S1: Charge Speed >100% → Charge Damage at 240%). Encoded as placeholder with note; runtime computation required.
   - **Stat kinds the DSL lacks**: `DEBUFF_AMMO_CAPACITY` (Modernia S1), `BUFF_HEAL_POTENCY` (Red Hood Step 2), `BUFF_DAMAGE_TO_PARTS` (SW:HA S2, Helm S2), `SET_CHARGE_TIME` (SW:HA S2), `FULL_BURST_TIME_EXTEND` (Modernia burst), Pierce *range* (vs boolean Pierce, Red Hood Step 3), `INDOMITABILITY` / `IMMORTALITY` (Blanc burst), `LIFESTEAL` / `DAMAGE_TO_HP_CONVERSION` (Helm burst), `ATK_DAMAGE` distinct from `BUFF_ATK` (Helm S2, Modernia S1), `ENEMY_HIGHEST_ATK` target kind (Helm burst), `REDUCE_SKILL_COOLDOWN` distinct from `REDUCE_BURST_COOLDOWN` (Centi S1).
   - **"For 1 round" durations** (SW:HA S2): currently encoded as 1.0 second; simulator must distinguish charge rounds from seconds.
- **RNG model** — Defender wins on 5-min timeout. Attacker damage variance is real. Pinning down the RNG seed model is needed before "deterministic" simulation claims.

## Snapshot architecture — future extensions (post Champions v1)

Champions v1 reuses the existing `RosterSnapshot` schema as-is (one
snapshot per `(season_number, player_username)`). When Rookie Arena
work begins we'll need to extend it to support **multiple snapshots
per (season, player)** keyed by date. Design captured here so the v1
build-out doesn't paint us into a corner.

**Schema changes needed for Rookie:**

```python
class RosterSnapshot(SQLModel, table=True):
    # NEW
    snapshot_kind: str          # 'champions_season' | 'rookie_daily' | 'shiftyspad_sync'
    snapshot_date: Optional[date] = None  # required for rookie_daily; null for champions_season
    # Replace the existing unique constraint:
    __table_args__ = (
        UniqueConstraint(
            "snapshot_kind", "season_number", "snapshot_date", "player_username",
            name="uq_roster_snapshot_kind_season_date_player",
        ),
    )
```

Backfill: every existing row gets `snapshot_kind='champions_season'`
(they were all Champions before this split).

**Rookie flow recap** (from 2026-05-16 discussion):
- Rookie Arena = 5 battles/day per player at *actual* per-character
  sync levels (not Champions' fixed-400 clamp).
- Snapshot scope: only the chars that appeared in that day's loadouts
  (typically ≤5 unique chars per player per day).
- Trigger: after match results land via `arena_importer`, run a
  scrape pass to capture each player's state for those chars.
- Storage: one `RosterSnapshot` per `(season, date, player)` plus
  sparse `RosterSnapshotCharacter` rows for just the played chars.

**Resolution stays the same** as Champions v1: `ArenaMatch` has
`user_snapshot_id` + `opponent_snapshot_id` FKs, the simulator
looks the right snapshot up by FK. The Champions LV-400 in-match
clamp is mode-specific (applied at resolution time, not stored in
the snapshot). Rookie reads the per-character `lv` from the snapshot
verbatim.

**Open considerations left for that slice:**
- Auto-trigger snapshot scrape from `arena_importer` (convenient)
  vs. explicit `nikkeoptimizer fetch-shiftyspad --snapshot-kind rookie_daily`
  (decoupled). v1 lean: explicit.
- Slot membership for Rookie's "actual sync level" — current
  ShiftyPad endpoints don't expose synchro-slot membership; the home
  roster's `lv` field gives effective displayed level which is what
  we want. Re-validate before Rookie wiring.
- Privacy: if an opponent's roster is private, write a sparse
  snapshot with `label='private_roster'` and zero per-char rows;
  outpost research (mostly public) still lands on the account-level
  fields. Simulator falls back to defaults for missing per-char data.

## Phase 3 — Rookie Arena follow-ups (2026-05-17 end-of-session)

The Rookie Arena flow shipped end-to-end (ingest → OCR → ArenaMatch
→ RookieArenaSnapshot, daemon-driven). Notes captured during the
live first-run validation:

- **Battle outcome extraction** — wipe detection landed
  2026-05-18 (10 new `(left|right).char{N}.disconnect` regions
  on `results_duel`, uniform 117×22 with 197px y-stride; OCR
  validated 99% confidence). The "DISCONNECTED" badge in NIKKE's
  UI means **defeated/wiped** (not network-disconnected — user
  confirmed). 5/5 wiped on a side → that side lost.
  All 30 historical rookie matches resolved this way (26 W / 4 L).
  Open follow-ups (only matter for the rare timeout case where
  neither side wipes — none observed yet in the dataset):
    1. **Timeout-winner indicator** for the no-wipe case — needs
       a user-supplied sample of a `results.png` from a 5-min
       timeout. Probably a victory icon / cell-color shift /
       banner on the winning team's side, OR fall back to
       comparing the per-Nikke HP% column (`(side).char{N}.hp`
       fields are already extracted; just sum and pick the
       higher side).
    2. `raw_battle_record` per-char stats (atk/heal numbers we
       already OCR but ignore) — would be useful for the
       damage-formula validation in Phase 4.

- ~~**Daemon stale-event-id reset on Syncthing restart**~~ (fixed
  2026-05-17). Original diagnosis was incomplete. Actual root
  cause: `get_current_event_id` queried Syncthing's GLOBAL event
  id (any type) with `since=0&limit=1` → returned 13785. Daemon
  then polled `events=FolderCompletion&since=13785` — but
  FolderCompletion-specific ids only reached 119 (lots of
  `LocalIndexUpdated`/`RemoteDownloadProgress` events between
  each FolderCompletion bump the global counter without bumping
  ours). Filter excluded every existing event AND any new event
  whose id falls in the gap. Fix: query
  `events=FolderCompletion&since=0&timeout=1` and take `max(id)`
  — now we anchor `since=` to the type we actually subscribe to.
  Self-heals across daemon restarts because `_save_last_event_id`
  overwrites the stored value with the new (correct) FC-anchored
  one each time the daemon starts.

- ~~**My-roster auto-refresh from rookie loadouts**~~ (shipped
  2026-05-17). New `roster/rookie_self_refresh.py` harvests the
  union of `user_team` names across the 5 ArenaMatch rows of a
  rookie tournament, maps them to BlablaLink name_codes, and runs
  a sparse `ShiftyPadFetcher.fetch_home` + `fetch_character_details`
  + `sync(apply=True)` against the configured `intl_openid`. Wired
  into `ingest_rookie_root(refresh_self_from_loadouts=True)`; the
  daemon opts in whenever cookies are present. Per-tournament
  cooldown state at
  `<user_data_dir>/state/rookie_self_refresh.json` so a daemon
  restart never re-fetches an already-handled run. New
  `IngestStats.self_refresh_*` counters surface in the audit log
  as a `SelfRfsh:` line. CLI:
  - `nikkeoptimizer set-uid <base64-uid>` (persists to config.json)
  - `nikkeoptimizer refresh-self-from-rookie [<tid>] [--force]`

- **Retire legacy `arena.py`** — proportional-coord arena
  extractor from before the 1510×2013 era. New captures all
  flow through the region-driven family
  (`promo_tournament_regions` + `rookie_arena_regions`).
  Safe to delete after confirming no historical captures still
  rely on it.

## Done — kept here as forward-thinking notes

- Phase 2 alpha: rookie / SP / Champions / counter / counter-sp / explain (shipped)
- Phase 2 polish: 79-pair synergy table with Helm-led entries, role-specific weights, matchup coverage scorer (shipped)
- Validation suite: 11 invariant tests covering canonical meta, role-weight differentiation, element advantage, synergy integrity, determinism (shipped)
- Phase 3 simulator slice 1: static team evaluator with damage-type buff aggregates (shipped)
- Phase 3 simulator slice 2: time-windowed evaluator with buff lifecycles (shipped)
- Phase 3 DSL slice: 8 damage-type buff kinds + ScalingSource cross-stat + Target element/weapon/role filters; all 39 affected library files re-encoded (shipped)
- Phase 3 simulator slice 3: damage-formula resolution — Team A vs Team B comparison using published NIKKE damage formula (ATK channel + DEF mitigation, true-damage / pierce / shield-damage / sustained-damage channels, Full Burst / element / crit averages, 5-min timeout verdict). Deterministic, ignores per-event RNG and state machines. Sets foundation for ML-driven optimization (Phase 4). (shipped)
- Phase 3 simulator slice — burst-gauge dynamics (slice #75, 2026-04-28). Per-weapon fill-rate table (SG 3.3/s, RL 2.8/s, MG 2.2/s, SR 2.0/s, AR 1.7/s, SMG 1.6/s) calibrated so Crown comp lands at the legacy t=10 default. `compute_burst_chain_offsets()` derives offsets from team weapon mix; `build_timeline_by_names` auto-loads weapons from DB. SG/RL-heavy teams burst earlier, MG/SMG comps later. Per-Nikke skill gauge bonuses (Liter S1, Naga, Anchor) still TBD. (shipped)
- Phase 3 simulator slice — burst-gauge wired into damage + scoring (slice #77, 2026-04-28). `damage.resolve` now multiplies the burst payload by the number of full-burst rotations that fit in the match (`(MATCH_LENGTH - first_burst_sec) / 40s`). `resolve_by_names` auto-derives `first_burst_sec` from the attacker's weapon mix. `_score_burst_gen` adds a +/-1.5 weapon-mix speed bonus around the 12s legacy baseline. SG/RL teams now get measurable scoring + win-margin uplift. (shipped)
- Web UI burst-timing display (slice #79, 2026-04-28). New `BurstTiming` helper + `burst_timings_for(teams)` parallel computation. Rookie/SP/Champions/counter routes now surface "[timing] first burst @ Xs · FB Y-Zs" line on each team card. (shipped)
- Phase 3 simulator slice — burst-gauge skill bonuses (slice #78, 2026-04-28). `BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC` table covers 18 named gauge-bonus characters (Liter +2.0/s, D +2.5/s, Tia/Dorothy/Anchor 1.2-1.6/s, etc.). `compute_burst_chain_offsets()` accepts an optional `member_names` arg that adds the bonuses on top of weapon-rate sum. `build_timeline_by_names`, `resolve_by_names`, and `_score_burst_gen` thread member names automatically. Liter on Crown comp now bursts at t=8.3s (vs t=10s without). (shipped)
- **Damage-formula stat calibration** (slice #88, 2026-04-28 PM). `evaluate_team` accepts a new `per_name_stats` mapping; `evaluate_by_names` auto-loads each member's `OwnedCharacter.total_atk/hp/def` via `_load_owned_stats` (defensive fallback to coarse defaults). `damage.py` fixed an `atk_buff_pct` double-count in `_per_member_atk_damage_multiplier` (it's already in `effective_atk`) and added a `DAMAGE_PER_SHOT_FRACTION = 0.10` calibration constant — real NIKKE shots deal 7-100% of ATK, not full ATK per hit. Verdicts moved from "1s clear, +299s margin" to "11-30s clear" with realistic per-Nikke stats (Liter ATK 324k, etc.). Per-weapon shot multipliers + FB-window-only burst payload remain open follow-ups. (shipped)
- **Investment-floor env override** (slice #89, 2026-04-28 PM). `effective_min_skill_sum()` reads `NIKKE_OPTIMIZER_MIN_SKILL_SUM` at call time so the veto can be relaxed (=0 disables) or tightened without code changes. All four optimizer entry points (rookie/sp_arena/champions/counter) + investment_advisor consume it. 8 new tests cover pass/veto/explainer-mode/env-override/zero-disable cases. (shipped)
- **ScoreBreakdown panel on SP / Champions** (slice #90, 2026-04-28 PM). Both routes now match the rookie page's per-component display (burst / power / elements / roles / synergy / invest / durability / burst-gen + buff-amp / vs-high-DEF when set). (shipped)
- **Counter-pick free-form opponent input** (slice #91, 2026-04-28 PM). New `/counter` route + `counter_freeform.html` template. 5 datalist-backed text inputs autocomplete from `Character.name`; unknown names surface as warnings; partial input shows "need all 5". Reuses `recommend_counter` so output matches the capture-driven flow. Linked from the global nav. (shipped)
- **Match-outcome capture** (slice #92, 2026-04-28 PM). New POST `/captures/{id}/outcome` accepts win/loss/timeout + user_role + seconds_to_clear; persists outcome/user_role to existing columns and stashes seconds_to_clear inside `raw_battle_record` (no schema change). Captures list shows the outcome column. Foundation for damage-formula validation and Phase 4 training data. (shipped)
- **Cube same-level cross-validation** (slice #93, 2026-04-28 PM). `web/cube_warnings.py` flags cubes whose ATK/HP/DEF differ by >40% from the same-level median. Catches the original Assist Cube ATK=190 (true ~790) OCR misread case. Cubes list surfaces flags inline + a banner count. 6 new tests. (shipped)
- **OptimizerContext caching** (slice #94, 2026-04-28 PM). `loader.OptimizerContext` + `get_context(session, db_path)` keyed on DB mtime. `recommend_counter` accepts an optional `context=` arg to skip the load step. Web routes use it. Honest perf claim: ~3% per-call wall-clock benefit (beam search dominates), but call surface is now clean for more aggressive future caching (precomputed pair-scores, partial-team enumeration). (shipped)
- **Auto-detect username banner** (slice #95, 2026-04-28 PM). Dashboard offers a one-click "Save 'X' as my username" button when no username is configured but captures exist (uses existing `detect_self_username` helper). POST `/config/username` persists. Eliminates the only manual setup step left for CP cross-validation auto-confirm. (shipped)
- **Burst payload as steady-state DPS, not t=0 head-start** (slice #96, 2026-04-28 PM). `damage.resolve` previously credited the entire multi-cycle burst payload (`burst_total × bursts_in_match`) at `first_burst_sec`, which collapsed clear time toward the first burst when burst_payload was large. Now burst contributes `burst_total / cycle_period_sec` to steady-state DPS — clear time scales with `defender_hp / total_dps` correctly. Crown comp clear time moved from 11s → 35s (still attacker-favored vs realistic 60-120s, but no longer degenerate). 2 new tests. (shipped)
- **Per-weapon shot multiplier table** (slice #97, 2026-04-28 PM). Replaced the global `DAMAGE_PER_SHOT_FRACTION = 0.10` with a per-WeaponClass table — AR/SMG/MG (sustained DPS) score higher than SR/RL (slow-but-big-shot). The `/num_members` divisor is gone; each Nikke contributes individually via her own weapon factor. SR-heavy comps now score lower DPS than mixed AR/SMG comps in counter-pick output, matching the meta. 1 new test. (shipped)
- **MMR-style diversity tuning + beam search 3× speedup** (slice #98, 2026-04-28 PM). `select_diverse_top_k(candidates, top_k, mmr_lambda)` in `search.py` replaces the per-iteration full-lockout loop in rookie + counter-pick — top-K teams may now share 1-2 members when base score is significantly higher (`mmr_lambda=2.0` default; `inf` reproduces hard lockout). Bonus: profiling showed `_partial_score` was 67% of beam-search time due to per-call `role_tags` scans. Added `_precompute_contributions` to cache per-character contribution upfront. Combined effect: counter-pick latency 1095ms → 388ms (2.8× faster). 3 new MMR tests. (shipped)
- **Roster diff polish** (slice #99, 2026-04-28 PM). Snapshot infrastructure was already complete (auto-saves on CSV import); added manual `snapshot` / `snapshots` CLI commands, a "Snapshot roster now" button + saved-confirmation banner on `/roster`, and a summary count line on the diff page ("X added · Y removed · Z changed"). 1 new test. (shipped)
- **Counter-pick re-rank by win-margin** (slice #100, 2026-04-28 PM). After damage-formula resolution, re-sort `unique` + `damage_resolutions` in parallel by a combined key: heuristic_score + bounded(win_margin/60). Win bonus capped at +3, predicted-timeout penalty at -2 — nudges close calls toward damage-formula confidence without overwhelming clearly-better heuristic teams. (shipped)
- **Champions speedup via roles cache** (slice #101, 2026-04-28 PM). Profile of `recommend_champions` showed `_roles_of` was 60% of `score_team` time (24M calls × per-tag startswith). Added `_ROLES_CACHE: dict[tuple, frozenset]` keyed on the immutable `role_tags` tuple. Champions latency 1165ms → 661ms (1.76× faster). The earlier "O(N×5²×5²)" claim in BACKLOG was a red herring — actual bottleneck was per-call role lookup, not the swap matrix. (shipped)
- **MMR fallback to lockout + dedup** (slice #100b, 2026-04-28 PM). Smoke-testing the MMR refactor surfaced two bugs: (a) polish converges multiple beam seeds onto the same composition → MMR returned 5 identical teams in counter-pick top-K. Added member-set dedup at the top of `select_diverse_top_k`. (b) When MMR finds < top_k distinct teams (high min_power, dominant single comp), fall back to per-iteration lockout so users still get top_k variations. Updated `test_attack_and_defense_top_picks_differ` to a more robust score-differentiation assertion (the old "must be different teams" check broke when one team is genuinely dominant on both axes). (shipped)
- **Phase 1 regression fixtures — name matcher** (slice #102, 2026-04-28 PM). The `_find_character` 6-step fallback chain had only end-to-end coverage via `test_import_full_roster_csv`. Added 7 focused tests: exact / case-insensitive / paren-disambiguator / colon-alt-form / collab short-form prefix / ambiguous prefix / unknown-name. Locks in the regression-prone smart matcher. (shipped)
- **Web UI: scoring weight tuning** (slice #103, 2026-04-28 PM). `/optimize/rookie?synergy_w=2.5&durability_w=3.0&...` now accepts seven optional weight overrides corresponding to each `ScoringWeights` field. A collapsible "Scoring weights" panel surfaces a table with default values + custom inputs; submit re-runs the optimizer. Defense follows the same overrides. SP/Champions extension is a follow-up. (shipped)
- **Weight tuning extended to SP / Champions** (slice #104, 2026-04-28 PM). Same query params + collapsible panel as rookie. Refactored the panel into a Jinja `_weight_panel.html` partial included by all three optimizer pages. `recommend_sp_arena` and `recommend_champions` accept an optional `override_weights=` ScoringWeights that replaces both attack and defense presets. (shipped)
- **Captures list outcome filter** (slice #105, 2026-04-28 PM). `/captures?outcome=win|loss|timeout|untagged` filters the list. Useful for finding which captures still need a manual outcome tag for damage-formula validation. (shipped)
- **Stack-cap source-tracking tests** (slice #86b, 2026-04-28 PM). The `Timeline.state_at` source-grouping behavior shipped in slice #86 had only weak end-to-end coverage. Added 4 focused unit tests that construct synthetic Timelines: cross-source non-stacking, same-source cap, top-magnitude pick within cap, and legacy-effect (no-source) independent counting. (shipped)
- **Investment advisor web route** (slice #106, 2026-04-28 PM). `/roster/advisor` route + `roster_advisor.html` template. Mirrors the existing `nikkeoptimizer advisor` CLI in the web UI — surfaces under-invested Nikkes and how much top-K score lift each upgrade unlocks. New "Advisor" link in the global nav. (shipped)
- **MMR diversity for SP arena attack** (slice #107, 2026-04-28 PM). SP arena attack used hard lockout; the game allows attack reuse, so 3 fully-disjoint cores forced lower slots into weak fillers. Switched attack to `_mmr_distinct` (lambda=2.0) with lockout fallback. Defense keeps lockout (uniqueness is a hard game rule). (shipped)
- **Damage-formula validation harness** (slice #108, 2026-04-28 PM). New `/validate` route that backtests the damage resolver against tagged captures. Reports win/loss accuracy, confusion matrix, and mean clear-time error. Foundation for "is the simulator getting better?" feedback as more matches get tagged. New "Validate" link in nav. (shipped)
- **Team copy-export for chat** (slice #109, 2026-04-28 PM). Added `copyTeam(btn)` clipboard helper to `_base.html` and a "Copy" button on every team card across rookie/sp/champions/counter/counter-freeform pages. Copies a `Name1 / Name2 / ...` string for paste into Discord etc. (shipped)
- **Synergy table coverage audit** (slice #110, 2026-04-28 PM). New `synergy_audit.py` + `nikkeoptimizer synergy-audit` CLI command. Surfaces encoded characters with 0 or 1 synergy pair entries (currently 93 of 122 encoded chars are under-represented) so the maintainer can decide which pairings to add to `SYNERGY_PAIRS`. (shipped)
- **DSL coverage push 110 → 122** (slices #111+#112, 2026-04-28 PM). Encoded 12 owned-but-unencoded characters from the user's roster: Little Mermaid (Siren), Liberalio, Noise, Moran, Tove, Quency: Escape Queen (slice #111); Raven, Ade: Agent Bunny, Vesti: Tactical Upgrade, Ludmilla: Winter Owner, Grave, Noir (slice #112). Each file cites the source `Character.skill_*_description` text and notes DSL gaps (state machines, multi-stage Overheat, etc.) inline. (shipped)
- **Synergy table expansion 79 → 125 pairs** (slice #113, 2026-04-28 PM). Added 46 pairings: meta-relevant pairings for the 12 newly encoded characters (Vesti:TU+Crown, Ade:AB+Maxwell, Liberalio+Crown, Noir+Tove, etc.) plus gap-fills for previously encoded but under-represented attackers (Maxwell, Cinderella, A2, 2B, Phantom, Trony, Ein, Mihara). Under-represented count dropped 93 → 82 of 122 encoded characters. (shipped)
- **SYNERGY_PAIRS typo guard** (slice #114a, 2026-04-28 PM). New `test_synergy_pairs_contain_no_unknown_character_names` validates every name in the table against the live DB. Catches typos at test time rather than as a silent zero-bonus run-time miss. Allowlist hook for hypothetical / unreleased characters. (shipped)
- **Synergy notes promoted on team cards** (slice #114, 2026-04-28 PM). Team cards previously buried "synergy: X + Y (+5.0)" entries inside the generic notes panel. Two new Jinja filters (`synergy_notes` / `other_notes`) split them so each card now has a dedicated **Synergies:** line listing which pairings fired, separate from the rest of the notes (timing, damage formula). Applied to rookie/sp/champions/counter/counter-freeform. (shipped)
- **CLI `validate` command** (slice #114b, 2026-04-28 PM). Mirrors the `/validate` web route as a terminal command. Same backtest, formatted as a Rich table. (shipped)
- **Optimizer perf cache (3.25× rookie speedup)** (slice #115, 2026-04-28 PM). Profiled the post-#101-cache rookie pass and found `_weapon_mix_speed_bonus` and `_score_synergy_pairs` were both calling deterministic computations 100k times. Wrapped both in `lru_cache(maxsize=4096-8192)` keyed on sorted team identity. Rookie top-5 latency 6500ms → 2000ms. Tests still pass — caches return immutable tuples to avoid mutation bugs. (shipped)
- **Counter-pick element-coverage badge** (slice #116, 2026-04-28 PM). New `element_coverage(team, opponent)` helper returns `(covered, distinct)` opponent-element counts. Counter-pick recommendations now show "element coverage 3/5" on each team card so users can spot-check whether the recommended team actually exploits the opponent's weaknesses. (shipped)
- **Synergy table expansion round 2** (slice #117, 2026-04-28 PM). Added 41 more pairings: Asuka:Wille / Mihara:BC / Maiden:IR / Chisato / Takina / Jill / Ada / Soldier OW / Rei:TN / Sakura:BiS / Snow White / Rapi / Privaty:UM / Drake / Treasure forms / Pepper / Dorothy:S / Folkwang / Marciana / Quency / Ade. Pairs grew 125 → 166. Under-represented count 82 → 67 of 122 encoded characters. (shipped)
- **Encoded-coverage badge on team cards** (slice #117b, 2026-04-28 PM). Each team card now shows "X/5 encoded" so users know whether to trust the simulator-derived numbers (or note that they're absent because some members aren't in the DSL library). Applied to rookie / SP / Champions. (shipped)
- **Encode 6 more chars 122 → 128** (slice #118, 2026-04-28 PM). Mana, Viper, Arcana: Fortune Mate, Rouge, Rosanna, Biscuit. Continues the coverage push for owned-but-unencoded chars. (shipped)
- **Damage formula docstring rewrite + rookie clear-time** (slices #119a + #119, 2026-04-28 PM). The damage.py module-level docstring described the old "head-start subtract burst payload" model; rewrote to describe the current per-Nikke stats → per-weapon DPS → time-averaged burst pipeline. Rookie attack page now shows predicted clear-time vs a canonical Helm/Centi/Blanc/Bay/Anchor benchmark per team. (shipped)
- **Synergy expansion round 3 + threshold guard** (slice #119b, 2026-04-28 PM). 54 more pairings (220 total) covering Anis: Star, Aria, Avistar, Belorta, Bready, Brid, Brid:ST, Chime, Crow, Crust, Eve, Exia, Frima, Jackal, Kilo, Laplace, Makima, Misato, Mast:RM, Nayuta, Nihilister, Pascal, Power, Quiry, Rem, Sin, Snow Crane, Yulha, Diesel, Diesel:WS, Cocoa, Anne:MF, Alice:WB, Mari, Soda:TB, Rosanna:CO, Elegg:BS, Guillotine:WS, Emilia, Emma:TU, Volume, Mary:BG, Admi, Trony, Anis, Soda, Privaty, Sakura. New regression test: under-represented count must stay below 50% of encoded chars. (shipped)
- **Encode 6 more 128 → 134** (slice #120, 2026-04-28 PM). Trina, Mast (base), Julia, Elegg (base), Maiden (base), Milk: Blooming Bunny — chars seen in opponent captures or owned-but-unencoded. With matching synergy pairs added so the threshold test stays green. (shipped)
- **Robust screenshot path resolution** (slice #121, 2026-04-29). The web review section was returning 404 on most captures because the DB stored relative `tests/fixtures/...` paths from CLI imports, and those fixture files were trimmed to keep the dir small. New `_resolve_screenshot_path` in `web/app.py` searches by basename + mode through 4 candidate locations (stored path → project-root-relative → `<db_dir>/screenshots/<Mode>/` → `<db_dir>/uploads/`). Resolved paths persist back to the DB so subsequent loads skip the search. 13/13 review captures now resolve. (shipped)
- **Phase 4 feasibility — genetic algorithm** (slice #122, 2026-04-29). New `optimizer/genetic.py` with tournament selection, single-point crossover, member-swap mutation, elitism. CLI `nikkeoptimizer ga` runs and side-by-side compares to beam search. **Big finding**: GA's top-1 (84.61) outscored beam's top-1 (59.12) on the user's actual roster — surfaced a real bug in beam-search's `_partial_score` (it didn't include synergy, so Crown-comp partials were pruned before assembly). Slice #122a fixed that — beam top-1 now 88.63, GA's earlier best becomes beam's #4. 7 new GA tests. (shipped)
- **Damage-formula tuning panel** (slice #123, 2026-04-29). `/validate?damage_per_shot=0.05&cycle_period=60&min_def_through=0.10` now sweeps the three core tuning constants. Collapsible "Damage formula tuning" panel surfaces the form. `damage.resolve` accepts these as kwargs (was a global-only constant). Lets the user iterate on calibration once they tag matches. (shipped)
- **DSL coverage 134 → 140** (slice #124a, 2026-04-29). Epinel, Soline: Frost Ticket, Arcana, Guillotine, Harran, Neon: Blue Ocean. Mix of meta-historical carries + niche electric-code support. (shipped)
- **Synergy expansion round 4 → 254 pairs** (slice #124b, 2026-04-29). Pairings for the round-5 encodings + gap-fills for Soldier OW, Mast:RM, Sakura, Volume, Marciana, Quency, Ade, Folkwang, Pepper, Bay, Anchor, Trony, Anis:Star. Under-represented count 67 → 61 of 140 encoded. (shipped)
- **DSL coverage 140 → 146** (slice #125, 2026-04-29). Clay, Mary, Yan, Privaty (Treasure), Mica: Snow Buddy, Neon: Vision Eye. (shipped)
- **Synergy expansion round 5 → 349 pairs, ZERO under-represented** (slice #126, 2026-04-29). Final coverage push: every encoded character (146/146) has ≥2 synergy pairs. The under-represented count is now 0 — all future encoded chars need their own pairs to keep the threshold test green. (shipped)
- **Investment advisor relaxed criteria** (slice #127, 2026-04-29). Surfaces candidates whose upgrade beats the baseline top-K floor even if they don't crack the top-K. Adjusts roi_score to use both lift and absolute team-strength delta. Result: 1 → 3 recommendations on the user's actual roster (Noah, Centi, Anis: Star). (shipped)
- **DSL coverage 146 → 152** (slice #128a, 2026-04-29). Eunhwa, Mori, Diesel (Treasure), Julia (Treasure), Laplace (Treasure), Frima (Treasure). Heavy on Treasure-form encodings — useful once the Doll/Treasure CSV gap is closed. (shipped)
- **GA web UI** (slice #128b, 2026-04-29). New `/optimize/ga` route + `optimize_ga.html` template. Shows GA top-K side-by-side with beam-search top-K, with GA-only / shared / beam-only set comparison. Form lets users tune population size, generations, seed for reproducibility. Linked from global nav. (shipped)
- **GA convergence sparkline** (slice #129, 2026-04-29). Inline pure-SVG polyline showing best-fitness + mean-fitness across generations on the GA page. No JS needed. Lets the user see at a glance whether GA converged or is still improving. (shipped)
- **Roster diff: power delta column** (slice #130, 2026-04-29). Per-row Δ column for numeric field changes (color-coded green/yellow/grey) plus a total power delta header across all changed Nikkes. Quick visual feedback on net investment progress between snapshots. (shipped)
- **DSL coverage 152 → 158** (slice #131, 2026-04-29). Miranda (Treasure), Moran (Treasure), Milk (Treasure), Exia (Treasure), Tove (Treasure), Poli (Treasure). 6 Treasure-form encodings with concise headline-only DSL — fills out the 17 Treasure-eligible roster once the Doll/Treasure CSV gap is closed. (shipped)
- **Synergy threshold tightened to ≤5** (slice #132, 2026-04-29). After hitting 0 under-represented chars in slice #126, raised the regression test bar from `len(encoded)//2` to a hard ≤5 cap. Future encoding rounds that don't ship matching synergy pairs now fail the test loudly. (shipped)
- **DSL coverage 158 → 164** (slice #133, 2026-04-29). Eunhwa: Tactical Upgrade, Ludmilla (base), Milk (base), Rumani, K, Label. Each shipped with at least 2 synergy pairs to satisfy the tightened threshold test. Total session coverage: 80 → 164 chars (+84 over the day). (shipped)
- **Doll/Treasure CSV gap CLOSED** (slice #134, 2026-05-02). The user provided an updated CSV format that explicitly distinguishes Doll from Treasure via a new `Doll/Treasure Rarity` column (SSR=Treasure, SR/R=Doll). Changes:
  - `OwnedCharacter` schema: added `treasure_rarity` + `treasure_skill_levels` (ALTER TABLE applied to both `/tmp/nikke_test.sqlite3` and the user's main DB; per the no-migrations note).
  - CSV importer reads new `Doll/Treasure {Name,Rarity,Phase,Stats,Skill Levels}` columns with fallback to legacy `Treasure {Name,Phase,Stats}` so historical CSVs still parse.
  - `CharacterView.is_treasure_unlocked` flag set when rarity == SSR and phase ≥ 1.
  - `simulator.evaluator._route_treasure_forms` auto-substitutes `<name>` → `<name> (Treasure)` when user has Treasure unlocked AND the registry has a Treasure-form entry. Stats + identities re-keyed under routed names so the substitution carries through to per-Nikke stat lookup. 2 new tests.
  - Imported the new CSV: 12 Treasures detected (Helm, Centi, Bay, Drake, Diesel, Tove, Privaty, Moran, Miranda, Exia, Laplace, Poli) + Neon: Vision Eye added to roster (+ portrait file).
  - Crown comp vs user defense (with Treasure routing): clear time corrects from 24s → 51s as the boosted Treasure-form stats kick in. (shipped)
