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
    name: Optional[list[str]] = typer.Option(
        None, "--name", "-n",
        help="Refresh only the named character(s); pass multiple times or "
             "comma-separated. Resolved against Prydwen slugs case-insensitively. "
             "Default: refresh every character.",
    ),
) -> None:
    """Fetch character data from Prydwen and upsert into the local database.

    Examples:

      \b
      nikkeoptimizer refresh                       # refresh all characters
      nikkeoptimizer refresh --name Mint           # just one character
      nikkeoptimizer refresh -n Mint -n "Red Hood" # several
      nikkeoptimizer refresh --name "Mint,Red Hood" --no-cache
    """
    from ..data.scrapers.refresh import refresh_async

    # Allow either repeated flags or a comma-separated single value.
    names: Optional[list[str]] = None
    if name:
        names = []
        for entry in name:
            for piece in entry.split(","):
                p = piece.strip()
                if p:
                    names.append(p)

    counts = asyncio.run(
        refresh_async(db_path=db, use_cache=not no_cache, names=names)
    )
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


@app.command(name="auto-import")
def auto_import_cmd(
    staging: Optional[Path] = typer.Option(
        None, "--staging",
        help="Staging dir to walk (defaults to <repo>/incoming-captures/champion_arena).",
    ),
    log_path: Optional[Path] = typer.Option(
        None, "--log",
        help="Audit log path (defaults to <repo>/logs/auto_import.log).",
    ),
    lock_path: Optional[Path] = typer.Option(
        None, "--lock",
        help="Lock file (defaults to /tmp/nikke-autoimport.lock).",
    ),
) -> None:
    """Run the auto-import daemon: subscribe to Syncthing's event API and
    trigger ``ingest-tournaments`` whenever the watched folder reports
    completion.

    Reads Syncthing's API key + folder ID from
    ``~/Library/Application Support/Syncthing/config.xml`` (matches the
    folder whose ``path`` contains the staging dir).

    Designed for launchd (``KeepAlive=true``). Single-instance enforced
    via flock. Audit log rotates at 5MB.
    """
    from .. import auto_import

    kwargs: dict = {}
    if staging is not None:
        kwargs["staging"] = staging
    if log_path is not None:
        kwargs["log_path"] = log_path
    if lock_path is not None:
        kwargs["lock_path"] = lock_path
    raise typer.Exit(code=auto_import.run_daemon(**kwargs) or 0)


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


@app.command("set-uid")
def set_uid_cmd(
    uid: str = typer.Argument(
        ..., help="Your base64-encoded BlablaLink intl_openid (the "
                  "`?uid=...` param on a shiftyspad URL).",
    ),
) -> None:
    """Persist your BlablaLink ``intl_openid`` so the daemon can run
    sparse self-refreshes after each rookie run.

    Equivalent to setting ``NIKKE_OPTIMIZER_UID`` permanently. Used
    by the post-rookie-ingest self-refresh hook in ``auto-import``;
    without it that hook is skipped with a one-line audit note.
    """
    from ..data.config import set_self_intl_openid

    path = set_self_intl_openid(uid)
    console.print(f"[bold green]Saved intl_openid[/] {uid!r} -> {path}")


