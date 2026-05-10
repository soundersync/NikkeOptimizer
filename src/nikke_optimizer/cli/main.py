"""CLI entry point — `nikkeoptimizer <command>`.

Commands implemented today:
  refresh     pull latest character data from Prydwen into the local DB
  characters  list characters currently in the local DB

Stubs for future phases:
  import      OCR a roster screenshot and persist owned-character rows
  optimize    suggest top-K teams for a given mode
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from ..data.db import default_db_path, get_session, init_db, make_engine
from ..data.models import Character

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="NikkeOptimizer — PvP team optimization for Goddess of Victory: NIKKE.",
)
console = Console()


@app.callback()
def _root(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable info-level logging"),
) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def refresh(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass on-disk fetch cache"),
) -> None:
    """Fetch character data from Prydwen and upsert into the local database."""
    from ..data.scrapers.refresh import refresh_async

    counts = asyncio.run(refresh_async(db_path=db, use_cache=not no_cache))
    console.print(f"[bold green]Refresh complete[/]: {counts}")
    console.print(f"DB: {db or default_db_path()}")


@app.command(name="crop-tool")
def crop_tool(
    image: Optional[Path] = typer.Argument(
        None,
        help="Optional path to an image to load at startup (otherwise drag-drop or use Open…).",
    ),
) -> None:
    """Visual crop-coordinate utility — derive region constants by selection.

    Drag-and-drop an image (or pass a path), click two corners, press
    `s` to save the cropped image and copy image-relative coords to the
    clipboard. Press `f` to reset; mouse wheel to zoom.

    Coordinates are formatted as `(x1, y1, x2, y2)` with 4-decimal
    fractions ready to paste into a region constant in `roster/arena.py`.
    """
    from ..tools.crop_tool import run

    if image is not None and not image.is_file():
        console.print(f"[red]Image not found:[/] {image}")
        raise typer.Exit(code=1)
    run(image)


@app.command(name="ingest-tournaments")
def ingest_tournaments(
    staging: Path = typer.Option(
        Path("champion_arena"),
        "--staging",
        help="Staging dir holding promotion_tournament_* folders.",
    ),
    archive: Optional[Path] = typer.Option(
        None,
        "--archive",
        help="Archive root (defaults to <repo>/captures/, matching the web app's static mount).",
    ),
    move: bool = typer.Option(
        False, "--move",
        help="Delete staging files after a successful copy + size match.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Allow a second tournament on a date already populated (suffixes _2, _3, ...).",
    ),
    ocr: bool = typer.Option(
        True, "--ocr/--no-ocr",
        help="Run OCR over every screenshot after relocation. Default on.",
    ),
    force_ocr: bool = typer.Option(
        False, "--force-ocr",
        help="Re-OCR screenshots that already have extracted fields.",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path"),
) -> None:
    """Relocate tournament/league staging folders into the archive and persist DB rows.

    Walks every ``promotion_tournament_<TS>`` / ``champions_duel_<TS>`` /
    ``league_<TS>`` folder under ``--staging``, copies (or with
    ``--move``, moves) the source PNGs into
    ``<archive>/beta_season_<N>/<format>/...``, skips coord-picker
    leftovers (``__masked.png`` always; ``__crop.png`` except for
    league leaderboard crops), then upserts PromoTournament /
    PromoGroup / PromoMatch / PromoMatchScreenshot rows. Idempotent —
    safe to re-run.

    The season number comes from the parent staging folder when it
    matches ``beta_season_<N>[_…]`` (e.g. dropping
    ``beta_season_29_2026-05-07/`` as ``--staging``); otherwise it's
    derived from the captured-at date via the cadence table in
    ``data/seasons.py``.
    """
    from ..roster.promo_tournament_ingest import ingest_root

    if not staging.is_dir():
        console.print(f"[yellow]Staging dir not found: {staging}[/]")
        # Still proceed — the ingest will pick up archive-only folders.
    stats = ingest_root(
        staging_root=staging,
        archive_root=archive,
        move=move,
        force=force,
        ocr=ocr,
        force_ocr=force_ocr,
        db_path=db,
    )
    console.print(f"[bold green]Ingest complete[/]: {stats}")
    if stats.errors:
        console.print("[red]Errors:[/]")
        for err in stats.errors:
            console.print(f"  · {err}")


@app.command(name="label-tournament-portraits")
def label_tournament_portraits(
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path"),
) -> None:
    """Backfill loadout portraits with character_ids from same-round duel results.

    Loadout screenshots show portraits but no character names; duel
    results show both. For each loadout, this finds the corresponding
    duel (same match + same round), determines which side of the duel
    the loadout's player is on (by player_name OCR vs the overview's
    left_name / right_name), and copies the 5 character_ids into the
    loadout's char1..5.portrait extraction rows.

    Idempotent — re-runs only update rows whose character_id changed.
    No Vision API calls, no PaddleOCR, just a slot-correspondence join.
    """
    from sqlmodel import Session

    from ..data.db import init_db, make_engine
    from ..roster.promo_tournament_ocr import backfill_portrait_character_ids

    engine = make_engine(db)
    init_db(engine)
    with Session(engine) as session:
        examined, updated = backfill_portrait_character_ids(session)
    console.print(
        f"[bold green]Portrait labeling complete[/]: examined={examined} updated={updated}"
    )


@app.command(name="label-tournament-dolls")
def label_tournament_dolls(
    label_dir: Optional[Path] = typer.Option(
        None,
        "--label-dir",
        help="Directory of labeled exemplars (defaults to web/static/doll-icons).",
    ),
    backend: str = typer.Option(
        "auto",
        "--backend",
        help="Classifier: auto | vision | hsv. Auto picks Vision when a manually-corrected corpus exists, HSV otherwise.",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path"),
) -> None:
    """Classify the doll/treasure tier on every loadout slot.

    Two backends:
      * ``vision`` (preferred when audited): Apple Vision feature-print
        K-NN over the manually-corrected corpus. Captures intra-class
        variation a single exemplar can't.
      * ``hsv``: mean-squared HSV distance against the labeled
        exemplar files in ``web/static/doll-icons``. Cold-start friendly.
      * ``auto``: Vision when the corpus is non-empty, else HSV.

    Manually-corrected rows are sticky — never overwritten on re-run.
    """
    from sqlmodel import Session

    from ..data.db import init_db, make_engine
    from ..roster.promo_tournament_doll_match import (
        backfill_doll_classifications,
    )

    engine = make_engine(db)
    init_db(engine)
    with Session(engine) as session:
        examined, updated, counts = backfill_doll_classifications(
            session, label_dir=label_dir, backend=backend,
        )
    console.print(
        f"[bold green]Doll labeling complete[/]: examined={examined} updated={updated} backend={backend}"
    )
    if counts:
        console.print("[bold]Class distribution:[/]")
        for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            console.print(f"  {key:18s} {n}")


@app.command(name="audit-vision-disagreements")
def audit_vision_disagreements(
    k: int = typer.Option(5, "--k", help="K for nearest-neighbour vote."),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path"),
) -> None:
    """Diagnostic: rows where Vision disagrees with the human label.

    Builds the corpus from every manually-corrected doll row, then
    re-classifies each one against the corpus *with itself excluded*.
    Disagreements are either Vision misclassifications worth noting
    OR audit mistakes the user might want to revisit.
    """
    from sqlmodel import Session

    from ..data.db import init_db, make_engine
    from ..roster.promo_tournament_doll_vision import DollVisionMatcher
    from ..data.models import PromoExtractedField, PromoMatchScreenshot
    from ..roster.promo_tournament_regions import PLAYER_LOADOUT
    from PIL import Image
    from sqlmodel import select as _sel

    bbox_by_slug = {
        r.slug: r.bbox for r in PLAYER_LOADOUT if r.slug.endswith(".doll")
    }
    engine = make_engine(db)
    init_db(engine)
    with Session(engine) as session:
        matcher = DollVisionMatcher.from_session(session)
        if len(matcher) == 0:
            console.print(
                "[red]No manually-corrected corpus found.[/] Audit some "
                "doll rows via /audit/dolls first."
            )
            raise typer.Exit(code=1)
        console.print(
            f"[bold]Corpus size:[/] {len(matcher)} rows · K={k}"
        )

        rows = session.exec(
            _sel(PromoExtractedField).where(
                PromoExtractedField.region_slug.like("%.doll"),
                PromoExtractedField.manually_corrected == True,  # noqa: E712
            )
        ).all()
        shot_ids = list({r.screenshot_id for r in rows})
        shots = session.exec(
            _sel(PromoMatchScreenshot).where(
                PromoMatchScreenshot.id.in_(shot_ids)
            )
        ).all()
        shot_by_id = {s.id: s for s in shots}
        images: dict[int, Image.Image] = {}

        disagreements: list[tuple[PromoExtractedField, str, float, int]] = []
        for row in rows:
            shot = shot_by_id.get(row.screenshot_id)
            if shot is None:
                continue
            bbox = bbox_by_slug.get(row.region_slug)
            if bbox is None:
                continue
            img = images.get(shot.id)
            if img is None:
                try:
                    img = Image.open(shot.file_path).convert("RGB")
                except OSError:
                    continue
                images[shot.id] = img
            crop = img.crop(bbox)
            result = matcher.match(crop, k=k, exclude_field_id=row.id)
            if result is None or result.canonical_key == row.normalized:
                continue
            disagreements.append((row, result.canonical_key, result.distance, result.n_voting))

    if not disagreements:
        console.print("[bold green]No disagreements.[/] Vision agrees with every human label.")
        return
    console.print(
        f"[bold yellow]{len(disagreements)} disagreement(s)[/] (Vision vs. human label):"
    )
    console.print(
        f"  {'field_id':>9s}  {'human':18s}  {'vision':18s}  {'votes':>5s}  {'mean_dist':>9s}"
    )
    for row, vision_class, dist, n_voting in disagreements:
        console.print(
            f"  {row.id:>9d}  {row.normalized or '(none)':18s}  "
            f"{vision_class:18s}  {n_voting:>3d}/{k}  {dist:>9.2f}"
        )


@app.command(name="migrate-lb-core-format")
def migrate_lb_core_format(
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path"),
) -> None:
    """Rewrite legacy ``%.lb_core`` ``normalized`` values to canonical class keys.

    Phase-2 emitted structured strings like ``"3,7"`` / ``"3,0"`` / ``"1"``.
    The audit page expects ``normalized`` to double as the class key
    (``"mlb_max"`` / ``"mlb_c0"`` / ``"lb1"``). This is a one-shot
    migration — pure ORM updates, no image re-OCR. Idempotent: rows
    already in the new format are detected and skipped.
    """
    from sqlmodel import Session, select

    from ..data.db import init_db, make_engine
    from ..data.models import PromoExtractedField
    from ..roster.promo_tournament_lb_core_audit import (
        AUDIT_KEYS,
        OLD_TO_NEW_NORMALIZED,
    )

    engine = make_engine(db)
    init_db(engine)
    audit_keys = set(AUDIT_KEYS)
    examined = 0
    updated = 0
    skipped_unknown = 0
    with Session(engine) as session:
        rows = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.region_slug.like("%.lb_core")
            )
        ).all()
        for row in rows:
            examined += 1
            cur = row.normalized
            if cur in audit_keys:
                continue  # already migrated
            new = OLD_TO_NEW_NORMALIZED.get(cur)
            if new is None:
                skipped_unknown += 1
                continue
            row.normalized = new
            session.add(row)
            updated += 1
        session.commit()
    console.print(
        f"[bold green]Migration complete[/]: examined={examined} "
        f"updated={updated} skipped_unknown={skipped_unknown}"
    )


@app.command(name="backfill-extractions")
def backfill_extractions(
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path"),
) -> None:
    """Run extraction for region slugs missing on already-ingested screenshots.

    Idempotent. Use after adding new region types (e.g. Phase 2.x
    slices like ``char{N}.lb_core``) to populate them on existing data
    without paying the cost of a full ``ingest-tournaments --force-ocr``.
    Non-destructive: never rewrites rows that already exist.
    """
    from ..data.db import init_db, make_engine
    from ..roster.promo_tournament_ingest import run_backfill_pass

    engine = make_engine(db)
    init_db(engine)
    stats = run_backfill_pass(engine)
    console.print(f"[bold green]Backfill complete[/]: {stats}")
    if stats.errors:
        console.print("[red]Errors:[/]")
        for err in stats.errors:
            console.print(f"  · {err}")


@app.command(name="rematch-tournament-characters")
def rematch_tournament_characters(
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path"),
) -> None:
    """Re-run character matching on every stored tournament name extraction.

    Fast (no PaddleOCR re-run): walks every ``*.name`` row in
    ``PromoExtractedField``, scores the existing OCR ``text`` against
    the current ``Character`` DB with the current matcher, and updates
    ``character_id`` + ``character_match_score`` in place. Use after
    changing ``match_character()`` to repair existing data without
    paying the cost of a full ``ingest-tournaments --force-ocr``.
    """
    from sqlmodel import Session

    from ..data.db import init_db, make_engine
    from ..roster.promo_tournament_ocr import rematch_character_fields

    engine = make_engine(db)
    init_db(engine)
    with Session(engine) as session:
        examined, updated = rematch_character_fields(session)
    console.print(
        f"[bold green]Rematch complete[/]: examined={examined} updated={updated}"
    )


@app.command(name="pick-coords")
def pick_coords(
    image: Optional[Path] = typer.Argument(
        None,
        help="Optional path to an image to load at startup (otherwise drag-drop into the window).",
    ),
) -> None:
    """Visual coord-picker — drop image, click 2 corners, save crop + masked PNG.

    Sister to ``crop-tool``. Where ``crop-tool`` writes fractional region
    constants for the codebase's runtime crop boxes, this writes
    *absolute pixel* outputs alongside the source image:

      ``<stem>__x1_y1_x2_y2__crop.png``    just the selected region
      ``<stem>__x1_y1_x2_y2__masked.png``  full size, rest blacked out

    Coordinates ``(x1, y1, x2, y2)`` also land on the clipboard. Built
    on PySide6 — supports trackpad pinch-zoom and drag-pan.
    """
    from ..tools.coord_picker import run

    if image is not None and not image.is_file():
        console.print(f"[red]Image not found:[/] {image}")
        raise typer.Exit(code=1)
    raise typer.Exit(code=run(image))


@app.command()
def ga(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    role: str = typer.Option("attack", help="attack | defense | balanced"),
    top_k: int = typer.Option(5, help="Top-K teams to surface"),
    pop_size: int = typer.Option(100, help="GA population size"),
    generations: int = typer.Option(50, help="GA generations"),
    min_power: int = typer.Option(100_000, help="Minimum power for pool"),
    seed: Optional[int] = typer.Option(None, help="Seed for reproducibility"),
    compare: bool = typer.Option(
        True, "--compare/--no-compare",
        help="Also run beam search and show team-set difference",
    ),
) -> None:
    """Phase 4 feasibility — run a genetic-algorithm team search.

    Compares against the beam-search heuristic (same pool + weights)
    to surface compositions GA finds that the heuristic missed.
    """
    from ..optimizer.genetic import genetic_search
    from ..optimizer.loader import filter_eligible, load_owned
    from ..optimizer.constraints import effective_min_skill_sum
    from ..optimizer.scoring import (
        ATTACK_WEIGHTS, BALANCED_WEIGHTS, DEFENSE_WEIGHTS,
    )
    from ..optimizer.search import beam_search_top_teams

    weights_for = {
        "attack": ATTACK_WEIGHTS,
        "defense": DEFENSE_WEIGHTS,
        "balanced": BALANCED_WEIGHTS,
    }
    weights = weights_for.get(role, ATTACK_WEIGHTS)

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        owned = load_owned(session)
    pool = filter_eligible(
        owned, min_power=min_power, min_skill_sum=effective_min_skill_sum()
    )
    console.print(
        f"[bold]GA team search[/] — pool={len(pool)}, pop={pop_size}, "
        f"gens={generations}, role={role}, seed={seed}"
    )
    if len(pool) < 5:
        console.print("[red]Eligible pool too small (< 5).[/]")
        return

    result = genetic_search(
        pool,
        weights=weights,
        population_size=pop_size,
        generations=generations,
        top_k=top_k,
        seed=seed,
    )
    console.print(
        f"  Generations: {result.generations_run}, "
        f"unique-final: {result.final_population_unique_compositions}, "
        f"best-trace start→end: "
        f"{result.best_score_per_generation[0]:.2f} → "
        f"{result.best_score_per_generation[-1]:.2f}"
        if result.best_score_per_generation else
        "  (no convergence trace — population didn't initialize)"
    )

    table = Table(title=f"GA top-{top_k}")
    table.add_column("#")
    table.add_column("Score")
    table.add_column("Members", overflow="fold")
    for i, t in enumerate(result.teams, 1):
        table.add_row(
            str(i), f"{t.score:.2f}",
            ", ".join(m.name for m in t.members),
        )
    console.print(table)

    if compare and result.teams:
        beam_teams = beam_search_top_teams(
            pool, top_k=top_k, beam_width=200, weights=weights
        )
        ga_sets = {frozenset(m.name for m in t.members) for t in result.teams}
        beam_sets = {frozenset(m.name for m in t.members) for t in beam_teams}
        ga_only = ga_sets - beam_sets
        beam_only = beam_sets - ga_sets
        shared = ga_sets & beam_sets
        console.print(
            f"\n[bold]Comparison vs beam search[/]: "
            f"shared={len(shared)}, GA-only={len(ga_only)}, beam-only={len(beam_only)}"
        )
        if ga_only:
            console.print("[bold]GA-only compositions:[/]")
            for s in ga_only:
                names = sorted(s)
                console.print(f"  · {', '.join(names)}")


@app.command()
def validate(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """Backtest the damage formula against tagged match outcomes.

    For every capture with both a tagged ``outcome`` and a complete
    user_team + opponent_team + role, runs the damage resolver and
    compares predicted win/loss to the actual. Reports accuracy,
    confusion matrix, and mean clear-time error. Mirrors the
    ``/validate`` web route.
    """
    from ..data.models import ArenaMatch
    from ..simulator.damage import resolve_by_names

    engine = make_engine(db)
    init_db(engine)
    n_total = 0
    n_predictable = 0
    n_correct = 0
    confusion = {"true_pos": 0, "true_neg": 0, "false_pos": 0, "false_neg": 0}
    clear_time_errors: list[float] = []
    rows: list[dict] = []

    with get_session(engine) as session:
        captures = list(session.exec(select(ArenaMatch)).all())
    for cap in captures:
        if not cap.outcome:
            continue
        n_total += 1
        user = [n for n in (cap.user_team or []) if n]
        opp = [n for n in (cap.opponent_team or []) if n]
        if len(user) != 5 or len(opp) != 5:
            continue
        if cap.user_role == "attack":
            attacker, defender = user, opp
        elif cap.user_role == "defense":
            attacker, defender = opp, user
        else:
            continue
        try:
            r = resolve_by_names(attacker, defender)
        except Exception:
            r = None
        if r is None:
            continue
        n_predictable += 1
        if cap.user_role == "attack":
            user_predicted_win = r.attacker_wins_within_5min
        else:
            user_predicted_win = not r.attacker_wins_within_5min
        user_actual_win = cap.outcome == "win"
        correct = user_predicted_win == user_actual_win
        if correct:
            n_correct += 1
        if user_predicted_win and user_actual_win:
            confusion["true_pos"] += 1
        elif (not user_predicted_win) and (not user_actual_win):
            confusion["true_neg"] += 1
        elif user_predicted_win:
            confusion["false_pos"] += 1
        else:
            confusion["false_neg"] += 1
        actual = (cap.raw_battle_record or {}).get("seconds_to_clear")
        if actual is not None:
            clear_time_errors.append(abs(r.seconds_to_clear_defender - float(actual)))
        rows.append({
            "id": cap.id, "mode": cap.mode, "role": cap.user_role,
            "predicted": "win" if user_predicted_win else "loss",
            "actual": cap.outcome, "correct": correct,
        })

    console.print(f"[bold]Damage formula validation[/]")
    console.print(
        f"  Tagged captures: {n_total}, predictable (full teams + role): "
        f"{n_predictable}"
    )
    if n_predictable == 0:
        console.print(
            "[yellow]No predictable captures yet. Tag outcomes via the "
            "capture detail page (set outcome + user_role) and re-run.[/]"
        )
        return
    accuracy = n_correct / n_predictable
    console.print(
        f"  Accuracy: [bold]{accuracy * 100:.0f}%[/] "
        f"({n_correct}/{n_predictable})"
    )
    console.print(
        f"  Confusion: TP={confusion['true_pos']} "
        f"TN={confusion['true_neg']} "
        f"FP={confusion['false_pos']} "
        f"FN={confusion['false_neg']}"
    )
    if clear_time_errors:
        mean_err = sum(clear_time_errors) / len(clear_time_errors)
        console.print(
            f"  Mean clear-time error: {mean_err:.0f}s "
            f"({len(clear_time_errors)} samples)"
        )
    if rows:
        table = Table(title="Per-capture detail")
        table.add_column("ID")
        table.add_column("Mode")
        table.add_column("Role")
        table.add_column("Predicted")
        table.add_column("Actual")
        table.add_column("Correct?")
        for r in rows:
            table.add_row(
                str(r["id"]), r["mode"], r["role"] or "?",
                r["predicted"], r["actual"],
                "[green]✓[/]" if r["correct"] else "[red]✗[/]",
            )
        console.print(table)


@app.command("synergy-audit")
def synergy_audit_cmd() -> None:
    """List encoded characters by their synergy-table coverage.

    Surfaces under-represented characters (0 or 1 synergy pairs) so the
    maintainer can decide which pairings to add to ``SYNERGY_PAIRS`` in
    ``scoring.py``. The optimizer never credits a team for a synergy
    that's not in the table — so missing entries silently devalue
    teams that include the affected character.
    """
    from ..optimizer.scoring import SYNERGY_PAIRS
    from ..optimizer.synergy_audit import audit_synergy_coverage
    from ..simulator.registry import all_encoded_names

    encoded = all_encoded_names()
    report = audit_synergy_coverage(encoded, SYNERGY_PAIRS)
    console.print(
        f"[bold]Synergy coverage[/]: "
        f"{len(encoded)} encoded characters, "
        f"{len(SYNERGY_PAIRS)} synergy pairs"
    )
    console.print()
    for n, names in report.tiers_by_coverage.items():
        label = (
            "[red]uncovered[/]" if n == 0
            else "[yellow]1 pair only[/]" if n == 1
            else f"{n} pairs"
        )
        console.print(f"[bold]{label}[/]: {len(names)} characters")
        if n <= 1:
            for name in names:
                console.print(f"    {name}")
    console.print()
    under = report.under_represented
    if under:
        console.print(
            f"[bold yellow]{len(under)} under-represented characters[/] "
            "(0 or 1 synergy pair). Consider adding meta-relevant "
            "pairings to SYNERGY_PAIRS for the ones you actually field."
        )


@app.command()
def snapshot(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    label: str = typer.Option("", help="Optional label appended to the filename"),
) -> None:
    """Save a snapshot of the current OwnedCharacter state to
    ``<user_data_dir>/snapshots/<timestamp>.json``.

    Snapshots also get taken automatically on CSV import. Use this
    command to capture state at any other moment (e.g., right before
    a major investment push) so the roster diff page can compare
    "before vs after" later.
    """
    from ..roster.snapshots import take_snapshot

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        path = take_snapshot(session, label=label)
    console.print(f"[bold green]Snapshot saved[/] {path}")


@app.command()
def snapshots(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """List all saved roster snapshots, oldest → newest."""
    from ..roster.snapshots import list_snapshots

    paths = list_snapshots()
    if not paths:
        console.print("[yellow]No snapshots saved yet.[/]")
        return
    for p in paths:
        console.print(f"  {p.name}")


@app.command("fetch-portraits")
def fetch_portraits(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    out_dir: Optional[Path] = typer.Option(None, help="Override portrait output dir"),
) -> None:
    """Download Prydwen portrait images for every character (used for arena matching)."""
    from ..data.scrapers.portraits import download_all

    counts = download_all(db_path=db, out_dir=out_dir)
    console.print(f"[bold green]Portraits fetched[/]: {counts}")


@app.command("fetch-roledata")
def fetch_roledata_cmd(
    target: Optional[str] = typer.Argument(
        None,
        help="resource_id (e.g. 'c500') or name_code to fetch a single character. "
             "Omit with --all to fetch every character in the id_map.",
    ),
    fetch_all: bool = typer.Option(
        False,
        "--all",
        help="Fetch every character listed in character_id_map.json.",
    ),
    lang: str = typer.Option("en", "--lang", help="Language code: en / ja / ko / zh-tw / etc."),
    rate: float = typer.Option(
        1.0,
        "--rate",
        help="Minimum seconds between page navigations (politeness throttle).",
    ),
    headed: bool = typer.Option(
        False,
        "--headed",
        help="Show the Chromium window (default: headless). Useful for debugging.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Bypass the on-disk cache and re-fetch.",
    ),
    out_dir: Optional[Path] = typer.Option(
        None,
        "--out-dir",
        help="Override cache directory (default: <user_data_dir>/blablalink/).",
    ),
) -> None:
    """Mirror BlablaLink character stat tables via a headless browser.

    BlablaLink's CDN URLs are content-hashed at runtime by their JS,
    so we run their page in headless Chromium and capture the JSON
    responses as they fly past. Cache lands at
    ``<user_data_dir>/blablalink/<lang>/roledata/``.

    Requires Playwright:

      pip install -e '.[scrape]' && playwright install chromium

    Examples:

      nikkeoptimizer fetch-roledata --all                     # full mirror
      nikkeoptimizer fetch-roledata c500                      # one character by id
      nikkeoptimizer fetch-roledata --all --lang ja --rate 2  # slower, in Japanese
    """
    from ..data.scrapers import blablalink

    if not fetch_all and target is None:
        console.print(
            "[red]Specify a target (e.g. 'c500') or pass [bold]--all[/].[/]"
        )
        raise typer.Exit(code=2)
    if fetch_all and target is not None:
        console.print("[red]Pass either a target or [bold]--all[/], not both.[/]")
        raise typer.Exit(code=2)

    cache = out_dir or blablalink.default_cache_dir()
    console.print(f"Cache: [dim]{cache}[/]")

    if fetch_all:
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeRemainingColumn,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        ) as progress:
            task_id = progress.add_task("fetching", total=None)

            def _on_progress(idx: int, total: int, rid: str) -> None:
                progress.update(
                    task_id, total=total, completed=idx, description=f"fetching {rid}"
                )

            stats = blablalink.fetch_all(
                lang=lang,
                rate_seconds=rate,
                headless=not headed,
                cache_dir=cache,
                force=force,
                progress=_on_progress,
            )
        console.print(
            f"[bold green]Done[/] — fetched: {stats.fetched}, "
            f"cached: {stats.cached}, errors: {stats.errors}"
        )
        if stats.error_ids:
            console.print(f"[yellow]missing/errored ids:[/] {', '.join(stats.error_ids)}")
        return

    assert target is not None
    data = blablalink.fetch_one(
        target,
        lang=lang,
        rate_seconds=rate,
        headless=not headed,
        cache_dir=cache,
        force=force,
    )
    if data is None:
        console.print(f"[red]No roledata for {target!r} (lang={lang}).[/]")
        raise typer.Exit(code=1)
    name = data.get("name_localkey") or data.get("name_code") or target
    console.print(f"[bold green]Saved[/] roledata for {name} ({target})")


@app.command("roledata-coverage")
def roledata_coverage_cmd(
    lang: str = typer.Option("en", "--lang", help="Language code of the cache."),
) -> None:
    """Compare cached BlablaLink stat tables against our simulator library.

    Shows three buckets:
      ✓ encoded + cached      (full coverage — simulator can use real stats)
      ⚠ encoded but NOT cached (need to run fetch-roledata for these)
      ⓘ cached but NOT encoded (BlablaLink has them; we haven't written DSL yet)
    """
    import json as _json

    from ..data.scrapers.blablalink import (
        cache_path_for_nikke_list,
        cache_path_for_roledata,
    )
    from ..simulator import registry

    nl_path = cache_path_for_nikke_list(lang)
    if not nl_path.is_file():
        console.print(
            f"[red]No nikke_list cached at[/] {nl_path}\n"
            "Run [bold]nikkeoptimizer fetch-roledata <anything>[/] first to populate it."
        )
        raise typer.Exit(code=1)
    nikke_list = _json.loads(nl_path.read_text())
    name_to_rid: dict[str, int] = {}
    for rec in nikke_list:
        nm = (rec.get("name_localkey") or {}).get("name")
        rid = rec.get("resource_id")
        if isinstance(nm, str) and rid is not None:
            name_to_rid[nm.lower()] = int(rid)

    encoded = registry.all_encoded_names()
    encoded_lower = {n.lower(): n for n in encoded}

    encoded_and_cached: list[tuple[str, int]] = []
    encoded_no_cache: list[tuple[str, int]] = []
    for lc, original in encoded_lower.items():
        rid = name_to_rid.get(lc)
        if rid is None:
            continue  # encoded but not in BlablaLink (mismatched name or unmapped)
        cached = cache_path_for_roledata(str(rid), lang).is_file()
        (encoded_and_cached if cached else encoded_no_cache).append((original, rid))

    encoded_no_match = [n for lc, n in encoded_lower.items() if lc not in name_to_rid]
    cached_not_encoded = []
    for lc, rid in name_to_rid.items():
        if lc in encoded_lower:
            continue
        if cache_path_for_roledata(str(rid), lang).is_file():
            cached_not_encoded.append((lc, rid))

    total_cached_files = sum(
        1 for rid in name_to_rid.values()
        if cache_path_for_roledata(str(rid), lang).is_file()
    )

    console.print(f"[bold]BlablaLink coverage[/] (lang={lang})")
    console.print(f"  nikke_list size:     {len(nikke_list)}")
    console.print(f"  roledata cached:     {total_cached_files}")
    console.print(f"  simulator encoded:   {len(encoded)}")
    console.print()
    console.print(
        f"  [green]✓ encoded + cached:[/]      {len(encoded_and_cached)}"
    )
    console.print(
        f"  [yellow]⚠ encoded, no cache:[/]    {len(encoded_no_cache)}"
    )
    console.print(
        f"  [dim]ⓘ cached, not encoded:[/]   {len(cached_not_encoded)}"
    )
    console.print(
        f"  [dim]· encoded, no name match:[/] {len(encoded_no_match)}"
    )
    if encoded_no_cache:
        console.print(
            "\n[yellow]Encoded but missing from cache:[/] "
            + ", ".join(f"{n}({r})" for n, r in encoded_no_cache[:20])
            + (f", … (+{len(encoded_no_cache)-20} more)" if len(encoded_no_cache) > 20 else "")
        )
    if encoded_no_match:
        console.print(
            "\n[dim]Encoded but no BlablaLink name match (likely a Treasure or "
            "non-canonical name):[/] " + ", ".join(encoded_no_match[:15])
            + (f", … (+{len(encoded_no_match)-15} more)" if len(encoded_no_match) > 15 else "")
        )


@app.command("set-research")
def set_research_cmd(
    synchro: Optional[int] = typer.Option(None, "--synchro", help="Synchro Level (account LV cap)"),
    general: Optional[int] = typer.Option(None, "--general", help="Recycle Room → General Research level"),
    attacker: Optional[int] = typer.Option(None, "--attacker", help="Attacker class research level"),
    defender: Optional[int] = typer.Option(None, "--defender", help="Defender class research level"),
    supporter: Optional[int] = typer.Option(None, "--supporter", help="Supporter class research level"),
    pilgrim: Optional[int] = typer.Option(None, "--pilgrim", help="Pilgrim manufacturer research level"),
    elysion: Optional[int] = typer.Option(None, "--elysion", help="Elysion manufacturer research level"),
    tetra: Optional[int] = typer.Option(None, "--tetra", help="Tetra manufacturer research level"),
    missilis: Optional[int] = typer.Option(None, "--missilis", help="Missilis manufacturer research level"),
    abnormal: Optional[int] = typer.Option(None, "--abnormal", help="Abnormal manufacturer research level"),
    show: bool = typer.Option(False, "--show", help="Just show current values without changes"),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """Set or view your account-wide Outpost research levels.

    These come from the in-game [Outpost Info] panel. Used by the
    optimizer to compute account-buff additions for stat predictions
    via the BlablaLink formula.

    Per-level rates (May 2026 observation):
      - General Research:    +450 HP / level
      - Class research:      +750 HP, +5 DEF / level
      - Manufacturer research: +25 ATK, +5 DEF / level

    Examples:

      nikkeoptimizer set-research --show
      nikkeoptimizer set-research --general 300 --attacker 179 --defender 172
      nikkeoptimizer set-research --synchro 654 --pilgrim 167 --elysion 169
    """
    from ..data.models import AccountState
    from ..simulator import account_buffs

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        state = account_buffs.get_or_default_state(session)
        if not show:
            for field, value in (
                ("synchro_level", synchro),
                ("general_research_level", general),
                ("class_attacker_level", attacker),
                ("class_defender_level", defender),
                ("class_supporter_level", supporter),
                ("mfr_pilgrim_level", pilgrim),
                ("mfr_elysion_level", elysion),
                ("mfr_tetra_level", tetra),
                ("mfr_missilis_level", missilis),
                ("mfr_abnormal_level", abnormal),
            ):
                if value is not None:
                    setattr(state, field, value)
            from datetime import datetime, timezone
            state.updated_at = datetime.now(timezone.utc)
            session.add(state)
            session.commit()
            session.refresh(state)

        table = Table(title="Outpost Research Levels", show_header=True)
        table.add_column("Field", style="dim")
        table.add_column("Level", justify="right")
        table.add_row("Synchro Level", str(state.synchro_level))
        table.add_row("General Research", str(state.general_research_level))
        table.add_row("Attacker", str(state.class_attacker_level))
        table.add_row("Defender", str(state.class_defender_level))
        table.add_row("Supporter", str(state.class_supporter_level))
        table.add_row("Pilgrim", str(state.mfr_pilgrim_level))
        table.add_row("Elysion", str(state.mfr_elysion_level))
        table.add_row("Tetra", str(state.mfr_tetra_level))
        table.add_row("Missilis", str(state.mfr_missilis_level))
        table.add_row("Abnormal", str(state.mfr_abnormal_level))
        console.print(table)


@app.command("set-username")
def set_username_cmd(
    name: str = typer.Argument(..., help="Your in-game NIKKE username"),
) -> None:
    """Persist your in-game username so CP cross-validation knows which
    side of a capture is yours. Saved to ``<user_data_dir>/config.json``.

    Equivalent to setting ``NIKKE_OPTIMIZER_USERNAME`` permanently — env
    var still wins if both are set.
    """
    from ..data.config import set_self_username

    path = set_self_username(name)
    console.print(f"[bold green]Saved username[/] {name!r} -> {path}")


@app.command("show-config")
def show_config_cmd() -> None:
    """Show the resolved self-username (env var or config file)."""
    from ..data.config import get_self_username

    name = get_self_username()
    if name:
        console.print(f"Self-username: [bold]{name}[/]")
    else:
        console.print(
            "[yellow]No self-username configured. "
            "Run [bold]nikkeoptimizer set-username <name>[/] to set one.[/]"
        )


@app.command()
def doctor(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """Self-diagnosis: report green/red status on every dependency.

    Checks: DB exists with characters + roster, portrait library found,
    self-username configured, optional deps importable. Exits 0 on full
    green, 1 if anything's missing.
    """
    from importlib import import_module

    from ..data.config import get_self_username
    from ..data.db import default_db_path, default_portrait_library_path
    from ..data.models import Character, Cube, OwnedCharacter
    from sqlmodel import select

    fail = False

    def ok(msg: str) -> None:
        console.print(f"  [green]✓[/] {msg}")

    def warn(msg: str) -> None:
        console.print(f"  [yellow]⚠[/] {msg}")

    def err(msg: str) -> None:
        nonlocal fail
        fail = True
        console.print(f"  [red]✗[/] {msg}")

    console.print("[bold]Database[/]")
    db_path = db or default_db_path()
    if not db_path.exists():
        err(f"DB not found at {db_path}")
    else:
        ok(f"DB at {db_path}")
        engine = make_engine(db_path)
        init_db(engine)
        with get_session(engine) as session:
            n_chars = len(session.exec(select(Character)).all())
            n_owned = len(session.exec(select(OwnedCharacter)).all())
            n_cubes = len(session.exec(select(Cube)).all())
        if n_chars >= 200:
            ok(f"{n_chars} characters in DB")
        elif n_chars > 0:
            warn(f"only {n_chars} characters — run `nikkeoptimizer refresh`")
        else:
            err("no characters — run `nikkeoptimizer refresh`")
        if n_owned > 0:
            ok(f"{n_owned} owned characters in roster")
        else:
            warn("no owned characters — run `nikkeoptimizer import-csv <path>`")
        if n_cubes > 0:
            ok(f"{n_cubes} cubes")
        else:
            warn("no cubes — run `nikkeoptimizer import-cubes <dir>`")

    console.print()
    console.print("[bold]Portrait library[/]")
    pl = default_portrait_library_path()
    if pl is None:
        warn(
            "no portrait library found — uploads will be disabled. "
            "Place .webp files at ~/Library/Application Support/NikkeOptimizer/portraits/"
        )
    else:
        n_files = len(list(pl.glob("*.webp")))
        if n_files >= 200:
            ok(f"{n_files} portraits at {pl}")
        else:
            warn(f"only {n_files} portraits at {pl} (expect ~335)")

    console.print()
    console.print("[bold]Configuration[/]")
    name = get_self_username()
    if name:
        ok(f"self-username = {name!r}")
    else:
        warn(
            "no self-username configured. "
            "Run `nikkeoptimizer detect-username --save` or `set-username <name>`"
        )

    console.print()
    console.print("[bold]Optional dependencies[/]")
    for module_name, label in [
        ("sqlmodel", "DB layer (sqlmodel)"),
        ("fastapi", "web UI (fastapi)"),
        ("Vision", "portrait matcher (pyobjc Vision)"),
        ("paddleocr", "screenshot OCR (paddleocr)"),
        ("PIL", "image handling (Pillow)"),
    ]:
        try:
            import_module(module_name)
            ok(label)
        except ImportError:
            warn(f"{label} — not installed (some features disabled)")

    console.print()
    if fail:
        console.print("[bold red]doctor: FAILED[/]")
        raise typer.Exit(code=1)
    console.print("[bold green]doctor: all checks passed[/]")


@app.command()
def advisor(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    role: str = typer.Option("attack", help="attack | defense | balanced"),
    top_k: int = typer.Option(5, help="Top-K teams to consider"),
    target_skill: int = typer.Option(7, help="Skill level to simulate upgrade to"),
    max_recs: int = typer.Option(10, help="Max recommendations to print"),
) -> None:
    """Suggest who to level up next.

    For each owned-but-undertrained Nikke, simulates upgrading her
    skills to ``target_skill`` and re-runs the optimizer. Ranks
    candidates by score lift across the top-K teams.
    """
    from ..optimizer.investment_advisor import recommend_investment
    from ..optimizer.scoring import ATTACK_WEIGHTS, BALANCED_WEIGHTS, DEFENSE_WEIGHTS

    weights_for = {
        "attack": ATTACK_WEIGHTS,
        "defense": DEFENSE_WEIGHTS,
        "balanced": BALANCED_WEIGHTS,
    }
    weights = weights_for.get(role, ATTACK_WEIGHTS)

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        recs = recommend_investment(
            session, weights=weights, top_k=top_k,
            target_skill=target_skill, max_recommendations=max_recs,
        )

    if not recs:
        console.print(
            "[muted]No recommendations — either every owned Nikke meets the "
            "investment floor, or upgrades don't push anyone into top-K.[/]"
        )
        return
    console.print(
        f"[bold]Top {len(recs)} investment ROI recommendations[/] "
        f"(role={role}, target skill {target_skill})"
    )
    for i, r in enumerate(recs, 1):
        console.print(
            f"  {i}. [bold]{r.name}[/] — "
            f"projected team score {r.projected_score_in_team:.1f}, "
            f"total lift {r.score_lift:+.1f}"
        )


@app.command("apply-consensus")
def apply_consensus_cmd(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    min_confident: int = typer.Option(
        2, help="Min captures that must agree on a (slot, character) to promote"
    ),
) -> None:
    """Apply multi-capture consensus across captured opponent teams.

    When the same opponent appears in 2+ captures with confident
    portrait matches at the same slot, promote borderline matches in
    OTHER captures of the same opponent to the consensus character.
    Complements the per-cell CP cross-validation (slice #60) which
    only handles the user's own team.
    """
    from ..roster.capture_consensus import apply_consensus

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        report = apply_consensus(session, min_confident_count=min_confident)
        session.commit()

    if not report:
        console.print(
            "[muted]No promotions — either captures lack confident matches "
            "or no opponent appears in 2+ captures.[/]"
        )
        return
    total = 0
    for opp, info in report.items():
        n_promoted = sum(len(v) for v in info["promoted_per_row"].values())
        total += n_promoted
        console.print(
            f"[bold]{opp}[/] ({info['captures_in_group']} captures): "
            f"{n_promoted} cell(s) promoted"
        )
    console.print(f"\n[bold green]Total promotions: {total}[/]")


@app.command("detect-username")
def detect_username_cmd(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    save: bool = typer.Option(False, "--save", help="Persist the detected username to config.json"),
) -> None:
    """Best-guess the user's in-game name from existing arena captures.

    Counts the most frequent ``user_username`` value across all captured
    ArenaMatch rows and prints the candidate. Pass ``--save`` to persist
    it (equivalent to ``set-username``).
    """
    from ..data.config import detect_self_username, set_self_username

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        result = detect_self_username(session)

    if result is None:
        console.print("[yellow]No captured user_username values found in DB.[/]")
        return
    name, count = result
    console.print(f"Detected username: [bold]{name}[/] ({count} captures)")
    if save:
        path = set_self_username(name)
        console.print(f"[bold green]Saved to[/] {path}")


@app.command()
def characters(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    limit: int = typer.Option(20, help="Max rows to display"),
    burst: Optional[str] = typer.Option(None, help="Filter by burst type: I, II, III, I/II/III"),
    element: Optional[str] = typer.Option(None, help="Filter by element"),
) -> None:
    """List characters currently in the local database."""
    engine = make_engine(db)
    init_db(engine)

    query = select(Character)
    if burst:
        query = query.where(Character.burst_type == burst)
    if element:
        query = query.where(Character.element == element)

    with get_session(engine) as session:
        rows = session.exec(query).all()

    table = Table(title=f"Characters ({len(rows)} matches)")
    table.add_column("Name")
    table.add_column("Rarity")
    table.add_column("Element")
    table.add_column("Weapon")
    table.add_column("Burst")
    table.add_column("Tags", overflow="fold")
    for c in sorted(rows, key=lambda r: r.name)[:limit]:
        table.add_row(
            c.name,
            c.rarity.value,
            c.element.value,
            c.weapon_class.value,
            c.burst_type.value,
            ", ".join(c.role_tags or []),
        )
    console.print(table)
    if len(rows) > limit:
        console.print(f"... showing first {limit} of {len(rows)}")


@app.command("diff-csv")
def diff_csv_cmd(
    csv_path: Path = typer.Argument(..., help="Path to the CSV to diff against the DB"),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    show_unchanged: bool = typer.Option(
        False, "--show-unchanged", help="Also list characters with no field changes"
    ),
    power_drop_threshold: int = typer.Option(
        50_000,
        "--power-drop-threshold",
        help="Flag characters whose Power dropped by ≥ this amount (likely ungeared)",
    ),
) -> None:
    """Show the diff between a CSV file and the current DB without writing.

    Useful before re-importing — surfaces:
      - Characters whose stats changed (especially significant Power drops
        that may indicate gear loss or unequipped Nikkes)
      - Characters present in the CSV but missing from the DB (new pulls)
      - Characters present in the DB but missing from the CSV
      - The detected CSV format version (v1 vs v2)
    """
    from ..roster.csv_importer import dry_run_diff

    report = dry_run_diff(csv_path, db_path=db)

    console.print(f"[bold]CSV format detected:[/] {report.format_version}")
    console.print(f"  rows in CSV:   {report.rows}")
    console.print(f"  matched:       {report.matched}")
    console.print(f"  unmatched:     {len(report.unmatched)}")
    console.print(f"  in DB only:    {len(report.db_only)}")
    if report.unmatched:
        console.print(f"\n[yellow]Unmatched names (no DB Character row):[/]")
        for n in report.unmatched[:30]:
            console.print(f"  - {n}")
    if report.db_only:
        console.print(f"\n[dim]In DB but not CSV (will be untouched on import):[/]")
        for n in report.db_only[:30]:
            console.print(f"  - {n}")
    if report.fuzzy_warnings:
        console.print(f"\n[dim]Fuzzy/alias name matches:[/]")
        for w in report.fuzzy_warnings[:15]:
            console.print(f"  {w}")

    drops = report.with_significant_power_drop(threshold=power_drop_threshold)
    stripped = [d for d in drops if d.looks_stripped]
    uninvested = [d for d in drops if d.looks_uninvested and not d.looks_stripped]
    other_drops = [d for d in drops if not d.looks_stripped and not d.looks_uninvested]

    if stripped:
        stripped.sort(key=lambda d: d.power_delta or 0)
        t = Table(
            title="⚠ STRIPPED — was MLB+invested, now low Power (verify gear loss!)",
            show_header=True,
            header_style="red",
        )
        t.add_column("Character"); t.add_column("Power Δ", justify="right")
        t.add_column("From → To", justify="right")
        for d in stripped:
            curp = d.changes.get("power", (None, None))[0] or 0
            newp = d.changes.get("power", (None, None))[1] or 0
            t.add_row(d.name, f"{d.power_delta:+,}", f"{curp:,} → {newp:,}")
        console.print(); console.print(t)

    if other_drops:
        other_drops.sort(key=lambda d: d.power_delta or 0)
        t = Table(title=f"⚠ Power drops worth a second look", show_header=True)
        t.add_column("Character"); t.add_column("Power Δ", justify="right")
        t.add_column("From → To", justify="right"); t.add_column("New LB")
        for d in other_drops:
            curp = d.changes.get("power", (None, None))[0] or 0
            newp = d.changes.get("power", (None, None))[1] or 0
            new_lb = d.changes.get("limit_break", (None, None))[1]
            t.add_row(d.name, f"{d.power_delta:+,}", f"{curp:,} → {newp:,}", str(new_lb))
        console.print(); console.print(t)

    if uninvested:
        console.print(
            f"\n[dim]ℹ {len(uninvested)} characters dropped to baseline Power "
            f"(uninvested in your roster — old DB had stale values, this is just a "
            f"correction):[/]"
        )
        names = [d.name for d in uninvested[:8]]
        console.print(f"  {', '.join(names)}" + (
            f", … (+{len(uninvested) - 8} more)" if len(uninvested) > 8 else ""
        ))

    new_chars = [d for d in report.diffs if d.is_new]
    if new_chars:
        console.print(f"\n[bold green]New characters in CSV:[/] {len(new_chars)}")
        for d in new_chars[:30]:
            console.print(f"  + {d.name}")

    changed = [d for d in report.diffs if d.changes and not d.is_new]
    if changed or show_unchanged:
        console.print(f"\n[bold]Per-character field changes:[/] {len(changed)}")
        for d in (report.diffs if show_unchanged else changed):
            if not d.changes and not show_unchanged:
                continue
            line = f"  {d.name}"
            if d.changes:
                items = ", ".join(
                    f"{k}: {v[0]!r}→{v[1]!r}"
                    for k, v in list(d.changes.items())[:5]
                )
                if len(d.changes) > 5:
                    items += f", … (+{len(d.changes) - 5} more)"
                line += f"  [{items}]"
            console.print(line)


@app.command("import-csv")
def import_csv_cmd(
    csv_file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """Import a roster CSV (per-character data including OL gear + cubes)."""
    from ..roster.csv_importer import import_csv

    report = import_csv(csv_file, db_path=db)
    console.print(f"[bold green]Import complete[/]")
    console.print(report.to_dict())


@app.command("snapshot-roster")
def snapshot_roster_cmd(
    season: int = typer.Option(..., "--season", help="Beta season number, e.g. 29."),
    player: str = typer.Option(
        ..., "--player",
        help="Player username (your own name or another player's tag).",
    ),
    csv_file: Optional[Path] = typer.Option(
        None, "--csv",
        help="CSV path. Omit to snapshot your own current OwnedCharacter + AccountState.",
        exists=True, dir_okay=False, readable=True,
    ),
    label: Optional[str] = typer.Option(None, "--label", help="Optional human-readable note."),
    # Account-level overrides (required when --csv is given; CSVs have no account row).
    synchro_level: Optional[int] = typer.Option(None, "--synchro-level"),
    general: Optional[int] = typer.Option(None, "--research-general"),
    attacker: Optional[int] = typer.Option(None, "--research-attacker"),
    defender: Optional[int] = typer.Option(None, "--research-defender"),
    supporter: Optional[int] = typer.Option(None, "--research-supporter"),
    pilgrim: Optional[int] = typer.Option(None, "--research-pilgrim"),
    elysion: Optional[int] = typer.Option(None, "--research-elysion"),
    tetra: Optional[int] = typer.Option(None, "--research-tetra"),
    missilis: Optional[int] = typer.Option(None, "--research-missilis"),
    abnormal: Optional[int] = typer.Option(None, "--research-abnormal"),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """Snapshot a player's roster against a beta season.

    Without ``--csv``: snapshot the user's own roster from the live
    OwnedCharacter table + AccountState singleton.

    With ``--csv``: import another player's roster CSV (their drawn
    character data) plus the account-level fields you pass via the
    ``--research-*`` and ``--synchro-level`` options. Idempotent —
    re-running for the same ``(season, player)`` replaces the prior
    snapshot.
    """
    from ..roster.snapshot import import_snapshot_csv, make_self_snapshot

    research_overrides = {
        "synchro_level": synchro_level,
        "general_research_level": general,
        "class_attacker_level": attacker,
        "class_defender_level": defender,
        "class_supporter_level": supporter,
        "mfr_pilgrim_level": pilgrim,
        "mfr_elysion_level": elysion,
        "mfr_tetra_level": tetra,
        "mfr_missilis_level": missilis,
        "mfr_abnormal_level": abnormal,
    }
    research_overrides = {k: v for k, v in research_overrides.items() if v is not None}

    if csv_file is not None:
        if not research_overrides:
            console.print(
                "[yellow]No --research-* / --synchro-level passed.[/] "
                "Account-wide research will default to 0 in the snapshot."
            )
        report = import_snapshot_csv(
            csv_path=csv_file,
            season_number=season,
            player_username=player,
            research=research_overrides,
            label=label,
            db_path=db,
        )
    else:
        if research_overrides:
            console.print(
                "[yellow]--research-* / --synchro-level options ignored.[/] "
                "Self-snapshot pulls from the live AccountState singleton."
            )
        report = make_self_snapshot(
            season_number=season,
            player_username=player,
            label=label,
            db_path=db,
        )

    console.print(f"[bold green]Snapshot saved[/]: {report.to_dict()}")
    if report.warnings:
        for warning in report.warnings[:10]:
            console.print(f"  · {warning}")
        if len(report.warnings) > 10:
            console.print(f"  · … (+{len(report.warnings) - 10} more)")


@app.command()
def roster(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    limit: int = typer.Option(20, help="Max rows to display"),
) -> None:
    """List the owned characters currently persisted."""
    from ..data.models import Cube, OwnedCharacter

    engine = make_engine(db)
    init_db(engine)
    table = Table(title="Owned characters")
    table.add_column("Name")
    table.add_column("Pow", justify="right")
    table.add_column("Sync", justify="right")
    table.add_column("Skills")
    table.add_column("Battle Cube")
    table.add_column("Arena Cube")
    with get_session(engine) as session:
        rows = list(session.exec(select(OwnedCharacter)).all())
        rows.sort(key=lambda r: -(r.power or 0))
        total = len(rows)
        for o in rows[:limit]:
            char_name = o.character.name
            bc = session.get(Cube, o.battle_cube_id) if o.battle_cube_id else None
            ac = session.get(Cube, o.arena_cube_id) if o.arena_cube_id else None
            table.add_row(
                char_name,
                str(o.power or "-"),
                str(o.sync_level or "-"),
                f"{o.skill1_level}/{o.skill2_level}/{o.burst_skill_level}",
                bc.name if bc else "-",
                ac.name if ac else "-",
            )
    table.title = f"Owned characters ({total})"
    console.print(table)
    if total > limit:
        console.print(f"... showing first {limit} of {total}")


@app.command("import-cubes")
def import_cubes_cmd(
    directory: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    require_complete: bool = typer.Option(
        False,
        "--require-complete",
        help="Skip cubes whose OCR extraction is incomplete instead of saving stubs",
    ),
) -> None:
    """OCR every cube screenshot in a directory and upsert into the DB."""
    from ..roster.cube_importer import import_cubes

    report = import_cubes(directory, db_path=db, require_complete=require_complete)
    console.print(f"[bold]Cube import:[/] {report.to_dict()}")
    if report.extractions:
        table = Table(title="Cubes")
        table.add_column("Name")
        table.add_column("Lv", justify="right")
        table.add_column("ATK", justify="right")
        table.add_column("HP", justify="right")
        table.add_column("DEF", justify="right")
        table.add_column("Equip")
        table.add_column("OK?")
        for e in report.extractions:
            table.add_row(
                e.name or "?",
                str(e.level or "-"),
                str(e.atk or "-"),
                str(e.hp or "-"),
                str(e.def_ or "-"),
                f"{e.equipping_count_equipped}/{e.equipping_count_owned}",
                "✓" if e.is_complete else "[yellow]partial[/]",
            )
        console.print(table)


@app.command("cubes")
def cubes_cmd(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """List the cubes currently persisted."""
    from ..data.models import Cube

    engine = make_engine(db)
    init_db(engine)
    table = Table(title="Cubes")
    table.add_column("Name")
    table.add_column("Lv", justify="right")
    table.add_column("ATK", justify="right")
    table.add_column("HP", justify="right")
    table.add_column("DEF", justify="right")
    table.add_column("Equip")
    with get_session(engine) as session:
        rows = list(session.exec(select(Cube)).all())
        rows.sort(key=lambda c: (-(c.level or 0), c.name))
        for c in rows:
            table.add_row(
                c.name,
                str(c.level or "-"),
                str(c.atk or "-"),
                str(c.hp or "-"),
                str(c.def_ or "-"),
                f"{c.equipping_count_equipped or 0}/{c.equipping_count_owned or 0}",
            )
    console.print(table)


@app.command("ingest")
def ingest_cmd(
    directory: Path = typer.Argument(..., exists=True),
    library_dir: Optional[Path] = typer.Option(
        None, "--library", help="Path to labeled Portrait_library/ (required for arena)"
    ),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    user_username: str = typer.Option("NIKA", help="Your in-game username"),
    classify_only: bool = typer.Option(
        False,
        "--dry-run",
        help="Classify each file without running any importer",
    ),
) -> None:
    """Walk a directory and auto-route every file to the right importer.

    Detects CSV / cube detail / arena pre-battle / Champion Arena Info and
    dispatches to the matching importer. With ``--dry-run`` only the per-file
    classification is reported (no DB writes).
    """
    from ..roster.screenshot_router import ingest_directory

    report = ingest_directory(
        directory,
        library_dir=library_dir,
        db_path=db,
        user_username=user_username,
        classify_only=classify_only,
    )
    console.print(f"[bold]Ingest:[/] {report.to_dict()}")
    if classify_only:
        table = Table(title="File classification")
        table.add_column("Type")
        table.add_column("Path", overflow="fold")
        for path, cls in sorted(report.classifications.items()):
            style = "green" if cls != "unknown" else "yellow"
            table.add_row(f"[{style}]{cls}[/]", path)
        console.print(table)


@app.command("import-arena")
def import_arena_cmd(
    directory: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    library_dir: Path = typer.Option(
        ..., "--library", help="Path to labeled Portrait_library/"
    ),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    user_username: str = typer.Option("NIKA", help="Your in-game username"),
) -> None:
    """OCR every arena screenshot in a directory and persist to the DB."""
    from ..roster.arena_importer import import_arena_directory
    from ..roster.portrait_matcher import PortraitMatcher

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        matcher = PortraitMatcher.from_portrait_library(library_dir, session=session)
    console.print(f"matcher indexed {len(matcher)} portraits")

    report = import_arena_directory(
        directory, matcher, db_path=db, user_username=user_username
    )
    console.print(f"[bold]Arena import:[/] {report.to_dict()}")


@app.command("arena-captures")
def arena_captures_cmd(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    review_only: bool = typer.Option(
        False, "--review-only", help="Only show captures flagged for review"
    ),
) -> None:
    """List the arena captures persisted in the DB."""
    from ..data.models import ArenaMatch

    engine = make_engine(db)
    init_db(engine)
    table = Table(title="Arena captures")
    table.add_column("ID", justify="right")
    table.add_column("Mode")
    table.add_column("User")
    table.add_column("Opponent")
    table.add_column("User team", overflow="fold")
    table.add_column("Opp team", overflow="fold")
    table.add_column("Review?")
    with get_session(engine) as session:
        query = select(ArenaMatch)
        if review_only:
            query = query.where(ArenaMatch.needs_review == True)  # noqa: E712
        rows = list(session.exec(query).all())
        rows.sort(key=lambda r: r.id or 0)
        for r in rows:
            table.add_row(
                str(r.id),
                r.mode,
                r.user_username or "-",
                r.opponent_username or "-",
                ", ".join(c or "?" for c in (r.user_team or [])),
                ", ".join(c or "?" for c in (r.opponent_team or [])),
                "[yellow]yes[/]" if r.needs_review else "no",
            )
    console.print(table)


@app.command("portrait-library")
def portrait_library_cmd(
    library_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """Inventory a labeled portrait library and report DB-name resolution."""
    from ..roster.portrait_library import resolve_library_from_session, summarize

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        entries = resolve_library_from_session(library_dir, session)
    summary = summarize(entries)

    console.print(f"[bold]Portrait library:[/] {library_dir}")
    console.print(f"  total files:        {summary['total']}")
    console.print(f"  unique characters:  {summary['unique_characters']}")
    console.print(f"  exact name match:   {summary['exact']}")
    console.print(f"  colon-insert match: {summary['colon-insert']}")
    console.print(f"  alias match:        {summary['alias']}")
    console.print(f"  fuzzy match:        {summary['fuzzy']}")
    console.print(f"  unresolved:         {summary['unresolved']}")
    if summary["unresolved"]:
        console.print("\n[yellow]Unresolved files (need manual aliases):[/]")
        for e in entries:
            if e.resolution == "unresolved":
                console.print(f"  - {e.file_path.name}")


@app.command("inspect-arena")
def inspect_arena_cmd(
    screenshot: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    library_dir: Path = typer.Option(
        ..., "--library", help="Path to labeled Portrait_library/"
    ),
    out_dir: Path = typer.Option(
        Path("/tmp/arena_dbg"), "--out", help="Where to save debug crops"
    ),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    mode: str = typer.Option(
        "auto",
        help="Force extractor mode: rookie/special/champion/auto",
    ),
) -> None:
    """Run the arena extractor on a screenshot and dump everything for inspection.

    Saves the team-strip + per-cell + per-portrait crops, then prints the
    matcher's top candidate per cell with distance — used to iterate on the
    proportional region geometry.
    """
    from PIL import Image

    from ..roster.arena import (
        _PREBATTLE_REGIONS,
        _ARENA_INFO_REGIONS,
        _crop_grid_cells,
        _crop_proportional,
        detect_title,
        extract_champion_arena_info,
        extract_pre_battle,
    )
    from ..roster.portrait_matcher import PortraitMatcher

    out_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(screenshot).convert("RGB")
    detected_mode, title_lines = detect_title(image)
    effective_mode = mode if mode != "auto" else detected_mode
    console.print(f"detected mode: [bold]{detected_mode}[/]  effective: [bold]{effective_mode}[/]")
    console.print(f"title lines: {title_lines[:6]}")

    if effective_mode in ("rookie", "special"):
        regions = _PREBATTLE_REGIONS
    elif effective_mode == "champion":
        regions = _ARENA_INFO_REGIONS
    else:
        console.print("[red]unsupported mode for inspect-arena[/]")
        raise typer.Exit(1)

    for name, box in regions.items():
        crop = _crop_proportional(image, box)
        crop.save(out_dir / f"{name}.png")

    from ..roster.arena import _PORTRAIT_BOX_PREBATTLE, _PORTRAIT_BOX_CHAMPION

    if effective_mode in ("rookie", "special"):
        for strip in ("top_team_strip", "bottom_team_strip"):
            team_img = _crop_proportional(image, regions[strip])
            for i, cell in enumerate(_crop_grid_cells(team_img, cols=5)):
                cell.save(out_dir / f"{strip}_cell_{i}.png")
                cw, ch = cell.size
                px1, py1, px2, py2 = _PORTRAIT_BOX_PREBATTLE
                portrait = cell.crop(
                    (int(cw * px1), int(ch * py1), int(cw * px2), int(ch * py2))
                )
                portrait.save(out_dir / f"{strip}_portrait_{i}.png")
    elif effective_mode == "champion":
        team_img = _crop_proportional(image, regions["team_strip"])
        for i, cell in enumerate(_crop_grid_cells(team_img, cols=5)):
            cell.save(out_dir / f"team_cell_{i}.png")
            cw, ch = cell.size
            px1, py1, px2, py2 = _PORTRAIT_BOX_CHAMPION
            portrait = cell.crop(
                (int(cw * px1), int(ch * py1), int(cw * px2), int(ch * py2))
            )
            portrait.save(out_dir / f"team_portrait_{i}.png")

    console.print(f"saved crops to: [bold]{out_dir}[/]")

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        matcher = PortraitMatcher.from_portrait_library(library_dir, session=session)
    console.print(f"matcher indexed {len(matcher)} embeddings\n")

    if effective_mode in ("rookie", "special"):
        result = extract_pre_battle(screenshot, matcher, user_username="NIKA")
        if result is None:
            console.print("[red]extract_pre_battle returned None[/]")
            return
        for label, team in (("USER", result.user_team), ("OPPONENT", result.opponent_team)):
            console.print(f"[bold]{label}[/] {team.player_username} power={team.power}")
            for c, b, d in zip(team.characters, team.best_matches, team.portrait_distances):
                style = "green" if c else "yellow"
                console.print(f"  [{style}]confident={c}  best={b}  d={d}[/]")
    else:
        result = extract_champion_arena_info(screenshot, matcher)
        if result is None:
            console.print("[red]extract_champion_arena_info returned None[/]")
            return
        console.print(
            f"player={result.player_username} round={result.round_index} power={result.total_power}"
        )
        for c, b, d in zip(
            result.team.characters,
            result.team.best_matches,
            result.team.portrait_distances,
        ):
            style = "green" if c else "yellow"
            console.print(f"  [{style}]confident={c}  best={b}  d={d}[/]")


@app.command()
def web(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    library_dir: Optional[Path] = typer.Option(
        None,
        "--library",
        help=(
            "Path to labeled Portrait_library/. "
            "If omitted, auto-discovers from $NIKKE_OPTIMIZER_PORTRAITS or "
            "<user_data_dir>/portraits/."
        ),
    ),
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8765, help="Bind port"),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Auto-open the default browser to the UI on startup",
    ),
) -> None:
    """Run the manual-correction web UI on http://<host>:<port>/.

    Auto-launches the default browser to the UI by default. Use
    ``--no-open`` to skip (e.g. when running headless).
    """
    import threading
    import time
    import webbrowser

    import uvicorn

    from ..data.db import default_portrait_library_path
    from ..web.app import create_app

    # Auto-discover the portrait library when --library isn't passed.
    # This is the default path the user shouldn't have to know about.
    if library_dir is None:
        library_dir = default_portrait_library_path()
        if library_dir is not None:
            console.print(f"[muted]Auto-loaded portrait library:[/] {library_dir}")
        else:
            console.print(
                "[yellow]No portrait library found at "
                "<user_data_dir>/portraits/ — screenshot uploads will be "
                "disabled. Pass --library or set NIKKE_OPTIMIZER_PORTRAITS to enable.[/]"
            )

    fastapi_app = create_app(db_path=db, portrait_library=library_dir)
    url = f"http://{host}:{port}/"
    console.print(f"[bold green]NikkeOptimizer UI[/] {url}")

    if open_browser:
        # Brief delay so uvicorn is bound before the browser tries to load.
        # Daemon thread so it dies with the main process if the user Ctrl-Cs
        # before the timer fires.
        def _delayed_open() -> None:
            time.sleep(0.7)
            webbrowser.open(url, new=2)
        threading.Thread(target=_delayed_open, daemon=True).start()

    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@app.command("counter")
def counter_cmd(
    opponent: list[str] = typer.Argument(
        ...,
        help="Opponent character names. Pass 5 names, or one capture ID with --capture.",
    ),
    capture_id: Optional[int] = typer.Option(
        None,
        "--capture",
        help="Use opponent_team from this ArenaMatch row instead of names",
    ),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    top_k: int = typer.Option(5, help="How many recommendations to return"),
    beam_width: int = typer.Option(200, help="Beam search width"),
    min_power: int = typer.Option(50_000, help="Filter low-investment characters"),
) -> None:
    """Recommend counter-pick teams against a specific opponent lineup.

    Examples:
        nikkeoptimizer counter "Snow White" "Crown" "Modernia" "Red Hood" "Liter"
        nikkeoptimizer counter --capture 1 _   # underscore is a placeholder
    """
    from ..data.models import ArenaMatch
    from ..optimizer.counter import recommend_counter

    engine = make_engine(db)
    init_db(engine)

    if capture_id is not None:
        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                console.print(f"[red]capture {capture_id} not found[/]")
                raise typer.Exit(1)
            opp_names = [n for n in (cap.opponent_team or []) if n]
            if not opp_names:
                console.print(
                    f"[red]capture {capture_id} has no opponent_team — Champion captures only store one team[/]"
                )
                raise typer.Exit(1)
            console.print(
                f"[bold]Counter-picking[/] capture #{capture_id}: "
                f"{cap.opponent_username or '?'} ({', '.join(opp_names)})"
            )
    else:
        opp_names = list(opponent)

    with get_session(engine) as session:
        rec = recommend_counter(
            session,
            opp_names,
            top_k=top_k,
            beam_width=beam_width,
            min_power=min_power,
        )

    if not rec.opponent.opponent_members:
        console.print("[red]none of the opponent names resolved against the DB[/]")
        raise typer.Exit(1)

    console.print(
        "[bold]Opponent elements:[/] "
        + ", ".join(
            f"{m.name} ({m.element.value})" for m in rec.opponent.opponent_members
        )
    )
    if not rec.teams:
        console.print("[yellow]no counter-pick recommendations[/]")
        return

    table = Table(title=f"Top {len(rec.teams)} counter teams")
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Power", justify="right")
    table.add_column("Members", overflow="fold")
    table.add_column("Notes", overflow="fold")
    for i, t in enumerate(rec.teams, 1):
        members = ", ".join(
            f"{m.name} ({m.element.value}/B{m.burst_position})" for m in t.members
        )
        table.add_row(
            str(i),
            f"{t.score:.2f}",
            f"{t.power:,}",
            members,
            "; ".join(t.notes) if t.notes else "-",
        )
    console.print(table)


@app.command("simulate")
def simulate_cmd(
    members: list[str] = typer.Argument(
        ...,
        help="Five character names (must all be in the encoded skill library).",
    ),
) -> None:
    """Run the static team evaluator on a 5-Nikke team.

    Reports DPS / EHP / sustain / burst payload computed from the
    encoded skill DSL — first slice of the Phase 3 simulator.
    """
    from ..simulator.evaluator import evaluate_by_names
    from ..simulator.registry import all_encoded_names

    if len(members) != 5:
        console.print(f"[red]Need exactly 5 character names; got {len(members)}.[/]")
        console.print(
            f"  encoded: {', '.join(all_encoded_names())}"
        )
        raise typer.Exit(2)

    result = evaluate_by_names(members)
    if result is None:
        encoded = set(all_encoded_names())
        missing = [m for m in members if m not in encoded]
        console.print(
            f"[red]Not all members are encoded.[/] Missing: {missing}"
        )
        console.print(f"  encoded: {', '.join(sorted(encoded))}")
        raise typer.Exit(1)

    console.print(f"\n[bold]Team:[/] {', '.join(m.name for m in result.members)}")
    console.print(
        f"  [bold]DPS estimate[/]:    {result.dps_estimate:>15,.0f}  "
        "(sum of effective ATK)"
    )
    console.print(
        f"  [bold]EHP estimate[/]:    {result.ehp_estimate:>15,.0f}  "
        "(base HP + shields)"
    )
    console.print(
        f"  [bold]Burst payload[/]:   {result.burst_payload:>15,.0f}  "
        "(burst-skill DEAL_DAMAGE × ATK)"
    )
    console.print(
        f"  [bold]Total shield[/]:    {result.total_shield:>15,.0f}"
    )
    console.print(
        f"  [bold]Sustain index[/]:   {result.sustain_index:>15,.2f}  "
        "(heal-per-sec × duration, summed)"
    )
    console.print(
        f"  [bold]Avg ATK buff %[/]:  {result.team_atk_buff_pct:>15,.2f}"
    )
    console.print(
        f"  [bold]Avg DEF buff %[/]:  {result.team_def_buff_pct:>15,.2f}"
    )

    table = Table(title="Per-Nikke breakdown")
    table.add_column("Name")
    table.add_column("ATK%", justify="right")
    table.add_column("DEF%", justify="right")
    table.add_column("Shield", justify="right")
    table.add_column("Burst dmg ×ATK", justify="right")
    table.add_column("Heal/s × dur", justify="right")
    for m in result.members:
        table.add_row(
            m.name,
            f"+{m.atk_buff_pct:.1f}",
            f"+{m.def_buff_pct:.1f}",
            f"{m.shield_value:,.0f}",
            f"{m.burst_damage_magnitude:.2f}",
            f"{m.heal_per_second * m.heal_duration:.2f}",
        )
    console.print(table)


@app.command("timing")
def timing_cmd(
    members: list[str] = typer.Argument(
        ...,
        help="Five character names (your team).",
    ),
    vs: Optional[str] = typer.Option(
        None,
        "--vs",
        help="Comma-separated opponent team to compare against.",
    ),
) -> None:
    """Quick burst-chain calculator for a 5-Nikke team (slice #81).

    Computes the predicted burst-chain offsets from the team weapon
    mix (slice #75) plus per-character gauge-fill bonuses (slice #78).
    Optionally compares against an opponent team.
    """
    from sqlmodel import select
    from ..data.models import Character
    from ..simulator.timeline import (
        BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC,
        BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC,
        compute_burst_chain_offsets,
    )

    if len(members) != 5:
        console.print(
            f"[red]Need exactly 5 character names; got {len(members)}.[/]"
        )
        raise typer.Exit(2)

    def _resolve(team: list[str]) -> tuple[list[Optional[str]], list[Optional[str]]]:
        weapons: list[Optional[str]] = []
        names: list[Optional[str]] = []
        with get_session(make_engine(default_db_path())) as session:
            for n in team:
                ch = session.exec(
                    select(Character).where(Character.name == n)
                ).one_or_none()
                if ch is None:
                    console.print(f"[yellow]warning:[/] character {n!r} not in DB")
                    weapons.append(None)
                    names.append(n)
                else:
                    weapons.append(ch.weapon_class.value if ch.weapon_class else None)
                    names.append(ch.name)
        return weapons, names

    def _show(label: str, team: list[str]) -> tuple[float, float]:
        weapons, names = _resolve(team)
        offsets = compute_burst_chain_offsets(weapons, member_names=names)
        weapon_total = sum(
            BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC.get((w or "").lower(), 1.8)
            for w in weapons
        )
        skill_total = sum(
            BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC.get(n or "", 0.0) for n in names
        )

        console.print(f"\n[bold]{label}:[/] {', '.join(team)}")
        table = Table(show_header=True)
        table.add_column("Slot")
        table.add_column("Name")
        table.add_column("Weapon")
        table.add_column("Weapon rate", justify="right")
        table.add_column("Skill bonus", justify="right")
        for i, (n, w) in enumerate(zip(names, weapons)):
            wr = BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC.get((w or "").lower(), 1.8)
            sb = BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC.get(n or "", 0.0)
            table.add_row(
                str(i + 1),
                n or "?",
                (w or "?").upper(),
                f"{wr:.2f}/s",
                f"{sb:+.2f}/s" if sb else "—",
            )
        console.print(table)
        console.print(
            f"  weapon-rate sum: [bold]{weapon_total:.2f}/s[/], "
            f"skill bonuses: [bold]{skill_total:+.2f}/s[/], "
            f"total: [bold]{weapon_total + skill_total:.2f}/s[/]"
        )
        console.print(
            f"  [bold]B1 burst @[/] {offsets[0]:.2f}s · "
            f"[bold]B3 / FB start @[/] {offsets[2]:.2f}s · "
            f"[bold]FB ends @[/] {offsets[2] + 10:.2f}s"
        )
        return offsets[0], offsets[2]

    my_b1, my_fb = _show("Your team", members)

    if vs:
        opp = [s.strip() for s in vs.split(",") if s.strip()]
        if len(opp) != 5:
            console.print(
                f"[red]--vs needs exactly 5 names (comma-separated); got {len(opp)}.[/]"
            )
            raise typer.Exit(2)
        opp_b1, opp_fb = _show("Opponent", opp)
        delta_fb = opp_fb - my_fb
        if delta_fb > 0.1:
            console.print(
                f"\n[green]Speed advantage[/]: your team's Full Burst opens "
                f"[bold]{delta_fb:.2f}s before[/] the opponent's"
            )
        elif delta_fb < -0.1:
            console.print(
                f"\n[red]Speed disadvantage[/]: opponent's Full Burst opens "
                f"[bold]{-delta_fb:.2f}s before[/] yours"
            )
        else:
            console.print("\n[bold]Burst timing roughly equal[/] (Δ < 0.1s)")


@app.command("resolve")
def resolve_cmd(
    attacker: str = typer.Argument(
        ...,
        help='Comma-separated attacker team, e.g. "Liter,Crown,Modernia,Red Hood,Snow White: Heavy Arms"',
    ),
    defender: str = typer.Argument(
        ...,
        help="Comma-separated defender team.",
    ),
) -> None:
    """Predict the outcome of a 5v5 PvP match (slice #89).

    Wraps the damage formula resolver — burst payload, DPS, time-to-
    clear, multi-cycle rotation count, and burst-time advantage.
    """
    from ..simulator.damage import resolve_by_names
    from ..simulator.timeline import compute_burst_chain_offsets, _load_weapons

    a_names = [s.strip() for s in attacker.split(",") if s.strip()]
    d_names = [s.strip() for s in defender.split(",") if s.strip()]
    if len(a_names) != 5 or len(d_names) != 5:
        console.print(
            f"[red]Need exactly 5 names per team; got attacker={len(a_names)}, "
            f"defender={len(d_names)}.[/]"
        )
        raise typer.Exit(2)

    result = resolve_by_names(a_names, d_names)
    if result is None:
        console.print(
            "[red]Resolution failed[/] — one or more team members aren't "
            "in the encoded skill registry. Use `nikkeoptimizer skill-coverage` "
            "to see what's encoded."
        )
        raise typer.Exit(1)

    # Compute burst-time delta for context.
    a_w = _load_weapons(a_names)
    d_w = _load_weapons(d_names)
    a_fb = compute_burst_chain_offsets(a_w, member_names=a_names)[2] if any(a_w) else None
    d_fb = compute_burst_chain_offsets(d_w, member_names=d_names)[2] if any(d_w) else None

    console.print(f"\n[bold]Attacker:[/] {', '.join(a_names)}")
    console.print(f"[bold]Defender:[/] {', '.join(d_names)}")

    if a_fb is not None and d_fb is not None:
        delta = d_fb - a_fb
        if delta > 0.1:
            console.print(
                f"  [green]Burst advantage[/]: attacker FB @ {a_fb:.2f}s vs "
                f"defender FB @ {d_fb:.2f}s ({delta:+.2f}s)"
            )
        elif delta < -0.1:
            console.print(
                f"  [yellow]Burst disadvantage[/]: attacker FB @ {a_fb:.2f}s "
                f"vs defender FB @ {d_fb:.2f}s ({delta:+.2f}s)"
            )
        else:
            console.print(
                f"  [bold]Burst timing equal[/]: both @ ~{a_fb:.2f}s"
            )

    verdict = (
        "[green]WIN[/]" if result.attacker_wins_within_5min else "[red]TIMEOUT[/]"
    )
    console.print(f"\n  Verdict: {verdict}")
    console.print(
        f"  Time to clear:    {result.seconds_to_clear_defender:>8.1f}s "
        f"({result.seconds_to_clear_defender / 60:.2f}m)"
    )
    console.print(
        f"  Win margin:       {result.win_margin:>+8.0f}s vs 5-min cap"
    )
    console.print(
        f"  Burst payload:    {result.attacker_burst_payload:>15,.0f}"
    )
    console.print(
        f"  Defender HP pool: {result.defender_effective_hp:>15,.0f}"
    )
    console.print(
        f"  Team DPS:         {result.attacker_team_dps:>15,.0f} "
        f"(ATK {result.attacker_atk_damage_per_sec:,.0f} + "
        f"true {result.attacker_true_damage_per_sec:,.0f} + "
        f"other {result.attacker_other_damage_per_sec:,.0f})"
    )
    if result.notes:
        console.print("\n  [bold]Notes:[/]")
        for n in result.notes:
            console.print(f"    · {n}")


@app.command("simulate-timeline")
def simulate_timeline_cmd(
    members: list[str] = typer.Argument(
        ...,
        help="Five character names (must all be in the encoded skill library).",
    ),
    at: list[float] = typer.Option(
        [0.0, 12.0, 15.0, 22.0, 30.0, 60.0],
        "--at",
        help="Sample times (seconds). Default samples cover battle start, "
        "burst chain, full burst window, post-burst, mid-match, and late-match.",
    ),
) -> None:
    """Time-windowed evaluator — show team state at multiple timestamps.

    The static evaluator (``simulate``) collapses everything to a single
    post-burst-chain snapshot. This command shows how buffs / shields
    decay over a 5-minute match window. Useful for understanding when
    the team's burst window is actually active vs when it's wearing off.
    """
    from ..simulator.registry import all_encoded_names
    from ..simulator.timeline import build_timeline_by_names

    if len(members) != 5:
        console.print(f"[red]Need 5 character names; got {len(members)}.[/]")
        raise typer.Exit(2)
    timeline = build_timeline_by_names(members)
    if timeline is None:
        encoded = set(all_encoded_names())
        missing = [m for m in members if m not in encoded]
        console.print(f"[red]Not all members are encoded.[/] Missing: {missing}")
        raise typer.Exit(1)

    console.print(f"\n[bold]Team:[/] {', '.join(timeline.member_names)}")
    console.print(
        f"[muted]{len(timeline.applied)} effect applications across the timeline[/]"
    )

    for t in at:
        states = timeline.state_at(t)
        avg_atk = sum(s.atk_buff_pct for s in states) / max(len(states), 1)
        avg_def = sum(s.def_buff_pct for s in states) / max(len(states), 1)
        total_shield = sum(s.shield_value for s in states)
        active = sum(1 for e in timeline.applied if e.is_active_at(t))
        console.print(
            f"\n[bold]t={t:>6.1f}s[/]  "
            f"avg ATK +{avg_atk:>6.1f}%  "
            f"avg DEF +{avg_def:>6.1f}%  "
            f"shield {total_shield:>10,.0f}  "
            f"active effects: {active}"
        )


@app.command("skill")
def skill_cmd(
    character: str = typer.Argument(..., help="Character name (encoded in the simulator library)"),
) -> None:
    """Inspect the encoded skill DSL for one character."""
    from ..simulator.registry import get

    skills = get(character)
    if skills is None:
        from ..simulator.registry import all_encoded_names

        encoded = all_encoded_names()
        console.print(f"[red]{character!r} is not encoded yet[/]")
        console.print(f"  encoded so far: {', '.join(encoded)}")
        raise typer.Exit(1)

    console.print(f"\n[bold]{skills.character_name}[/] (skill levels {skills.skill_levels_assumed})")
    if skills.notes:
        console.print(f"  [dim]{skills.notes}[/]\n")
    for slot_name in ("skill1", "skill2", "burst_skill"):
        slot = getattr(skills, slot_name)
        console.print(f"  [bold]{slot_name}[/]")
        for se in slot:
            if se.description:
                console.print(f"    [italic]{se.description}[/]")
            console.print(
                f"    trigger: [cyan]{se.trigger.kind.value}[/]"
                + (f" every {se.trigger.every_n_hits} hits" if se.trigger.every_n_hits else "")
                + (f" cd={se.trigger.cooldown_seconds}s" if se.trigger.cooldown_seconds else "")
            )
            for eff in se.effects:
                duration = (
                    f" for {eff.duration_seconds}s"
                    if eff.duration_seconds > 0
                    else ""
                )
                stacks = f" (×{eff.stacks_max} stacks)" if eff.stacks_max > 1 else ""
                console.print(
                    f"      [magenta]{eff.kind.value}[/] → "
                    f"{eff.target.kind.value}"
                    + (f"[{eff.target.count}]" if eff.target.count > 1 else "")
                    + f": {eff.magnitude}{duration}{stacks}"
                )
            console.print()


@app.command("skill-coverage")
def skill_coverage_cmd(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
) -> None:
    """Report how many DB characters are encoded in the skill library."""
    from ..simulator.registry import all_encoded_names, coverage_against

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        db_names = [c.name for c in session.exec(select(Character)).all()]

    cov = coverage_against(db_names)
    encoded = cov["encoded"]
    orphans = cov["encoded_orphans"]
    unencoded = cov["unencoded_in_db"]

    console.print(f"[bold]Skill library coverage[/]")
    console.print(f"  encoded characters: {len(all_encoded_names())}")
    console.print(f"  matched against DB: {len(encoded)}")
    if orphans:
        console.print(
            f"  [yellow]encoded but not in DB[/]: {', '.join(orphans)} "
            "(typo or unscraped)"
        )
    console.print(f"  unencoded DB characters: {len(unencoded)}")
    if encoded:
        console.print(f"\n  encoded: {', '.join(encoded)}")


@app.command("explain")
def explain_cmd(
    character: str = typer.Argument(..., help="Character name (case-insensitive, substring OK)"),
    role: str = typer.Option(
        "balanced",
        help="Score weights: 'attack', 'defense', or 'balanced'",
    ),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    beam_width: int = typer.Option(200),
    min_power: int = typer.Option(50_000),
) -> None:
    """Show why ``character`` isn't in the top recommendation.

    Compares the best team that *includes* the given character against the
    global top team, and prints the per-component score deltas.
    """
    from ..optimizer.explain import explain_character

    if role not in ("attack", "defense", "balanced"):
        console.print(f"[red]role must be 'attack', 'defense', or 'balanced'[/]")
        raise typer.Exit(2)

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        result = explain_character(
            session,
            character,
            role=role,  # type: ignore[arg-type]
            beam_width=beam_width,
            min_power=min_power,
        )

    if result.best_with_target is None:
        if result.target.power == 0 and result.target.element is None:
            console.print(f"[red]character {character!r} not found in your roster[/]")
        else:
            console.print(
                f"[yellow]found {result.target.name!r} but no valid 5-Nikke team "
                "includes them — likely a burst-chain dead-end at this min_power[/]"
            )
        raise typer.Exit(1)

    target = result.target
    bt = result.best_with_target
    gt = result.global_top
    console.print(
        f"\n[bold]Best {result.role} team containing {target.name}:[/]"
    )
    members = ", ".join(
        f"{m.name} ({m.element.value}/B{m.burst_position})" for m in bt.members
    )
    console.print(f"  {members}")
    console.print(f"  score: {bt.score:.2f} · power: {bt.power:,}")

    if gt is not None and result.score_delta is not None:
        delta_str = (
            f"[green]+{result.score_delta:.2f}[/]"
            if result.score_delta >= 0
            else f"[yellow]{result.score_delta:.2f}[/]"
        )
        console.print(
            f"\n[bold]vs global top {result.role} team[/] "
            f"(score {gt.score:.2f}): {delta_str}"
        )
        global_members = ", ".join(m.name for m in gt.members)
        console.print(f"  global top: {global_members}")
        deltas = result.component_deltas
        # Show only components that meaningfully differ.
        notable = sorted(
            ((k, v) for k, v in deltas.items() if abs(v) > 0.1),
            key=lambda kv: kv[1],
        )
        if notable:
            console.print("\n[bold]Per-component delta (target team − global top):[/]")
            for k, v in notable:
                color = "green" if v >= 0 else "yellow"
                console.print(f"  [{color}]{v:+.2f}[/]  {k}")


@app.command("counter-sp")
def counter_sp_cmd(
    captures: list[int] = typer.Option(
        ...,
        "--capture",
        "-c",
        help="ArenaMatch IDs (one per defense round). Pass --capture three times.",
    ),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    beam_width: int = typer.Option(200, help="Beam search width"),
    min_power: int = typer.Option(50_000, help="Filter low-investment characters"),
) -> None:
    """Recommend 3 SP Arena attack teams, one per captured opposing defense.

    Example:
        nikkeoptimizer counter-sp -c 1 -c 2 -c 3
    """
    from ..optimizer.sp_counter import (
        recommend_sp_counter,
        resolve_defenses_from_capture_ids,
    )

    if len(captures) != 3:
        console.print(
            f"[yellow]SP Arena has 3 sub-matches — pass --capture 3 times "
            f"(got {len(captures)})[/]"
        )
        raise typer.Exit(2)

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        try:
            defenses = resolve_defenses_from_capture_ids(session, captures)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        rec = recommend_sp_counter(
            session,
            defenses,
            top_k=1,
            beam_width=beam_width,
            min_power=min_power,
        )

    for round_idx, (cap_id, round_rec) in enumerate(zip(captures, rec.rounds), 1):
        defense_names = ", ".join(
            m.name for m in round_rec.opponent.opponent_members
        )
        console.print(
            f"\n[bold]Round {round_idx}[/] (capture #{cap_id}) — defense: {defense_names}"
        )
        if not round_rec.teams:
            console.print("[yellow]  no counter-pick recommendation[/]")
            continue
        team = round_rec.teams[0]
        members = ", ".join(
            f"{m.name} ({m.element.value}/B{m.burst_position})" for m in team.members
        )
        console.print(f"  attack: {members}")
        console.print(f"  score: {team.score:.2f} · power: {team.power:,}")
        if team.notes:
            for n in team.notes:
                console.print(f"  [dim]· {n}[/]")


@app.command()
def optimize(
    mode: str = typer.Argument(
        "rookie",
        help="Optimization mode: rookie. counter/sp/champion coming later.",
    ),
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    top_k: int = typer.Option(5, help="How many recommendations to return"),
    beam_width: int = typer.Option(200, help="Beam search width — wider = slower + better"),
    min_power: int = typer.Option(
        50_000,
        help="Skip characters below this power (knocks low-investment Nikkes out of the search pool)",
    ),
) -> None:
    """Recommend the top-K teams for the given PvP mode."""
    engine = make_engine(db)
    init_db(engine)

    def _render(title: str, teams: list) -> None:
        table = Table(title=title)
        table.add_column("#", justify="right")
        table.add_column("Score", justify="right")
        table.add_column("Power", justify="right")
        table.add_column("Members", overflow="fold")
        table.add_column("Notes", overflow="fold")
        for i, t in enumerate(teams, 1):
            bursts = "/".join(m.burst_position for m in t.members)
            members = ", ".join(f"{m.name} (B{m.burst_position})" for m in t.members)
            table.add_row(
                str(i),
                f"{t.score:.2f}",
                f"{t.power:,}",
                f"{members}\n[dim]bursts {bursts}[/]",
                "; ".join(t.notes) if t.notes else "-",
            )
        console.print(table)

    if mode == "rookie":
        from ..optimizer.rookie import recommend_rookie

        with get_session(engine) as session:
            rec = recommend_rookie(
                session, top_k=top_k, beam_width=beam_width, min_power=min_power
            )
        if not rec.attack and not rec.defense:
            console.print(
                "[red]no recommendations — is your roster imported?[/]\n"
                "Run: [cyan]nikkeoptimizer import-csv <path/to/roster.csv>[/]"
            )
            raise typer.Exit(1)
        _render(f"Top {len(rec.attack)} attack teams", rec.attack)
        _render(f"Top {len(rec.defense)} defense teams", rec.defense)
        return

    if mode == "sp":
        from ..optimizer.sp_arena import recommend_sp_arena

        with get_session(engine) as session:
            rec = recommend_sp_arena(
                session, beam_width=beam_width, min_power=min_power
            )
        if not rec.attack and not rec.defense:
            console.print("[red]no recommendations[/]")
            raise typer.Exit(1)
        _render(
            "SP Arena attack — 3 distinct teams (repeat any in slots 1/2/3)",
            rec.attack,
        )
        _render(
            "SP Arena defense — 3 disjoint teams (uniqueness enforced)",
            rec.defense,
        )
        for n in rec.notes:
            console.print(f"[yellow]{n}[/]")
        return

    if mode in ("champion", "champions"):
        from ..optimizer.champions import recommend_champions

        with get_session(engine) as session:
            rec = recommend_champions(
                session, beam_width=beam_width, min_power=min_power
            )
        if not rec.teams:
            console.print("[red]no recommendations[/]")
            raise typer.Exit(1)
        _render(
            "Champions Arena — 5 disjoint teams (season-locked, balanced for both roles)",
            rec.teams,
        )
        if rec.coverage:
            cov = rec.coverage
            console.print(
                f"[bold]Coverage:[/] {int(cov.element_coverage)}/5 opposing elements countered, "
                f"{int(cov.archetype_spread * 5)}/5 archetype spread"
            )
            if cov.uncovered_opposing_elements:
                missing = ", ".join(e.value for e in cov.uncovered_opposing_elements)
                console.print(f"  [yellow]missing element coverage:[/] {missing}")
        for n in rec.notes:
            console.print(f"[yellow]{n}[/]")
        return

    console.print(
        f"[yellow]mode '{mode}' not implemented — try 'rookie', 'sp', 'champion', or `counter`[/]"
    )
    raise typer.Exit(2)


@app.command("seed-dolls")
def seed_dolls_cmd(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    show: bool = typer.Option(False, "--show", help="List the seeded catalog after writing"),
) -> None:
    """Populate the Doll / DollSkill / DollSkillPhase tables from doll_data.py.

    Idempotent — wipes and re-inserts each run. Linearly interpolates
    phases between published checkpoints (Phase 1 / 5 / 15 depending on
    rarity). Phase rows derived by interpolation are flagged via
    ``DollSkillPhase.interpolated``.

    Examples:

      nikkeoptimizer seed-dolls
      nikkeoptimizer seed-dolls --show
    """
    from ..data.doll_seed import seed_dolls
    from ..data.models import Doll, DollSkill, DollSkillPhase

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        counts = seed_dolls(session)
        console.print(
            f"[bold green]Seeded[/] {counts['dolls']} dolls, "
            f"{counts['skills']} skills, {counts['phases']} phase rows."
        )

        if show:
            dolls = session.exec(select(Doll).order_by(Doll.weapon_class, Doll.rarity)).all()
            for doll in dolls:
                console.print(
                    f"\n[bold cyan]{doll.name}[/] "
                    f"({doll.weapon_class.value} / {doll.rarity.value}, "
                    f"max phase {doll.max_phase})"
                )
                skills = session.exec(
                    select(DollSkill).where(DollSkill.doll_id == doll.id)
                    .order_by(DollSkill.skill_index)
                ).all()
                for skill in skills:
                    console.print(f"  [yellow]Skill {skill.skill_index}[/]: {skill.name}")
                    phases = session.exec(
                        select(DollSkillPhase).where(DollSkillPhase.skill_id == skill.id)
                        .order_by(DollSkillPhase.phase)
                    ).all()
                    # Show only checkpoint phases (non-interpolated) by default.
                    for ph in phases:
                        if ph.interpolated:
                            continue
                        effects = ", ".join(
                            f"{e['stat']} {'▼' if e.get('direction') == 'down' else '▲'} {e['magnitude']}%"
                            for e in ph.effects
                        )
                        console.print(f"    Phase {ph.phase}: {effects}")


@app.command("seed-treasures")
def seed_treasures_cmd(
    db: Optional[Path] = typer.Option(None, help="Override DB path"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass on-disk fetch cache"),
) -> None:
    """Populate the TreasureSkill table from Prydwen's ``-treasure`` pages.

    Walks every character with ``hasTreasure = True`` in the Prydwen
    index, fetches the corresponding ``<slug>-treasure`` JSON, extracts
    each skill's ``phase`` field + skill text, and upserts a row per
    (character, skill_index). Idempotent.

    Requires the base ``Character`` rows to already exist (run
    ``nikkeoptimizer refresh`` first).
    """
    from ..data.models import Character, TreasureSkill
    from ..data.scrapers.prydwen import PrydwenClient, extract_treasure_skills
    from ..data.scrapers.refresh import default_cache_dir as scraper_cache_dir

    engine = make_engine(db)
    init_db(engine)

    async def _run() -> tuple[int, int]:
        cache = None if no_cache else scraper_cache_dir()
        async with PrydwenClient(cache_dir=cache) as client:
            slugs_all = await client.list_character_slugs()
        treasure_slugs = [s for s in slugs_all if s.endswith("-treasure")]

        n_chars = 0
        n_skills = 0
        async with PrydwenClient(cache_dir=cache) as client:
            for slug in treasure_slugs:
                data = await client._get_json(
                    f"https://www.prydwen.gg/page-data/nikke/characters/{slug}/page-data.json",
                    cache_key=f"char_{slug}",
                )
                try:
                    node = data["result"]["data"]["currentUnit"]["nodes"][0]
                except (KeyError, IndexError):
                    continue
                rows = extract_treasure_skills(node)
                if not rows:
                    continue

                with get_session(engine) as session:
                    char = session.exec(
                        select(Character).where(Character.name == node.get("name"))
                    ).first()
                    if char is None:
                        console.print(
                            f"[yellow]skip {slug}: '{node.get('name')}' not in Character table — run refresh first[/]"
                        )
                        continue

                    # Wipe old rows for this character so we start fresh.
                    existing = session.exec(
                        select(TreasureSkill).where(TreasureSkill.character_id == char.id)
                    ).all()
                    for r in existing:
                        session.delete(r)
                    for row in rows:
                        session.add(
                            TreasureSkill(
                                character_id=char.id,
                                skill_index=row["skill_index"],
                                skill_slot=row["skill_slot"],
                                name=row["name"],
                                upgrade_phase=row["upgrade_phase"],
                                description_treasured=row["description_treasured"],
                            )
                        )
                    session.commit()
                    n_chars += 1
                    n_skills += len(rows)
        return n_chars, n_skills

    n_chars, n_skills = asyncio.run(_run())
    console.print(
        f"[bold green]Seeded[/] {n_skills} treasure-skill rows across {n_chars} characters."
    )


if __name__ == "__main__":
    app()