@app.command("show-config")
def show_config_cmd() -> None:
    """Show the resolved self-username + intl_openid (env vars or
    config file).
    """
    from ..data.config import get_self_intl_openid, get_self_username

    name = get_self_username()
    if name:
        console.print(f"Self-username:   [bold]{name}[/]")
    else:
        console.print(
            "[yellow]No self-username configured. "
            "Run [bold]nikkeoptimizer set-username <name>[/] to set one.[/]"
        )
    uid = get_self_intl_openid()
    if uid:
        console.print(f"Self-intl_openid: [bold]{uid}[/]")
    else:
        console.print(
            "[yellow]No intl_openid configured. "
            "Run [bold]nikkeoptimizer set-uid <base64-uid>[/] to enable "
            "the rookie self-refresh.[/]"
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


# ---------------------------------------------------------------------------
# ShiftyPad scraper
# ---------------------------------------------------------------------------


@app.command("shiftyspad-login")
def shiftyspad_login_cmd(
    sentinel: Path = typer.Option(
        Path("/tmp/blablalink-login-done"),
        "--sentinel", help="Path to touch when login is complete (script polls for it).",
    ),
    max_wait_minutes: int = typer.Option(30, "--max-wait", help="Max wait time before giving up."),
) -> None:
    """Open a Chromium window for manual BlablaLink login.

    The persistent profile under
    ``~/Library/Application Support/NikkeOptimizer/blablalink/_browser_profile/``
    is reused so subsequent ``fetch-shiftyspad`` calls inherit the
    session cookies. Steps:

      1. A Chromium window opens at https://www.blablalink.com/.
      2. Log in via whatever method you normally use.
      3. (Optional) Navigate to your own ShiftyPad profile and verify
         "My Nikkes" renders content — confirms the session works.
      4. In another terminal, run ``touch /tmp/blablalink-login-done``
         (or the value of ``--sentinel``). The script detects the file,
         captures the cookies, and exits.

    Cookies persist for ~30 days; re-run when sessions expire.
    """
    import time as _time
    from ..data.scrapers.shiftyspad import default_browser_profile_dir
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("[red]Playwright is not installed. Run: pip install -e '.[scrape]' && playwright install chromium[/]")
        raise typer.Exit(1)

    if sentinel.exists():
        sentinel.unlink()
    profile = default_browser_profile_dir()
    console.print(f"[cyan]persistent profile:[/] {profile}")
    console.print(f"[cyan]when done logging in, run:[/] touch {sentinel}")

    deadline = _time.monotonic() + max_wait_minutes * 60
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.blablalink.com/", wait_until="domcontentloaded")
        while _time.monotonic() < deadline:
            if sentinel.exists():
                break
            _time.sleep(1.0)
        cookies = ctx.cookies()
        ctx.close()
    bla_auth = [c for c in cookies if c["name"].startswith("game_")]
    console.print(
        f"[green]captured[/] {len(cookies)} cookies "
        f"({len(bla_auth)} look like game-session cookies)"
    )
    if sentinel.exists():
        sentinel.unlink()
    if not bla_auth:
        console.print(
            "[yellow]warning:[/] no game_* cookies found — login may not have succeeded."
        )


@app.command("snapshot-names")
def snapshot_names_cmd(
    season: int = typer.Option(..., "--season", help="Beta season number (e.g. 30)."),
    player: str = typer.Option(
        ..., "--player",
        help="Player identifier — matches ArenaMatch.user_username or "
             "opponent_username.",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Print the unique characters a player used in a Champions Arena season.

    Read-only convenience for the snapshot-scraping flow. Walks
    ArenaMatch rows for the season, filters by player name (either
    side), unions the character lists from all 5 teams, then prints
    a comma-separated list ready to paste into `fetch-shiftyspad --names`.

    Example:

      \b
      nikkeoptimizer snapshot-names --season 30 --player Aerin
      → "Crown,Modernia,Liter,..." # paste into --names of fetch-shiftyspad
    """
    from ..data.models import ArenaMatch
    from ..data.seasons import season_for_date

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        matches = session.exec(
            select(ArenaMatch).where(ArenaMatch.mode == "champion")
        ).all()

    chars: set[str] = set()
    matched_n = 0
    for m in matches:
        if not m.captured_at:
            continue
        try:
            if season_for_date(m.captured_at.date()) != season:
                continue
        except Exception:  # noqa: BLE001
            continue
        if m.user_username == player:
            chars.update(c for c in (m.user_team or []) if c)
            matched_n += 1
        if m.opponent_username == player:
            chars.update(c for c in (m.opponent_team or []) if c)
            matched_n += 1

    if not chars:
        console.print(
            f"[yellow]no Champions matches found for player={player!r} "
            f"in season {season}[/]"
        )
        raise typer.Exit(0)

    sorted_chars = sorted(chars)
    console.print(
        f"[cyan]{len(sorted_chars)} unique char(s) across {matched_n} "
        f"match-sides for {player!r} in season {season}:[/]"
    )
    console.print(",".join(sorted_chars))


@app.command("stub-character")
def stub_character_cmd(
    name: str = typer.Argument(..., help="Character display name (e.g. 'Mint')."),
    from_shiftyspad: bool = typer.Option(
        True, "--from-shiftyspad/--no-shiftyspad",
        help="Source minimal fields from the mirrored BlablaLink nikke list. "
             "Default is the only mode currently supported.",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Create a minimal `Character` row from BlablaLink data.

    Use this when a Nikke shows up in your ShiftyPad roster but isn't on
    Prydwen yet (typical for the first few days after a new release).
    The stub lets the optimizer treat the character normally; once
    Prydwen ships her review, `nikkeoptimizer refresh --name <X>`
    upgrades the stub to full data.

    The stub's `source` column is set to `"blablalink_stub"`, which
    `fetch-shiftyspad` surfaces as a recurring reminder.
    """
    from ..roster.shiftyspad_importer import stub_from_shiftyspad
    if not from_shiftyspad:
        console.print("[red]Only --from-shiftyspad is supported today.[/]")
        raise typer.Exit(1)
    char, status = stub_from_shiftyspad(name, db_path=db)
    if status == "not_found":
        console.print(
            f"[red]'{name}' not found in BlablaLink nikke list mirror.[/]\n"
            f"  Try `nikkeoptimizer fetch-roledata --all` to refresh the mirror."
        )
        raise typer.Exit(1)
    if status == "exists":
        console.print(
            f"[yellow]Character '{name}' already exists in the DB[/] "
            f"(source={char.source!r}). Not overwritten."
        )
        if char.source != "blablalink_stub":
            console.print(
                "[dim]  → already has Prydwen data; no stub needed.[/]"
            )
        return
    console.print(
        f"[bold green]Stub created[/] for '{name}'\n"
        f"  rarity={char.rarity.value} element={char.element.value} "
        f"weapon={char.weapon_class.value} burst={char.burst_type.value} "
        f"mfr={char.manufacturer.value if char.manufacturer else '?'}\n"
        f"  role_tags={char.role_tags} source={char.source!r}\n"
        f"[dim]  → upgrade to full Prydwen data later via:[/] "
        f"nikkeoptimizer refresh --name {name}"
    )


@app.command("fetch-shiftyspad")
def fetch_shiftyspad_cmd(
    uid: str = typer.Argument(
        ..., help="Base64-encoded uid from the shiftyspad URL (?uid=...).",
    ),
    names: Optional[str] = typer.Option(
        None, "--names",
        help="Comma-separated character names to fetch details for. Default: all owned.",
    ),
    max_chars: Optional[int] = typer.Option(
        None, "--max-chars",
        help="Cap on per-character detail fetches (safety lever during dev). "
             "Home-page data (basic_info, outpost, roster summary) is always fetched.",
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write changes to DB. Default is dry-run.",
    ),
    headless: bool = typer.Option(
        True, "--headless/--no-headless",
        help="Run Chromium headless. --no-headless shows the browser.",
    ),
    delay_lo: float = typer.Option(
        3.0, "--delay-lo", help="Min seconds between detail-page navigations.",
    ),
    delay_hi: float = typer.Option(
        7.0, "--delay-hi", help="Max seconds between detail-page navigations.",
    ),
    snapshot: bool = typer.Option(
        False, "--snapshot",
        help="Write to RosterSnapshot (Champions Arena) instead of the live "
             "OwnedCharacter table. Requires --season; --player-username "
             "defaults to the BlablaLink nickname for self-scrapes. Always "
             "writes (no dry-run) — re-run replaces the existing snapshot.",
    ),
    season: Optional[int] = typer.Option(
        None, "--season",
        help="Beta season number (e.g. 30). Required with --snapshot.",
    ),
    player_username: Optional[str] = typer.Option(
        None, "--player-username",
        help="Player identifier for the snapshot row (defaults to the scraped "
             "profile's nickname). Required when the nickname isn't available.",
    ),
    no_link_matches: bool = typer.Option(
        False, "--no-link-matches",
        help="With --snapshot: skip the auto-link to existing ArenaMatch FKs.",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Sync a ShiftyPad player profile into the local DB.

    Default is a **dry run** — fetches the data and prints a diff
    against the current DB without writing. Pass ``--apply`` to
    commit the changes.

    Behavior:
      - The home page is loaded once: that captures BasicInfo,
        OutpostInfo, and the owned-characters list in a single
        navigation.
      - For each target character, the detail page is loaded
        sequentially with a randomized ``--delay-lo``..``--delay-hi``
        gap between (mimics a user clicking through their roster;
        keep the defaults unless you have a reason).
      - When a profile has My Nikkes private, the roster + details
        are unavailable but the public Outpost fields still sync.
      - When a profile's Outpost research is per-field redacted, the
        scraper skips the research fields (synchro level + battle
        level stay public).

    Examples:

      \b
      nikkeoptimizer fetch-shiftyspad <uid>            # full dry-run
      nikkeoptimizer fetch-shiftyspad <uid> --apply    # full sync
      nikkeoptimizer fetch-shiftyspad <uid> --names "Alice,Modernia" --apply
      nikkeoptimizer fetch-shiftyspad <uid> --max-chars 3  # safety-capped probe
    """
    from ..data.scrapers.shiftyspad import (
        ShiftyPadFetcher,
        fetch_character_details,
    )
    from ..roster.shiftyspad_importer import (
        NameCodeIndex,
        sync,
        sync_to_snapshot,
    )

    if snapshot and season is None:
        console.print("[red]--snapshot requires --season N[/]")
        raise typer.Exit(1)

    name_filter = None
    if names:
        name_filter = {n.strip() for n in names.split(",") if n.strip()}
    name_index = NameCodeIndex.from_mirror()

    # Reverse lookup: English name → name_code (case-insensitive).
    name_to_code = {v.lower(): k for k, v in name_index.name_code_to_name.items()}

    console.print(f"[cyan]fetching home page for[/] uid={uid}")
    with ShiftyPadFetcher(
        headless=headless,
        detail_delay_range=(delay_lo, delay_hi),
    ) as f:
        home = f.fetch_home(uid)
        console.print(
            f"  basic_info:    {'yes' if home.basic_info else 'no'}\n"
            f"  outpost_info:  {'yes' if home.outpost_info else 'no'}"
            f" {'(research private)' if home.is_outpost_private else ''}\n"
            f"  characters:    {len(home.characters)}"
            f" {'(roster private)' if home.is_roster_private else ''}"
        )

        # Decide which characters to fetch details for.
        target_codes: list[int] = []
        if home.characters and not home.is_roster_private:
            if name_filter:
                missing: list[str] = []
                for n in name_filter:
                    code = name_to_code.get(n.lower())
                    if code is None:
                        missing.append(n)
                    else:
                        target_codes.append(code)
                if missing:
                    console.print(f"[yellow]no name_code for:[/] {missing}")
            else:
                target_codes = [
                    int(c["name_code"]) for c in home.characters
                    if c.get("name_code") is not None
                ]
            if max_chars is not None:
                target_codes = target_codes[:max_chars]

        details = []
        if target_codes:
            console.print(
                f"[cyan]fetching details for {len(target_codes)} character(s)[/]"
                f" — estimated {len(target_codes) * (delay_lo + delay_hi) / 2:.0f}s"
            )

            def _progress(i: int, n: int, code: int) -> None:
                name = name_index.name_code_to_name.get(code, f"#{code}")
                console.print(f"  [dim]({i + 1}/{n})[/] {name}")

            details = fetch_character_details(
                uid, target_codes,
                name_code_to_resource_id=name_index.name_code_to_resource_id,
                fetcher=f,
                progress=_progress,
            )

    # ---- Snapshot mode (Champions Arena, season-locked) ----
    if snapshot:
        # Resolve player_username: prefer explicit flag, else nickname.
        resolved_username = player_username
        if resolved_username is None and home.basic_info:
            resolved_username = home.basic_info.get("nickname")
        if not resolved_username:
            console.print(
                "[red]--player-username is required when the profile's "
                "nickname isn't available[/]"
            )
            raise typer.Exit(1)
        snap_report = sync_to_snapshot(
            home, details,
            season_number=season,
            player_username=resolved_username,
            name_index=name_index,
            db_path=db,
            link_matches=not no_link_matches,
        )
        console.print()
        console.print(
            f"[bold green]Snapshot written[/]: id={snap_report.snapshot_id} "
            f"season={snap_report.season_number} "
            f"player={snap_report.player_username!r}"
        )
        console.print(
            f"  chars written: {snap_report.chars_written} "
            f"(matched {snap_report.matched} of {snap_report.rows_seen} seen)"
        )
        if snap_report.replaced_existing:
            console.print(f"  [dim]replaced prior snapshot for same (season, player)[/]")
        if snap_report.matches_linked:
            console.print(
                f"  [green]linked {snap_report.matches_linked} "
                f"ArenaMatch row(s) to this snapshot[/]"
            )
        if snap_report.is_outpost_private:
            console.print("  [yellow]outpost research is redacted on this profile[/]")
        if snap_report.is_roster_private:
            console.print("  [yellow]roster is private — no per-char rows written[/]")
        if snap_report.unmatched:
            console.print(f"  [yellow]unmatched ({len(snap_report.unmatched)}):[/] {snap_report.unmatched[:10]}")
        return

    # ---- Live-table mode (default) ----
    report = sync(
        home, details, name_index=name_index, db_path=db, apply=apply,
    )

    # Print summary.
    console.print()
    if report.profile_summary:
        console.print("[bold]Profile:[/]")
        for k, v in report.profile_summary.items():
            tag = "[red]" if k == "is_banned" and v else ""
            console.print(f"  {k}: {tag}{v}{'[/]' if tag else ''}")

    if report.account_state_changes:
        console.print("\n[bold]AccountState changes:[/]")
        for k, (old, new) in report.account_state_changes.items():
            console.print(f"  {k}: {old} → {new}")
    else:
        console.print("\n[dim]no AccountState changes[/]")

    changed = report.changed()
    extras_only = [d for d in report.diffs if d.extras and not (d.changes or d.is_new)]
    if changed:
        console.print(f"\n[bold]Character changes ({len(changed)}):[/]")
        for d in changed[:50]:
            tag = "[green](new)[/]" if d.is_new else ""
            console.print(f"  {d.name} {tag}")
            for f_, (old, new) in d.changes.items():
                console.print(f"    {f_}: {old} → {new}")
            if d.extras:
                # Inline-print simple extras (cube/treasure/costume),
                # break out OL gear separately for readability.
                gear = d.extras.pop("ol_gear", None) if isinstance(d.extras, dict) else None
                if d.extras:
                    console.print(f"    [dim]extras:[/] {d.extras}")
                if gear:
                    for slot_info in gear:
                        bn = " | ".join(slot_info.get("bonuses", []))
                        if "stats" in slot_info:
                            console.print(
                                f"    [dim]{slot_info['slot']:5s} {slot_info['name']:25s} {slot_info['stats']}  →  {bn}[/]"
                            )
                        else:
                            console.print(f"    [dim]{slot_info['slot']:5s} {slot_info['name']}[/]")
        if len(changed) > 50:
            console.print(f"  [dim]... +{len(changed) - 50} more[/]")
    else:
        console.print("[dim]no per-character changes[/]")
    if extras_only:
        console.print(
            f"\n[dim]{len(extras_only)} chars have unchanged columns but captured extras (cube/treasure/costume/arena_combat)[/]"
        )

    if report.unmatched:
        console.print(f"\n[yellow]unmatched ({len(report.unmatched)}):[/] {report.unmatched[:10]}")
        console.print(
            "[dim]  → add a stub via:[/] "
            "nikkeoptimizer stub-character --from-shiftyspad <Name>"
        )
    if report.stubs_awaiting_refresh:
        console.print(
            f"\n[yellow]stubs awaiting Prydwen refresh "
            f"({len(report.stubs_awaiting_refresh)}):[/] "
            f"{report.stubs_awaiting_refresh}"
        )
        console.print(
            "[dim]  → when Prydwen catches up:[/] "
            "nikkeoptimizer refresh --name <X>"
        )
    if report.fuzzy_warnings:
        console.print(f"\n[yellow]fuzzy matches:[/]")
        for w in report.fuzzy_warnings[:20]:
            console.print(f"  {w}")

    if apply:
        console.print(f"\n[bold green]applied:[/] {report.matched} character rows synced")
    else:
        console.print(f"\n[dim]dry run — pass --apply to write changes[/]")


# ---------------------------------------------------------------------------
# BlablaLink player lookup (SKILL.md flow as a Python scraper)
# ---------------------------------------------------------------------------


@app.command("lookup-players")
def lookup_players_cmd(
    input_path: Path = typer.Argument(
        ...,
        help="Path to player list (CSV-ish: Rank,Name,lvl  or  Name,lvl  or  Name, Lv.XXX). "
             "Use '-' to read from stdin.",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output CSV path. Defaults to ~/Downloads/nikke_player_lookup_YYYY-MM-DD.csv",
    ),
    tolerance: int = typer.Option(
        15, "--tolerance", "-t",
        help="Level-match tolerance ±N (SKILL.md default 10; widen to 15+ for older lists).",
    ),
    show_browser: bool = typer.Option(
        False, "--show-browser", help="Run Chromium with a visible window (default: headless).",
    ),
    only: Optional[str] = typer.Option(
        None, "--only", help="Comma-separated subset of names to look up (case-insensitive).",
    ),
) -> None:
    """Look up Nikke players on BlablaLink (NA), verify by level, export CSV.

    Requires a logged-in BlablaLink session — run ``shiftyspad-login``
    first if you haven't. Cookies persist ~30 days in the Playwright
    profile.

    Output schema (31 columns) matches the JS skill's CSV. Status values:
    Found / "No Search Results" / "Not On NA" / "Level Mismatch".
    """
    import sys
    from ..data.scrapers.blablalink_user_lookup import (
        CSV_COLUMNS,
        PlayerQuery,
        default_csv_path,
        parse_player_input,
        run_lookup,
        write_csv,
    )

    if str(input_path) == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(input_path).read_text(encoding="utf-8")
    queries = parse_player_input(raw)
    if not queries:
        console.print("[red]no parseable players in input[/]")
        raise typer.Exit(1)

    if only:
        wanted = {n.strip().upper() for n in only.split(",") if n.strip()}
        queries = [q for q in queries if q.name.upper() in wanted]
        if not queries:
            console.print(f"[red]--only filter excluded every player[/]")
            raise typer.Exit(1)

    out_path = output or default_csv_path()
    console.print(f"[cyan]players:[/] {len(queries)}")
    console.print(f"[cyan]tolerance:[/] ±{tolerance}")
    console.print(f"[cyan]output:[/] {out_path}")
    console.print()

    rows: list[dict[str, object]] = []
    status_counts: dict[str, int] = {}

    def on_progress(p) -> None:
        if p.status in {"searching", "fetching-home"}:
            console.print(
                f"  [{p.index+1:2d}/{p.total}] [dim]{p.name:<20s}[/] {p.status}…"
            )
            return
        # terminal status for this player
        colour = {
            "Found": "green",
            "No Search Results": "yellow",
            "Not On NA": "yellow",
            "Level Mismatch": "yellow",
        }.get(p.status, "red")
        console.print(
            f"  [{p.index+1:2d}/{p.total}] [bold]{p.name:<20s}[/] "
            f"[{colour}]{p.status}[/]"
        )
        status_counts[p.status] = status_counts.get(p.status, 0) + 1

    rows = run_lookup(queries, tolerance=tolerance, headless=not show_browser,
                     on_progress=on_progress)

    write_csv(rows, out_path)
    console.print()
    console.print(f"[bold green]wrote[/] {out_path}  ({len(rows)} rows, {len(CSV_COLUMNS)} cols)")
    if status_counts:
        summary = "  ".join(f"{k}: {v}" for k, v in sorted(status_counts.items()))
        console.print(f"[dim]{summary}[/]")

    fetchable = [r for r in rows if r.get("Worth Fetching") == "yes"]
    if fetchable:
        console.print()
        console.print(f"[bold cyan]worth fetching ({len(fetchable)}):[/]")
        for r in fetchable:
            roster = r.get("My Nikkes Status", "?")
            outpost = r.get("Outpost Info Status", "?")
            console.print(
                f"  [bold]{r['Player Name']:<14s}[/] "
                f"Lv.{r['Actual Level']:<4}  "
                f"roster=[{'green' if roster=='Public' else 'yellow'}]{roster}[/] "
                f"outpost=[{'green' if outpost=='Public' else 'yellow'}]{outpost}[/]  "
                f"[dim]{r['UID']}[/]"
            )
        console.print()
        console.print("[dim]hand off to fetch-shiftyspad:[/]")
        for r in fetchable:
            console.print(f"  nikkeoptimizer fetch-shiftyspad {r['UID']}")


def _resolve_player_data_targets(
    target: str, engine, console_=None,
) -> list[tuple[int, Path, int]]:
    """Resolve a CLI ``target`` string into player_data tournaments.

    The argument is interpreted as a beta season number first; if no
    player_data tournaments belong to that season, falls back to
    treating it as a ``PromoTournament.id``. Used by both
    ``inspect-tournament-players`` and ``fetch-tournament-players``.
    """
    from ..data.models import PromoTournament
    from ..data.seasons import parse_season_number
    from ..roster.promo_tournament_ingest import (
        FORMAT_PROMO_PLAYER_DATA,
        tournament_format,
    )

    if not target.isdigit():
        if console_:
            console_.print(
                f"[red]target must be a tournament id or season number, got {target!r}[/]"
            )
        raise typer.Exit(1)
    target_n = int(target)

    targets: list[tuple[int, Path, int]] = []
    with get_session(engine) as session:
        all_pd = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_PROMO_PLAYER_DATA
        ]
        for t in all_pd:
            tn = parse_season_number(Path(t.storage_root).parent.name)
            if tn == target_n:
                targets.append((t.id, Path(t.storage_root), target_n))
        if not targets:
            t = session.get(PromoTournament, target_n)
            if (
                t is not None
                and tournament_format(t.storage_root) == FORMAT_PROMO_PLAYER_DATA
            ):
                season_n = parse_season_number(Path(t.storage_root).parent.name)
                targets.append((t.id, Path(t.storage_root), season_n or 0))
    return targets


@app.command("inspect-tournament-players")
def inspect_tournament_players_cmd(
    target: str = typer.Argument(
        ...,
        help="Tournament id (matches PromoTournament.id) OR beta season number.",
    ),
    show_all: bool = typer.Option(
        False, "--all", "-a",
        help="Show every raw record (top + bottom both visible) instead of "
             "the deduped per-player view. Useful for spotting OCR disagreements "
             "between the two sides of the same match.",
    ),
    low_confidence_only: bool = typer.Option(
        False, "--low-confidence-only",
        help="Filter to rows likely to be problematic: player_name OCR "
             "confidence < 0.7 OR fewer than 5 character names matched.",
    ),
    player: Optional[str] = typer.Option(
        None, "--player",
        help="Filter to one player name (case-insensitive substring match).",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Dump the raw players_lookup.json sidecar contents.",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Inspect a player_data tournament's OCR output without touching the DB.

    Reads the ``players_lookup.json`` + ``players_lookup_status.json``
    sidecars and renders a per-player audit table — every header field
    (name / level / team CP), every captured character, plus the scrape
    status when ``fetch-tournament-players`` has already run.

    Strictly read-only. The companion visual view is the
    ``/promo/<tournament_id>`` page in the web UI.

    Examples:

      \b
      nikkeoptimizer inspect-tournament-players 29
      nikkeoptimizer inspect-tournament-players 29 --low-confidence-only
      nikkeoptimizer inspect-tournament-players 29 --player BBB
      nikkeoptimizer inspect-tournament-players 29 --all   # both top+bottom rows
      nikkeoptimizer inspect-tournament-players 29 --json
    """
    import json as _json

    from ..roster.promo_tournament_player_data import read_sidecar
    from ..roster.promo_tournament_player_data_scrape import (
        STATUS_FOUND,
        STATUS_PRIVATE_BOTH,
        StatusSidecar,
        dedupe_by_player,
    )

    engine = make_engine(db)
    init_db(engine)
    targets = _resolve_player_data_targets(target, engine, console_=console)
    if not targets:
        console.print(
            f"[yellow]no player_data tournaments matched target={target!r}[/]"
        )
        raise typer.Exit(0)

    player_filter = player.strip().lower() if player else None

    for tid, root, season_n in targets:
        console.rule(
            f"[bold]Tournament {tid}[/]  [dim]({root.name})[/]  season {season_n}"
        )
        sidecar = read_sidecar(root)
        if sidecar is None:
            console.print(
                f"[yellow]no players_lookup.json at {root} — "
                f"run `nikkeoptimizer ingest-tournaments` first[/]"
            )
            continue

        # --json: dump and bail.
        if as_json:
            console.print(_json.dumps({
                "season_number": sidecar.season_number,
                "tournament_id": sidecar.tournament_id,
                "storage_root": sidecar.storage_root,
                "players": [
                    {
                        "group_no": p.group_no, "match_no": p.match_no,
                        "side": p.side, "screenshot_id": p.screenshot_id,
                        "player_name": p.player_name,
                        "player_name_confidence": p.player_name_confidence,
                        "player_level": p.player_level, "team_cp": p.team_cp,
                        "chars": [
                            {"slot": c.slot, "name": c.name, "name_raw": c.name_raw,
                             "name_match_score": c.name_match_score,
                             "cp": c.cp, "lb": c.lb, "core": c.core}
                            for c in p.chars
                        ],
                    }
                    for p in sidecar.players
                ],
            }, indent=2))
            continue

        status = StatusSidecar.load_or_init(
            root, tournament_id=tid, season_number=season_n,
        )

        records = sidecar.players if show_all else dedupe_by_player(sidecar.players)
        # Sort: deduped → by name; raw → by (group, match, side).
        if show_all:
            records.sort(key=lambda r: (r.group_no, r.match_no, r.side))
        else:
            records.sort(key=lambda r: (r.player_name or "").lower())

        # Filters.
        def _is_low_conf(r) -> bool:
            if r.player_name_confidence is not None and r.player_name_confidence < 0.7:
                return True
            char_hits = sum(1 for c in r.chars if c.name is not None)
            return char_hits < 5

        if low_confidence_only:
            records = [r for r in records if _is_low_conf(r)]
        if player_filter:
            records = [r for r in records if player_filter in (r.player_name or "").lower()]

        # Summary line.
        all_unique = {p.player_name for p in sidecar.players if p.player_name}
        console.print(
            f"[dim]Sidecar:[/] {root / 'players_lookup.json'}\n"
            f"[dim]Raw rows:[/] {len(sidecar.players)}    "
            f"[dim]Unique players:[/] {len(all_unique)}    "
            f"[dim]Showing:[/] {len(records)}"
            + ("  [dim](deduped)[/]" if not show_all else "  [dim](all rows)[/]")
        )

        if not records:
            console.print("  [dim](no rows match the filters)[/]")
            continue

        table = Table(show_header=True, header_style="bold", padding=(0, 1))
        table.add_column("Player", style="white", no_wrap=True)
        table.add_column("Lv", justify="right")
        table.add_column("Team CP", justify="right")
        table.add_column("Chars (1..5)", style="dim")
        table.add_column("Src", style="dim", no_wrap=True)
        table.add_column("Scrape", no_wrap=True)
        table.add_column("OCR", no_wrap=True)

        for r in records:
            name = r.player_name or "[red]?[/]"
            conf = r.player_name_confidence
            char_names = [c.name or f"[red]?{c.slot}[/]" for c in r.chars]
            char_hits = sum(1 for c in r.chars if c.name is not None)

            ocr_tag = "[green]ok[/]"
            if conf is not None and conf < 0.7:
                ocr_tag = f"[yellow]conf {conf:.2f}[/]"
            if char_hits < 5:
                ocr_tag = f"[yellow]chars {char_hits}/5[/]" if ocr_tag == "[green]ok[/]" else (
                    ocr_tag + f" [yellow]{char_hits}/5[/]"
                )

            scrape_cell = "[dim]—[/]"
            if r.player_name:
                rec = status.players.get(r.player_name)
                if rec is not None:
                    if rec.status == STATUS_FOUND and rec.snapshot_id is not None:
                        scrape_cell = f"[green]found[/] [dim]#{rec.snapshot_id}[/]"
                    elif rec.status == STATUS_PRIVATE_BOTH:
                        scrape_cell = f"[magenta]private_both[/]"
                    else:
                        scrape_cell = f"[yellow]{rec.status}[/]"

            level_cell = str(r.player_level) if r.player_level is not None else "[red]?[/]"
            cp_cell = f"{r.team_cp:,}" if r.team_cp is not None else "[red]?[/]"

            table.add_row(
                name,
                level_cell,
                cp_cell,
                ", ".join(char_names),
                f"g{r.group_no}/m{r.match_no}/{r.side[:3]}",
                scrape_cell,
                ocr_tag,
            )
        console.print(table)

        # Issue rollup at the bottom — most-actionable signal first.
        if not low_confidence_only and not player_filter:
            issues: list[str] = []
            no_name = [r for r in sidecar.players if not r.player_name]
            no_level = [r for r in sidecar.players
                        if r.player_name and r.player_level is None]
            low_conf = [r for r in dedupe_by_player(sidecar.players)
                        if r.player_name_confidence is not None
                        and r.player_name_confidence < 0.7]
            partial_chars = [
                r for r in dedupe_by_player(sidecar.players)
                if sum(1 for c in r.chars if c.name is not None) < 5
            ]
            if no_name:
                issues.append(f"[red]{len(no_name)}[/] row(s) missing player_name (will be skipped by scrape)")
            if no_level:
                issues.append(f"[red]{len(no_level)}[/] player(s) missing level (will be skipped by scrape)")
            if low_conf:
                issues.append(
                    f"[yellow]{len(low_conf)}[/] player(s) with OCR confidence < 0.7"
                )
            if partial_chars:
                issues.append(
                    f"[yellow]{len(partial_chars)}[/] player(s) with < 5 matched character names "
                    f"(snapshot will be sparse)"
                )
            if issues:
                console.print()
                console.print("[bold]Issues:[/]")
                for line in issues:
                    console.print(f"  · {line}")


@app.command("fetch-tournament-players")
def fetch_tournament_players_cmd(
    target: str = typer.Argument(
        ...,
        help="Tournament id (matches PromoTournament.id) OR beta season number. "
             "When a season is given, every player_data tournament in that "
             "season is processed in turn.",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Run BlablaLink lookups + write snapshots. Default is dry-run "
             "(prints the plan without touching the network or DB).",
    ),
    only: Optional[str] = typer.Option(
        None, "--only",
        help="Comma-separated subset of player names (case-insensitive).",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Re-run players whose status is already 'found' in the status sidecar.",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Cap the work list at N players (post-sort, post-filter). Use as "
             "a pilot run: `--apply --limit 5` exercises the full pipeline "
             "(lookup + snapshot + /promo/players page) on a handful of "
             "players before committing to the full bracket. Already-found "
             "players still count toward N unless --force is also passed.",
    ),
    tolerance: int = typer.Option(
        15, "--tolerance", "-t",
        help="Level-match tolerance for the BlablaLink search.",
    ),
    max_minutes: float = typer.Option(
        90.0, "--max-minutes",
        help="Soft watchdog — abort after this many minutes (mid-run snapshot "
             "writes are persisted; next run resumes).",
    ),
    show_browser: bool = typer.Option(
        False, "--show-browser",
        help="Open Chromium with a visible window (default: headless).",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Scrape BlablaLink for the players in a player_data tournament's
    sidecar and write per-player Champions Arena ``RosterSnapshot`` rows.

    Requires a logged-in BlablaLink session — run ``shiftyspad-login``
    first if you haven't. The ingest pass that produced the sidecar
    must already have run (``nikkeoptimizer ingest-tournaments`` or the
    auto-import daemon).

    Examples:

      \b
      nikkeoptimizer fetch-tournament-players 29 --apply
      nikkeoptimizer fetch-tournament-players 12 --only "BBB,ZTARMAN" --apply
      nikkeoptimizer fetch-tournament-players 29 --force --apply
    """
    from ..roster.promo_tournament_player_data_scrape import (
        STATUS_FOUND,
        STATUS_PRIVATE_BOTH,
        ScrapeProgress,
        build_plan,
        scrape_tournament_players,
    )
    from ..roster.promo_tournament_player_data import read_sidecar

    only_set = (
        {n.strip() for n in only.split(",") if n.strip()} if only else None
    )

    engine = make_engine(db)
    init_db(engine)

    targets = _resolve_player_data_targets(target, engine, console_=console)
    if not targets:
        console.print(
            f"[yellow]no player_data tournaments matched target={target!r} "
            f"(tried as season number, then as tournament id)[/]"
        )
        raise typer.Exit(0)

    for tid, root, season_n in targets:
        console.print(f"[cyan]tournament {tid}[/] [dim]({root.name})[/] season={season_n}")
        sidecar = read_sidecar(root)
        if sidecar is None:
            console.print(
                f"  [yellow]missing players_lookup.json — run ingest first[/]"
            )
            continue

        def on_progress(p: ScrapeProgress) -> None:
            if p.stage in {"searching", "fetching", "snapshotting"}:
                console.print(
                    f"  [{p.index+1:2d}/{p.total}] [dim]{p.name:<20s}[/] {p.stage}…"
                )
                return
            colour = {
                STATUS_FOUND: "green",
                STATUS_PRIVATE_BOTH: "yellow",
            }.get(p.stage, "red")
            extra = ""
            if p.record is not None and p.record.snapshot_id is not None:
                extra = f" snapshot={p.record.snapshot_id}"
            console.print(
                f"  [{p.index+1:2d}/{p.total}] [bold]{p.name:<20s}[/] "
                f"[{colour}]{p.stage}[/]{extra}"
            )

        if not apply:
            from ..roster.promo_tournament_player_data_scrape import (
                StatusSidecar,
            )
            status = StatusSidecar.load_or_init(
                root, tournament_id=tid, season_number=season_n,
            )
            plan = build_plan(
                sidecar, status, force=force, only=only_set, limit=limit,
            )
            cap_note = f" (capped at {limit})" if limit is not None else ""
            console.print(f"  [bold]plan:[/] {len(plan)} player(s){cap_note}")
            for entry in plan[:50]:
                console.print(
                    f"    [dim]Lv.{entry.expected_level:<4}[/] {entry.name:<20s} "
                    f"chars={','.join(entry.char_names) or '∅'}"
                )
            if len(plan) > 50:
                console.print(f"    [dim]…and {len(plan) - 50} more[/]")
            console.print(
                f"  [dim]pass --apply to fetch + snapshot ({len(plan)} player(s))[/]"
            )
            continue

        status = scrape_tournament_players(
            root,
            season_number=season_n,
            tournament_id=tid,
            apply=True,
            only=only_set,
            force=force,
            limit=limit,
            tolerance=tolerance,
            max_minutes=max_minutes,
            headless=not show_browser,
            db_path=db,
            on_progress=on_progress,
        )
        # Per-status counts for the summary line.
        counts: dict[str, int] = {}
        for rec in status.players.values():
            counts[rec.status] = counts.get(rec.status, 0) + 1
        summary = "  ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
        console.print(f"  [bold]done[/] — {summary}")


@app.command("ingest-rookie-arena")
def ingest_rookie_arena_cmd(
    staging: Path = typer.Option(
        Path("incoming-captures/rookie_arena"),
        "--staging",
        help="Staging dir holding <YYYY-MM-DD>_<HHMMSS>/battle_N/ runs.",
    ),
    archive: Optional[Path] = typer.Option(
        None, "--archive",
        help="Archive root. Defaults to <repo>/captures/.",
    ),
    move: bool = typer.Option(
        False, "--move",
        help="Delete staging files after a successful copy.",
    ),
    no_ocr: bool = typer.Option(
        False, "--no-ocr",
        help="Skip the OCR pass after relocation (useful when re-running "
             "the file copy but extractions are already current).",
    ),
    force_ocr: bool = typer.Option(
        False, "--force-ocr",
        help="Re-OCR existing screenshots (bypasses the has_extractions skip).",
    ),
    only_run: Optional[str] = typer.Option(
        None, "--only-run",
        help="Filter to ONE staging-folder name, e.g. 2026-05-17_052345. "
             "Phase 1 single-match validation uses this.",
    ),
    only_battle: Optional[int] = typer.Option(
        None, "--only-battle",
        help="Filter to one battle_N (1..5). Pair with --only-run for "
             "a single-battle ingest.",
    ),
    scrape: bool = typer.Option(
        False, "--scrape",
        help="Run BlablaLink scrape for every rookie run after OCR + "
             "ArenaMatch build. Default off — the daemon opts in when "
             "cookies are present.",
    ),
    max_scrape_minutes: float = typer.Option(
        90.0, "--max-scrape-minutes",
        help="Per-tournament soft watchdog for the scrape pass (only "
             "when --scrape is set).",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Ingest Rookie Arena daily runs into the captures archive + DB.

    Folder shape under ``--staging``:

      \b
      <YYYY-MM-DD>_<HHMMSS>/
        battle_1/
          opponent.png   (optional — older runs lack this)
          loadout.png
          results.png
        battle_2/
        ...battle_5/

    Idempotent — natural keys are (tournament.storage_root,
    match.match_no, screenshot.kind), so re-running on an unchanged
    staging dir is a no-op modulo any newly-added files. The OCR pass
    only touches screenshots that don't yet have extracted fields.

    Examples:

      \b
      # Phase 1 single-battle validation:
      nikkeoptimizer ingest-rookie-arena --only-run 2026-05-17_052345 --only-battle 1

      # Full ingest of every run currently in staging:
      nikkeoptimizer ingest-rookie-arena
    """
    from ..roster.rookie_arena_ingest import ingest_rookie_root

    stats = ingest_rookie_root(
        staging_root=staging,
        archive_root=archive,
        move=move,
        db_path=db,
        ocr=not no_ocr,
        force_ocr=force_ocr,
        only_run=only_run,
        only_battle=only_battle,
        scrape_rookie_opponents=scrape,
        max_scrape_minutes=max_scrape_minutes,
    )
    console.print(f"[bold]Ingest complete:[/] {stats}")


@app.command("fetch-rookie-opponents")
def fetch_rookie_opponents_cmd(
    target: str = typer.Argument(
        ...,
        help="Rookie run identifier. Accepts a PromoTournament.id (e.g. 7), "
             "a date string (YYYY-MM-DD — runs all daily runs on that date), "
             "or a staging-folder name (e.g. 2026-05-17_052345).",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Run BlablaLink lookups + write RookieArenaSnapshot rows. "
             "Default is dry-run.",
    ),
    only: Optional[str] = typer.Option(
        None, "--only",
        help="Comma-separated subset of opponent names (case-insensitive).",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Re-run opponents already marked 'found' in the status sidecar.",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Cap the work list at N opponents. Use --apply --limit 1 for "
             "a pilot smoke test.",
    ),
    max_minutes: float = typer.Option(
        90.0, "--max-minutes",
        help="Soft watchdog — abort after N minutes (mid-run snapshots persist).",
    ),
    show_browser: bool = typer.Option(
        False, "--show-browser",
        help="Open Chromium with a visible window (default: headless).",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Scrape BlablaLink for the opponents in a Rookie Arena daily run
    and write per-opponent ``RookieArenaSnapshot`` rows.

    Requires ``shiftyspad-login``. Per-opponent fetch model: sparse —
    only the 5 Nikkes from the opponent's loadout get their detail XHRs
    pulled, not the full BlablaLink roster.

    Tolerance is adaptive: ±5 when the opponent's level came from
    opponent.png, ±20 when estimated from my level (older runs without
    opponent.png).

    Examples:

      \b
      nikkeoptimizer fetch-rookie-opponents 7 --apply --limit 1   # pilot today
      nikkeoptimizer fetch-rookie-opponents 7 --apply             # full today
      nikkeoptimizer fetch-rookie-opponents 2026-05-17 --apply    # all runs that date
      nikkeoptimizer fetch-rookie-opponents 2026-05-15_121041 --apply  # by folder name
    """
    from datetime import date as _date_cls
    from pathlib import Path as _P

    from ..data.models import PromoTournament
    from ..roster.promo_tournament_ingest import (
        FORMAT_ROOKIE_ARENA,
        tournament_format,
    )
    from ..roster.rookie_arena_scrape import (
        STATUS_FOUND,
        STATUS_PRIVATE_BOTH,
        ScrapeProgress,
        build_plan,
        load_actual_level_cache,
        scrape_rookie_run,
        RookieStatusSidecar,
    )
    from ..roster.rookie_arena_sidecar import read_sidecar

    only_set = (
        {n.strip() for n in only.split(",") if n.strip()} if only else None
    )

    engine = make_engine(db)
    init_db(engine)

    # Resolve target → list of rookie tournaments.
    targets: list[PromoTournament] = []
    with get_session(engine) as session:
        all_pd = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_ROOKIE_ARENA
        ]
        if target.isdigit():
            tid = int(target)
            t = session.get(PromoTournament, tid)
            if t is not None and tournament_format(t.storage_root) == FORMAT_ROOKIE_ARENA:
                targets.append(t)
        else:
            # Try as date (YYYY-MM-DD) or as staging-folder name.
            try:
                d = _date_cls.fromisoformat(target)
                targets.extend(
                    t for t in all_pd if t.capture_date == d
                )
            except ValueError:
                # Try matching the storage folder's basename.
                targets.extend(
                    t for t in all_pd if _P(t.storage_root).name == target
                )

    if not targets:
        console.print(
            f"[yellow]no rookie runs matched target={target!r} "
            f"(tried as tournament id, date, and folder name)[/]"
        )
        raise typer.Exit(0)

    for tournament in targets:
        root = Path(tournament.storage_root)
        console.print(
            f"[cyan]rookie run {tournament.id}[/] "
            f"[dim]({root.name})[/] date={tournament.capture_date}"
        )
        sidecar = read_sidecar(root)
        if sidecar is None:
            console.print(
                f"  [yellow]missing players_lookup.json — run "
                f"ingest-rookie-arena first[/]"
            )
            continue

        def on_progress(p: ScrapeProgress) -> None:
            if p.stage in {"searching", "fetching", "snapshotting"}:
                console.print(
                    f"  [{p.index+1:2d}/{p.total}] [dim]{p.name:<14s}[/] {p.stage}…"
                )
                return
            colour = {
                STATUS_FOUND: "green",
                STATUS_PRIVATE_BOTH: "yellow",
            }.get(p.stage, "red")
            extra = ""
            if p.record is not None and p.record.snapshot_id is not None:
                extra = f" snap=#{p.record.snapshot_id}"
            console.print(
                f"  [{p.index+1:2d}/{p.total}] [bold]{p.name:<14s}[/] "
                f"[{colour}]{p.stage}[/]{extra}"
            )

        if not apply:
            status = RookieStatusSidecar.load_or_init(
                root, run_id=tournament.id,
                run_date=tournament.capture_date.isoformat() if tournament.capture_date else "",
            )
            cache = load_actual_level_cache(root)
            plan = build_plan(
                sidecar, status,
                force=force, only=only_set, limit=limit,
                actual_level_cache=cache,
            )
            cap = f" (capped at {limit})" if limit is not None else ""
            console.print(
                f"  [bold]plan:[/] {len(plan)} opponent(s){cap}  "
                f"[dim]cache: {len(cache)} prior-found level(s)[/]"
            )
            for e in plan[:50]:
                console.print(
                    f"    [dim]Lv.{e.expected_level:<4}[/] ±{e.tolerance:<2} "
                    f"[dim]src={e.level_source:25s}[/] {e.name:<14s} "
                    f"team={','.join(e.char_names) or '∅'}"
                )
            console.print(f"  [dim]pass --apply to scrape ({len(plan)} opponent(s))[/]")
            continue

        status = scrape_rookie_run(
            root,
            tournament=tournament,
            apply=True,
            only=only_set,
            force=force,
            limit=limit,
            max_minutes=max_minutes,
            headless=not show_browser,
            db_path=db,
            on_progress=on_progress,
        )
        counts: dict[str, int] = {}
        for rec in status.players.values():
            counts[rec.status] = counts.get(rec.status, 0) + 1
        summary = "  ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
        console.print(f"  [bold]done[/] — {summary}")


@app.command("build-champion-matches")
def build_champion_matches_cmd(
    only_tournament: Optional[int] = typer.Option(
        None, "--only-tournament", "-t",
        help="Build only for this tournament_id (skip others).",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Build ``ArenaMatch`` rows from Champions duel screenshots.

    One row per duel round (so a Champion match contributes up to 5
    rows, keyed by ``session_id = champion-pm{promo_match_id}``).
    Idempotent — re-running upserts in place. Disconnect detection +
    snapshot FK linkage happen automatically.

    Use after a fresh ``backfill-extractions`` pass that populated
    new region slugs, or after a ``fetch-shiftyspad --snapshot`` that
    landed new ``RosterSnapshot`` rows you want backfilled into the
    FK columns.
    """
    from ..roster.champion_arena_match import (
        build_arena_matches_for_all_champion_tournaments,
    )

    engine = make_engine(db)
    init_db(engine)
    stats = build_arena_matches_for_all_champion_tournaments(
        engine, only_tournament_id=only_tournament,
    )
    console.print(
        f"[bold green]Build complete[/]\n"
        f"  rows touched:               {stats.rows_touched}\n"
        f"  rows with outcome:          {stats.rows_with_outcome}\n"
        f"  rows fully snapshotted:     [bold]{stats.rows_fully_snapshotted}[/]"
        f" [dim](both player snapshots linked)[/]\n"
        f"  rows user_snapshot only:    {stats.rows_user_snapshot_only}\n"
        f"  rows opp_snapshot only:     {stats.rows_opp_snapshot_only}"
    )


@app.command("arena-matches")
def arena_matches_cmd(
    mode: Optional[str] = typer.Option(
        None, "--mode",
        help="Filter to 'rookie' or 'champion'. Default: all modes.",
    ),
    complete_snapshots: bool = typer.Option(
        False, "--complete-snapshots",
        help="Only show matches where BOTH user_snapshot_id and "
             "opponent_snapshot_id are set — i.e. full roster context "
             "for both players at the time of the match.",
    ),
    with_outcome: bool = typer.Option(
        False, "--with-outcome",
        help="Only show matches with a populated outcome.",
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Cap output rows."),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """List ``ArenaMatch`` rows with snapshot + outcome filters.

    Match-level (Champion duel) scoring derived by grouping on
    ``session_id`` — each session yields up to 5 round rows.
    ``--complete-snapshots`` is the "we have accurate roster data for
    both players at the time of this match" filter.
    """
    from ..data.models import ArenaMatch

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        q = select(ArenaMatch)
        if mode:
            q = q.where(ArenaMatch.mode == mode)
        if complete_snapshots:
            q = q.where(
                ArenaMatch.user_snapshot_id.is_not(None),
                ArenaMatch.opponent_snapshot_id.is_not(None),
            )
        if with_outcome:
            q = q.where(ArenaMatch.outcome.is_not(None))
        rows = session.exec(q).all()

    # Group Champion rows into sessions for human-readable summary.
    from collections import defaultdict
    by_session: dict = defaultdict(list)
    for r in rows:
        by_session[r.session_id or f"_solo_{r.id}"].append(r)

    n_sessions = len(by_session)
    n_rows = len(rows)
    fully_snap = sum(
        1 for r in rows
        if r.user_snapshot_id is not None and r.opponent_snapshot_id is not None
    )
    console.print(
        f"[bold]{n_rows}[/] rows in [bold]{n_sessions}[/] session(s)"
        f"  ·  fully-snapshotted rows: [bold green]{fully_snap}[/]"
    )

    shown = 0
    for sid, rs in sorted(by_session.items()):
        if shown >= limit:
            console.print(f"  [dim]… {n_sessions - shown} more session(s) (use --limit)[/]")
            break
        rs = sorted(rs, key=lambda r: r.round_index or 0)
        first = rs[0]
        w = sum(1 for r in rs if r.outcome == "win")
        l = sum(1 for r in rs if r.outcome == "loss")
        both = (
            first.user_snapshot_id is not None
            and first.opponent_snapshot_id is not None
        )
        snap_tag = "[green]✓ both[/]" if both else (
            "[yellow]user only[/]" if first.user_snapshot_id is not None else (
                "[yellow]opp only[/]" if first.opponent_snapshot_id is not None
                else "[dim]none[/]"
            )
        )
        console.print(
            f"  {sid:30s} {first.user_username!r:18s} vs {first.opponent_username!r:18s} "
            f"{w}W-{l}L  snap={snap_tag}"
        )
        shown += 1


@app.command("baseline-sim")
def baseline_sim_cmd(
    mode: Optional[str] = typer.Option(
        None, "--mode", help="Filter to 'rookie' or 'champion'.",
    ),
    show_misses: bool = typer.Option(
        False, "--misses",
        help="Only print the mispredicted matches (for triage).",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Predicted vs actual winner across snapshot=both ArenaMatch rows.

    Runs ``damage.resolve`` over every match where we have snapshot
    data for both sides (Champions: ``RosterSnapshot`` FK; Rookie:
    opponent ``RookieArenaSnapshot`` + live ``OwnedCharacter`` for
    user). The shorter ``seconds_to_clear_defender`` side is the
    predicted winner; verdict is compared to the recorded outcome.
    """
    from ..simulator.baseline import run_baseline

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        report = run_baseline(session)

    preds = report.predictions
    if mode in ("rookie", "champion"):
        preds = [p for p in preds if p.mode == mode]

    n_scored = sum(1 for p in preds if p.correct is not None)
    n_right = sum(1 for p in preds if p.correct is True)
    pct = (n_right / n_scored) if n_scored else 0.0
    console.print(
        f"[bold]Baseline:[/] {n_right}/{n_scored} = "
        f"[bold green]{pct:.1%}[/]   "
        f"[dim]({len(preds)} total predictions; "
        f"{len(preds) - n_scored} skipped: no outcome / tie)[/]"
    )
    for m, (c, t) in sorted(report.by_mode().items()):
        if mode and m != mode:
            continue
        console.print(f"  {m:8s} {c}/{t} = {c/t:.1%}")
    console.print()

    rows = [
        p for p in sorted(preds, key=lambda p: (p.mode, p.match_id))
        if (not show_misses) or (p.correct is False)
    ]
    for p in rows:
        if p.correct is True:
            mark = "[green]✓[/]"
        elif p.correct is False:
            mark = "[red]✗[/]"
        else:
            mark = "[dim]?[/]"
        margin = abs(p.user_clear_sec - p.opp_clear_sec)
        console.print(
            f"  {mark} m{p.match_id:4d} {p.mode:8s} "
            f"r{p.round_index or '-'}  "
            f"actual=[bold]{p.actual_outcome or '?':4s}[/]  "
            f"pred=[bold]{p.predicted_winner or 'tie':4s}[/]  "
            f"u_clear={p.user_clear_sec:6.1f}s  "
            f"opp_clear={p.opp_clear_sec:6.1f}s  "
            f"Δ={margin:5.1f}s  "
            f"[dim]u_dps={p.user_team_dps:>11,.0f}  opp_dps={p.opp_team_dps:>11,.0f}[/]"
        )


@app.command("refresh-self-from-rookie")
def refresh_self_from_rookie_cmd(
    target: Optional[str] = typer.Argument(
        None,
        help="Rookie tournament id (e.g. 7) to refresh from. Omit to "
             "refresh every rookie tournament that hasn't been refreshed yet.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Re-run even for tournaments already marked in the "
             "self-refresh state file.",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Override DB path."),
) -> None:
    """Sparse ``OwnedCharacter`` refresh from rookie loadouts.

    For each targeted rookie tournament, harvests the unique Nikke
    names from your ``user_team`` across the 5 battles and runs a
    sparse ShiftyPad fetch+sync against your configured
    ``intl_openid``. Idempotent via the per-tournament cooldown
    state file — re-running without ``--force`` is a no-op.

    Equivalent to ``fetch-shiftyspad <uid> --names "<loadout>"
    --apply`` but the loadout is auto-derived. This is the same
    hook the daemon runs after each rookie ingest.
    """
    from ..data.config import get_self_intl_openid
    from ..data.models import PromoTournament
    from ..roster.promo_tournament_ingest import (
        FORMAT_ROOKIE_ARENA, tournament_format,
    )
    from ..roster.rookie_self_refresh import (
        already_refreshed,
        refresh_self_from_rookie_tournament,
    )

    uid = get_self_intl_openid()
    if not uid:
        console.print(
            "[red]no intl_openid configured[/]\n"
            "Run [bold]nikkeoptimizer set-uid <base64-uid>[/] first."
        )
        raise typer.Exit(1)

    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        all_rookie = [
            t for t in session.exec(select(PromoTournament)).all()
            if tournament_format(t.storage_root) == FORMAT_ROOKIE_ARENA
        ]
        if target:
            if not target.isdigit():
                console.print(f"[red]target must be a tournament id[/]")
                raise typer.Exit(1)
            tid = int(target)
            targets = [t for t in all_rookie if t.id == tid]
            if not targets:
                console.print(
                    f"[yellow]no rookie tournament with id={tid}[/]"
                )
                raise typer.Exit(0)
        else:
            targets = [
                t for t in all_rookie
                if force or not already_refreshed(t.id)
            ]
            if not targets:
                console.print(
                    "[dim]every rookie tournament has already been "
                    "self-refreshed — pass --force to re-run[/]"
                )
                raise typer.Exit(0)

        for t in targets:
            console.print(
                f"[cyan]self-refresh[/] tournament={t.id} "
                f"[dim]({Path(t.storage_root).name})[/]"
            )
            report = refresh_self_from_rookie_tournament(
                session, t, intl_openid=uid, db_path=db, force=force,
            )
            if report.skipped_reason:
                console.print(f"  [yellow]skipped:[/] {report.skipped_reason}")
                continue
            if report.error:
                console.print(f"  [red]error:[/] {report.error}")
                continue
            console.print(
                f"  targeted={len(report.chars_targeted)} "
                f"unmapped={len(report.chars_unmapped)} "
                f"matched={report.chars_matched_in_sync} "
                f"updated={report.chars_updated}"
            )
            if report.chars_unmapped:
                console.print(
                    f"  [dim]unmapped names:[/] {report.chars_unmapped}"
                )


if __name__ == "__main__":
    app()
