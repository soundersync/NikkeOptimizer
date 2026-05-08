"""Minimal FastAPI app — manual-correction UI for cubes + arena captures.

Pages:
  GET  /                           dashboard (counts + links)
  GET  /cubes                      list every Cube row
  GET  /cubes/{id}                 edit form for one Cube
  POST /cubes/{id}                 save edits
  GET  /captures                   list ArenaMatch rows (filterable)
  GET  /captures/{id}              per-cell review for one capture
  POST /captures/{id}/cell         override a single cell's character

Server-rendered HTML only — no JS framework. Forms submit and redirect.

Launch with: ``nikkeoptimizer web --db <path> --library <portraits>``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select

from ..data.db import default_db_path, get_session, init_db, make_engine
from ..data.models import (
    ArenaMatch,
    Character,
    Cube,
    OwnedCharacter,
    PromoExtractedField,
    PromoGroup,
    PromoMatch,
    PromoMatchScreenshot,
    PromoTournament,
)
from ..roster.portrait_matcher import PortraitMatcher
from ..roster.promo_tournament_ingest import (
    FORMAT_DUEL,
    FORMAT_PROMO,
    tournament_format,
)
from ..roster.promo_tournament_regions import (
    KINDS as PROMO_KINDS,
    REFERENCE_IMAGE_SIZE as PROMO_REF_SIZE,
    regions_for_kind as promo_regions_for_kind,
)

log = logging.getLogger(__name__)


_THIS_DIR = Path(__file__).parent
_TEMPLATES_DIR = _THIS_DIR / "templates"
_STATIC_DIR = _THIS_DIR / "static"


def create_app(
    *,
    db_path: Optional[Path] = None,
    portrait_library: Optional[Path] = None,
) -> FastAPI:
    """Build a configured FastAPI instance bound to a specific DB.

    The portrait library is loaded once at startup (~30 seconds for 335
    embeddings) and reused for every per-cell rerun request.
    """
    app = FastAPI(title="NikkeOptimizer")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Slice #114 — split team notes into synergy lines vs everything else
    # so templates can render them in separate panels for clarity.
    def _synergy_notes(notes: list[str]) -> list[str]:
        return [n for n in (notes or []) if n.startswith("synergy:")]

    def _other_notes(notes: list[str]) -> list[str]:
        return [n for n in (notes or []) if not n.startswith("synergy:")]

    templates.env.filters["synergy_notes"] = _synergy_notes
    templates.env.filters["other_notes"] = _other_notes
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Promotion-tournament archive — served as static files. The mount
    # root is the canonical archive at <repo>/captures (created on
    # demand so the mount succeeds even before the first ingest).
    _PROMO_ROOT = Path(__file__).resolve().parents[3] / "captures"
    _PROMO_ROOT.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/promo-images",
        StaticFiles(directory=str(_PROMO_ROOT)),
        name="promo-images",
    )

    engine = make_engine(db_path)
    init_db(engine)
    app.state.engine = engine
    app.state.db_path = db_path
    app.state.matcher = None
    app.state.portrait_library = portrait_library

    # Slice #121 — robust screenshot path resolution. The DB stores
    # whatever path the importer was handed (often a relative
    # ``tests/fixtures/...`` path or an absolute path under
    # ``~/Library/Application Support/NikkeOptimizer/screenshots/``).
    # Files get moved/trimmed; the web server's cwd may not match the
    # import-time cwd. Fall through known dirs by basename + mode
    # before reporting 404.
    _MODE_TO_DIR = {
        "rookie": "Rookie_Arena",
        "special": "Special_Arena",
        "champion": "Champion_Arena",
    }

    def _resolve_screenshot_path(stored: str, mode: Optional[str]) -> Optional[Path]:
        candidates: list[Path] = []
        # 1. The path as stored — direct match if file is there.
        candidates.append(Path(stored))
        # 2. Same path but resolved relative to project root (handles
        # the "imported from project root, served from elsewhere" case).
        try:
            project_root = _THIS_DIR.parent.parent.parent  # web/.. = nikke_optimizer/.. = src/.. = root
            candidates.append(project_root / stored)
        except Exception:
            pass
        basename = Path(stored).name
        # Resolve the user-data dir from the active DB path (not
        # default_db_path) so tests with tmp DBs see their own dirs.
        try:
            db = app.state.db_path or default_db_path()
            data_dir = Path(db).parent
        except Exception:
            data_dir = None
        # 3. User's organized screenshots dir for this mode.
        if data_dir is not None:
            user_screens = data_dir / "screenshots"
            mode_dir = _MODE_TO_DIR.get((mode or "").lower())
            if mode_dir:
                candidates.append(user_screens / mode_dir / basename)
            # And a flat search across all mode dirs in case mode is wrong.
            for sub in _MODE_TO_DIR.values():
                candidates.append(user_screens / sub / basename)
            candidates.append(user_screens / "loose" / basename)
            # 4. Uploads dir under the resolved DB path (real-user uploads).
            candidates.append(data_dir / "uploads" / basename)
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate.resolve()
        return None

    def _matcher() -> Optional[PortraitMatcher]:
        if app.state.matcher is not None or app.state.portrait_library is None:
            return app.state.matcher
        with get_session(app.state.engine) as session:
            app.state.matcher = PortraitMatcher.from_portrait_library(
                app.state.portrait_library, session=session
            )
        log.info("loaded matcher with %d portraits", len(app.state.matcher))
        return app.state.matcher

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> Response:
        from ..data.config import detect_self_username, get_self_username
        from .capture_warnings import session_completeness_warnings

        configured_username = get_self_username()
        detected_username: Optional[tuple[str, int]] = None
        with get_session(engine) as session:
            n_chars = len(session.exec(select(Character)).all())
            n_cubes = len(session.exec(select(Cube)).all())
            captures = list(session.exec(select(ArenaMatch)).all())
            n_review = sum(1 for c in captures if c.needs_review)
            # First-run UX: when no username is configured but captures
            # exist, offer to auto-detect from the most-common
            # user_username value across rows.
            if configured_username is None and captures:
                detected_username = detect_self_username(session)
        # Session breakdown — drives the "Awaiting results" dashboard
        # tile so the user can spot pending predictions at a glance.
        session_matrices = session_completeness_warnings(
            captures, user_username=configured_username,
        )
        n_predictions_awaiting = sum(
            1 for sc in session_matrices.values()
            if sc.session_kind == "predictions"
        )
        n_complete_sessions = sum(
            1 for sc in session_matrices.values()
            if sc.session_kind == "complete"
        )
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "db_path": str(app.state.db_path or default_db_path()),
                "n_chars": n_chars,
                "n_cubes": n_cubes,
                "n_captures": len(captures),
                "n_review": n_review,
                "n_predictions_awaiting": n_predictions_awaiting,
                "n_complete_sessions": n_complete_sessions,
                "portrait_library": app.state.portrait_library,
                "configured_username": configured_username,
                "detected_username": detected_username,
            },
        )

    @app.post("/config/username")
    def config_save_username(name: str = Form(...)) -> Response:
        """Save the user's in-game name to ``config.json``."""
        from ..data.config import set_self_username

        cleaned = name.strip()
        if not cleaned:
            raise HTTPException(400, "username must not be empty")
        set_self_username(cleaned)
        return RedirectResponse(url="/", status_code=303)

    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------

    @app.post("/roster/snapshot")
    def roster_snapshot() -> Response:
        """Save a snapshot of the current OwnedCharacter state to
        ``<user_data_dir>/snapshots/<timestamp>.json`` for later diffing."""
        from ..roster.snapshots import take_snapshot
        with get_session(engine) as session:
            path = take_snapshot(session, label="manual")
        return RedirectResponse(
            url=f"/roster?snapshot_saved={path.name}", status_code=303
        )

    @app.get("/roster", response_class=HTMLResponse)
    def roster_list(
        request: Request,
        sort: str = "power",
        element: Optional[str] = None,
        burst: Optional[str] = None,
        snapshot_saved: Optional[str] = None,
    ) -> Response:
        """Browse owned characters. Sortable by power / name / sync; filterable by element/burst."""
        with get_session(engine) as session:
            owned = list(session.exec(select(OwnedCharacter)).all())
            chars = {c.id: c for c in session.exec(select(Character)).all()}
            cubes = {c.id: c for c in session.exec(select(Cube)).all()}

        # Join + flatten into row dicts the template can render directly.
        rows: list[dict] = []
        for o in owned:
            ch = chars.get(o.character_id)
            if ch is None:
                continue
            row = {
                "name": ch.name,
                "element": (ch.element.value if ch.element else "?"),
                "weapon": (ch.weapon_class.value if ch.weapon_class else "?"),
                "burst": (ch.burst_type.value if ch.burst_type else "?"),
                "manufacturer": (
                    ch.manufacturer.value if ch.manufacturer else "?"
                ),
                "power": o.power or 0,
                "sync_level": o.sync_level,
                "core": o.core,
                "limit_break": o.limit_break,
                "skill1": o.skill1_level,
                "skill2": o.skill2_level,
                "burst_skill": o.burst_skill_level,
                "arena_cube": (
                    cubes[o.arena_cube_id].name
                    if o.arena_cube_id and o.arena_cube_id in cubes
                    else None
                ),
                "battle_cube": (
                    cubes[o.battle_cube_id].name
                    if o.battle_cube_id and o.battle_cube_id in cubes
                    else None
                ),
                "doll": o.treasure_name,
                "doll_phase": o.treasure_phase,
            }
            rows.append(row)

        # Compute dropdown options from the *unfiltered* set so options
        # don't disappear when one filter is active (UX fix).
        all_elements = sorted({r["element"] for r in rows if r["element"] != "?"})
        all_bursts = sorted({str(r["burst"]) for r in rows if r["burst"] != "?"})

        # Filters
        if element:
            rows = [r for r in rows if r["element"].lower() == element.lower()]
        if burst:
            rows = [r for r in rows if str(r["burst"]).upper() == burst.upper()]

        # Sort
        sort_keys = {
            "power": lambda r: -r["power"],
            "name": lambda r: r["name"].lower(),
            "sync": lambda r: -(r["sync_level"] or 0),
            "burst": lambda r: (r["burst"], r["name"].lower()),
            "element": lambda r: (r["element"], -r["power"]),
        }
        rows.sort(key=sort_keys.get(sort, sort_keys["power"]))

        return templates.TemplateResponse(
            request,
            "roster_list.html",
            {
                "rows": rows,
                "sort": sort,
                "element": element,
                "burst": burst,
                "all_elements": all_elements,
                "all_bursts": all_bursts,
                "total_owned": len(owned),
                "snapshot_saved": snapshot_saved,
            },
        )

    @app.get("/roster/advisor", response_class=HTMLResponse)
    def roster_advisor(
        request: Request,
        role: str = "attack",
        target_skill: int = 7,
        max_recs: int = 10,
        top_k: int = 5,
    ) -> Response:
        """"Who should I level up next?" — slice #106.

        For each owned-but-undertrained Nikke (skill_sum below the
        investment floor), simulates upgrading her skills to
        ``target_skill`` and re-runs the optimizer. Ranks by score lift
        across the top-K teams. Surfaces the same ROI ranking as the
        ``nikkeoptimizer advisor`` CLI but in the web UI.
        """
        from ..optimizer.investment_advisor import recommend_investment
        from ..optimizer.scoring import (
            ATTACK_WEIGHTS, BALANCED_WEIGHTS, DEFENSE_WEIGHTS,
        )

        weights_for = {
            "attack": ATTACK_WEIGHTS,
            "defense": DEFENSE_WEIGHTS,
            "balanced": BALANCED_WEIGHTS,
        }
        weights = weights_for.get(role, ATTACK_WEIGHTS)
        with get_session(engine) as session:
            recs = recommend_investment(
                session, weights=weights, top_k=top_k,
                target_skill=target_skill, max_recommendations=max_recs,
            )
        return templates.TemplateResponse(
            request,
            "roster_advisor.html",
            {
                "recs": recs,
                "role": role,
                "target_skill": target_skill,
                "max_recs": max_recs,
                "top_k": top_k,
            },
        )

    @app.get("/roster/diff", response_class=HTMLResponse)
    def roster_diff(
        request: Request,
        snapshot: Optional[str] = None,
        days_ago: int = 7,
    ) -> Response:
        """Compare the current roster to a saved snapshot.

        With no parameters: picks the snapshot from at least 7 days ago.
        Pass ``?snapshot=<filename>`` to compare against a specific one,
        or ``?days_ago=N`` to use a different cutoff.
        """
        from ..roster.snapshots import (
            diff_against, latest_snapshot_before, list_snapshots,
        )
        from pathlib import Path as _Path

        all_snaps = list_snapshots()
        if snapshot:
            from ..data.db import default_db_path as _ddp
            base = _Path(_ddp()).parent / "snapshots"
            target = base / snapshot
            if not target.is_file():
                target = None
        else:
            target = latest_snapshot_before(days_ago)
        diff = None
        if target is not None:
            with get_session(engine) as session:
                diff = diff_against(session, target)
        return templates.TemplateResponse(
            request,
            "roster_diff.html",
            {
                "diff": diff,
                "all_snapshots": [p.name for p in all_snaps],
                "selected": target.name if target else None,
                "days_ago": days_ago,
            },
        )

    @app.get("/characters/{name}", response_class=HTMLResponse)
    def character_detail(request: Request, name: str) -> Response:
        """Per-character detail page — Prydwen prose + owned investment."""
        from ..data.scrapers.prydwen import flatten_rich_text
        with get_session(engine) as session:
            ch = session.exec(
                select(Character).where(Character.name == name)
            ).one_or_none()
            if ch is None:
                raise HTTPException(404, f"character {name!r} not found")
            owned = session.exec(
                select(OwnedCharacter).where(OwnedCharacter.character_id == ch.id)
            ).one_or_none()
        # Flatten the rich text fields for display. The web template
        # could render the full AST but plain prose is enough for now —
        # the JSON is preserved on the model for a future richer view.
        return templates.TemplateResponse(
            request,
            "character_detail.html",
            {
                "char": ch,
                "owned": owned,
                "pros_text": flatten_rich_text(ch.pros_raw),
                "cons_text": flatten_rich_text(ch.cons_raw),
                "review_text": flatten_rich_text(ch.review_raw),
                "skill_analysis_text": flatten_rich_text(ch.skill_analysis_raw),
                "harmony_cubes_text": flatten_rich_text(ch.harmony_cubes_info_raw),
            },
        )

    # ------------------------------------------------------------------
    # Cubes
    # ------------------------------------------------------------------

    @app.get("/cubes", response_class=HTMLResponse)
    def cubes_list(request: Request) -> Response:
        from .cube_warnings import compute_cube_warnings
        with get_session(engine) as session:
            rows = list(session.exec(select(Cube)).all())
            rows.sort(key=lambda c: (-(c.level or 0), c.name))
        warnings = compute_cube_warnings(rows)
        return templates.TemplateResponse(
            request, "cubes_list.html", {"cubes": rows, "warnings": warnings}
        )

    @app.get("/cubes/{cube_id}", response_class=HTMLResponse)
    def cubes_edit(request: Request, cube_id: int) -> Response:
        with get_session(engine) as session:
            cube = session.get(Cube, cube_id)
            if cube is None:
                raise HTTPException(404, f"cube {cube_id} not found")
        return templates.TemplateResponse(
            request, "cube_edit.html", {"cube": cube}
        )

    @app.post("/cubes/{cube_id}")
    def cubes_save(
        cube_id: int,
        name: str = Form(...),
        level: Optional[int] = Form(None),
        atk: Optional[int] = Form(None),
        hp: Optional[int] = Form(None),
        def_: Optional[int] = Form(None, alias="def"),
        equipping_count_equipped: Optional[int] = Form(None),
        equipping_count_owned: Optional[int] = Form(None),
    ) -> Response:
        with get_session(engine) as session:
            cube = session.get(Cube, cube_id)
            if cube is None:
                raise HTTPException(404, f"cube {cube_id} not found")
            cube.name = name.strip()
            cube.level = level
            cube.atk = atk
            cube.hp = hp
            cube.def_ = def_
            cube.equipping_count_equipped = equipping_count_equipped
            cube.equipping_count_owned = equipping_count_owned
            session.add(cube)
            session.commit()
        return RedirectResponse(url="/cubes", status_code=303)

    # ------------------------------------------------------------------
    # Arena captures
    # ------------------------------------------------------------------

    @app.get("/captures", response_class=HTMLResponse)
    def captures_list(
        request: Request,
        review_only: bool = False,
        mode: Optional[str] = None,
        outcome: Optional[str] = None,
        # Session filtering (slice #135).
        # session_kind: 'predictions' | 'partial' | 'complete'
        # since: '7d' | '30d' | 'all' — bound on captured_at for filtering
        session_kind: Optional[str] = None,
        since: Optional[str] = None,
        uploaded: Optional[int] = None,
        rookie: Optional[int] = None,
        special: Optional[int] = None,
        champion: Optional[int] = None,
        skipped: Optional[int] = None,
        review: Optional[int] = None,
        upload_error: Optional[str] = None,
    ) -> Response:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        from .capture_warnings import (
            per_row_warnings,
            session_completeness_warnings,
            set_completeness_warnings,
        )

        with get_session(engine) as session:
            # Set completeness needs the FULL capture set (not the filter
            # subset) so rounds present in unfiltered captures still
            # contribute to set membership.
            all_caps = list(session.exec(select(ArenaMatch)).all())
            set_warnings = set_completeness_warnings(all_caps)
            session_matrices = session_completeness_warnings(all_caps)

            query = select(ArenaMatch)
            if review_only:
                query = query.where(ArenaMatch.needs_review == True)  # noqa: E712
            if mode:
                query = query.where(ArenaMatch.mode == mode)
            if session_kind in ("predictions", "partial", "complete"):
                query = query.where(ArenaMatch.session_kind == session_kind)
            rows = list(session.exec(query).all())
            # Outcome filter (slice #105). The model has no index on
            # ``outcome``, but the result set is small (~tens of captures),
            # so an in-Python filter is fine. ``"untagged"`` matches rows
            # with NULL outcome — useful for finding which captures still
            # need a manual win/loss tag for damage-formula validation.
            if outcome == "untagged":
                rows = [r for r in rows if not r.outcome]
            elif outcome in ("win", "loss", "timeout"):
                rows = [r for r in rows if r.outcome == outcome]
            # Time-window filter for the "Awaiting results" workflow.
            if since in ("7d", "30d"):
                days = 7 if since == "7d" else 30
                cutoff = _dt.now(_tz.utc) - _td(days=days)
                # ``captured_at`` may be naive on legacy rows — normalize.
                def _aware(d):
                    if d.tzinfo is None:
                        return d.replace(tzinfo=_tz.utc)
                    return d
                rows = [r for r in rows if _aware(r.captured_at) >= cutoff]
            rows.sort(key=lambda r: r.id or 0, reverse=True)
            row_warnings = {r.id: per_row_warnings(r) for r in rows if r.id is not None}

            # Session-grouped view: when filtering by session_kind, surface
            # the unique sessions (one row per session_id, with summary
            # counts) above the per-row table so users can act on whole
            # sessions instead of scrolling through 11+ rows each.
            session_summaries: list[dict] = []
            if session_kind:
                seen: set[str] = set()
                for r in rows:
                    sid = r.session_id or ""
                    if not sid or sid in seen:
                        continue
                    seen.add(sid)
                    sc = session_matrices.get(sid)
                    if sc is None:
                        continue
                    session_summaries.append({
                        "session_id": sid,
                        "session_label": sc.session_label,
                        "session_kind": sc.session_kind,
                        "loadouts": sum(
                            (1 if r.p1_loadout.captured else 0)
                            + (1 if r.p2_loadout.captured else 0)
                            for r in sc.rounds
                        ),
                        "results": sum(
                            1 for r in sc.rounds if r.round_result.captured
                        ),
                        "duel_result": sc.duel_result.captured,
                        "warnings": sc.warnings,
                    })

            # Slice #136: when review_only is set, group rows by session_id
            # so the user can collapse / expand each Champions Duel as a
            # unit rather than scrolling 11+ unrelated rows. Sessions
            # without an ID get bucketed under the empty-string key
            # ("Unsessioned captures") so legacy data still appears.
            review_groups: list[dict] = []
            if review_only:
                from collections import defaultdict as _dd
                by_session: dict[str, list[ArenaMatch]] = _dd(list)
                for r in rows:
                    by_session[r.session_id or ""].append(r)
                # Sort: real sessions first by most-recent capture, then
                # the unsessioned bucket at the bottom.
                def _group_sort_key(item: tuple[str, list[ArenaMatch]]):
                    sid, sess_rows = item
                    most_recent = max(
                        (r.id or 0 for r in sess_rows), default=0
                    )
                    return (sid == "", -most_recent)
                for sid, sess_rows in sorted(by_session.items(), key=_group_sort_key):
                    sc = session_matrices.get(sid) if sid else None
                    review_groups.append({
                        "session_id": sid,
                        "session_label": (
                            sc.session_label if sc else None
                        ) or (
                            "Unsessioned captures" if not sid
                            else f"session {sid[:8]}…"
                        ),
                        "session_kind": sc.session_kind if sc else None,
                        "rows": sorted(
                            sess_rows, key=lambda r: r.id or 0,
                        ),
                        "review_count": sum(
                            1 for r in sess_rows if r.needs_review
                        ),
                    })
        upload_summary = None
        if uploaded is not None:
            upload_summary = {
                "uploaded": uploaded or 0,
                "rookie": rookie or 0,
                "special": special or 0,
                "champion": champion or 0,
                "skipped": skipped or 0,
                "review": review or 0,
            }
        # Counts for the in-page filter chips (predictions awaiting results).
        n_pred_sessions = sum(
            1 for sc in session_matrices.values()
            if sc.session_kind == "predictions"
        )
        return templates.TemplateResponse(
            request,
            "captures_list.html",
            {
                "captures": rows,
                "review_only": review_only,
                "mode": mode,
                "outcome": outcome,
                "session_kind": session_kind,
                "since": since,
                "row_warnings": row_warnings,
                "set_warnings": set_warnings,
                "session_summaries": session_summaries,
                "review_groups": review_groups,
                "upload_summary": upload_summary,
                "upload_error": upload_error,
                "matcher_loaded": _matcher() is not None,
                "n_predictions_awaiting": n_pred_sessions,
            },
        )

    @app.get("/captures/{capture_id}", response_class=HTMLResponse)
    def captures_detail(request: Request, capture_id: int) -> Response:
        from .capture_warnings import per_row_warnings, set_completeness_warnings

        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                raise HTTPException(404, f"capture {capture_id} not found")
            char_names = [c.name for c in session.exec(select(Character)).all()]
            row_w = per_row_warnings(cap)
            all_caps = list(session.exec(select(ArenaMatch)).all())
            set_w = set_completeness_warnings(all_caps).get(capture_id, [])
        return templates.TemplateResponse(
            request,
            "capture_detail.html",
            {
                "capture": cap,
                "char_names": sorted(char_names),
                "row_warnings": row_w,
                "set_warnings": set_w,
            },
        )

    @app.post("/captures/upload", response_class=HTMLResponse)
    async def captures_upload(
        request: Request,
        files: list[UploadFile] = File(...),
        mode_hint: str = Form(""),  # '', 'rookie', 'sp', 'champions'
        session_label: str = Form(""),
        # When supplied, the upload merges into an existing session
        # (used by the "Add results" workflow to attach Battle Records to
        # an earlier predictions-only session). Empty = create a new one.
        existing_session_id: str = Form(""),
    ) -> Response:
        """Upload one or more arena screenshots.

        Saves each file under ``<db_dir>/uploads/`` (persistent so
        FileResponse can re-serve them), runs the arena import
        pipeline, and redirects to ``/uploads/preview/{session_id}``
        with the matrix view so the user can verify completeness
        before navigating away.

        Requires the server to have been started with ``--library``
        — the portrait matcher needs an indexed library to identify
        cells. Returns ``upload_error=no_matcher`` if missing.
        """
        from ..roster.arena_importer import import_arena_screenshots

        matcher = _matcher()
        if matcher is None:
            return RedirectResponse(
                url="/captures?upload_error=no_matcher",
                status_code=303,
            )

        from pathlib import Path as _Path
        from ..data.config import get_self_username
        from ..data.db import default_db_path
        import time

        db_path = (
            _Path(app.state.db_path)
            if app.state.db_path is not None
            else _Path(default_db_path())
        )
        uploads_dir = db_path.parent / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[_Path] = []
        for upload in files:
            if not upload.filename:
                continue
            stem = _Path(upload.filename).stem
            suffix = _Path(upload.filename).suffix or ".png"
            target = uploads_dir / f"{int(time.time() * 1000)}_{stem}{suffix}"
            content = await upload.read()
            target.write_bytes(content)
            saved_paths.append(target)

        if not saved_paths:
            return RedirectResponse(url="/captures?upload_error=no_files", status_code=303)

        # mode_hint: empty string from the form means "auto-detect"; convert
        # to None so the importer doesn't try to match it as a literal hint.
        hint = mode_hint.strip() or None
        label = session_label.strip() or None
        sid = existing_session_id.strip() or None

        report = import_arena_screenshots(
            saved_paths,
            matcher,
            db_path=db_path,
            user_username=(get_self_username() or "NIKA"),
            mode_hint=hint,
            session_id=sid,
            session_label=label,
        )
        log.info("upload report: %s", report.to_dict())
        # Redirect to the preview matrix when a session_id is set; the page
        # surfaces completeness gaps and cell-level confidence so the user
        # can decide what to fix before navigating away. Falls back to the
        # captures list if anything went wrong with session generation.
        if report.session_id:
            return RedirectResponse(
                url=f"/uploads/preview/{report.session_id}",
                status_code=303,
            )
        params = (
            f"uploaded={report.files_seen}"
            f"&rookie={report.rookie}"
            f"&special={report.special}"
            f"&champion={report.champion}"
            f"&skipped={report.skipped}"
            f"&review={report.needs_review}"
        )
        return RedirectResponse(url=f"/captures?{params}", status_code=303)

    @app.get("/uploads/preview/{session_id}", response_class=HTMLResponse)
    def upload_preview(request: Request, session_id: str) -> Response:
        """Pre-save / post-upload completeness preview for one session.

        Shows the 5-round × 3-screen-type matrix for Champions sessions,
        plus the Duel Result row, plus per-cell match-confidence
        summaries. Same view powers both:
          - Immediate post-upload landing page (verify what just imported)
          - Returning later from the "Awaiting results" filter to add
            results to an existing predictions-only session
        """
        from ..data.config import get_self_username
        from .capture_warnings import (
            session_completeness,
        )
        with get_session(engine) as session:
            captures = list(
                session.exec(
                    select(ArenaMatch).where(
                        ArenaMatch.session_id == session_id
                    )
                ).all()
            )
            char_names = sorted(
                c.name for c in session.exec(select(Character)).all()
            )
        if not captures:
            raise HTTPException(404, f"session {session_id} has no captures")
        username = get_self_username()
        sc = session_completeness(captures, user_username=username)
        return templates.TemplateResponse(
            request,
            "upload_preview.html",
            {
                "session_id": session_id,
                "captures": captures,
                "completeness": sc,
                "captures_by_id": {c.id: c for c in captures},
                "char_names": char_names,
            },
        )

    @app.get("/captures/{capture_id}/cell-crop/{team}/{slot}.png")
    def captures_cell_crop(capture_id: int, team: str, slot: int) -> Response:
        """Serve the cropped portrait the matcher used for this cell.

        Slice #137 — debugging aid surfaced via hover-tooltip on the
        review UI. Lets the user verify that the crop the matcher saw
        is actually centered on the right portrait region. If the crop
        is wrong, the geometry needs re-tuning; if the crop is right
        but the match is wrong, the matcher needs more exemplars.
        """
        from io import BytesIO
        from PIL import Image as _PILImage
        from ..roster.arena import (
            _ARENA_INFO_REGIONS, _PORTRAIT_BOX_CHAMPION,
            _PORTRAIT_BOX_PREBATTLE, _PREBATTLE_REGIONS,
        )
        if team not in ("user", "opponent"):
            raise HTTPException(400, "team must be 'user' or 'opponent'")
        if not 0 <= slot < 5:
            raise HTTPException(400, "slot must be 0..4")
        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                raise HTTPException(404, f"capture {capture_id} not found")
            stored = cap.pre_battle_screenshot
            mode = cap.mode
        if not stored:
            raise HTTPException(404, "no source screenshot for this capture")
        resolved = _resolve_screenshot_path(stored, mode)
        if resolved is None:
            raise HTTPException(404, f"file not found: {stored}")
        try:
            full_image = _PILImage.open(resolved).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"open failed: {exc}")
        # Use the wide portrait crop (NOT the tight feedback box) — this
        # is what the matcher actually compares against at query time.
        crop = _crop_review_cell(
            full_image, mode, team, slot,
            _ARENA_INFO_REGIONS, _PREBATTLE_REGIONS,
            _PORTRAIT_BOX_CHAMPION, _PORTRAIT_BOX_PREBATTLE,
            tight_face=False,
        )
        if crop is None:
            raise HTTPException(404, f"no crop available for {mode}")
        buf = BytesIO()
        crop.save(buf, "PNG")
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/png")

    @app.get("/captures/{capture_id}/screenshot/{which}")
    def captures_screenshot(capture_id: int, which: str) -> Response:
        """Serve the PNG referenced by an ArenaMatch row.

        ``which`` is one of ``pre`` or ``record``. Only screenshots
        actually referenced by a DB row can be served — no arbitrary
        filesystem access via this endpoint.

        Slice #121 — if the stored path doesn't resolve (test fixtures
        were trimmed, project moved, web server cwd differs from import
        cwd), search known screenshot directories by basename + mode
        before giving up. Caches the resolved path back into the row so
        subsequent loads are fast.
        """
        if which not in ("pre", "record"):
            raise HTTPException(400, "which must be 'pre' or 'record'")
        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                raise HTTPException(404, f"capture {capture_id} not found")
            path_str = (
                cap.pre_battle_screenshot
                if which == "pre"
                else cap.battle_record_screenshot
            )
            if not path_str:
                raise HTTPException(404, f"no {which} screenshot recorded for this capture")
            resolved = _resolve_screenshot_path(path_str, cap.mode)
            if resolved is None:
                raise HTTPException(
                    404,
                    f"file not found: {path_str} (also checked user screenshots dir + uploads + project fixtures)",
                )
            # Persist the resolved absolute path back so we don't pay
            # the search cost again on every page reload.
            new_str = str(resolved)
            if new_str != path_str:
                if which == "pre":
                    cap.pre_battle_screenshot = new_str
                else:
                    cap.battle_record_screenshot = new_str
                session.add(cap)
                session.commit()
        return FileResponse(resolved, media_type="image/png")

    @app.post("/captures/{capture_id}/cell")
    def captures_override_cell(
        capture_id: int,
        team: str = Form(...),  # "user" or "opponent"
        slot: int = Form(...),  # 0..4
        character: str = Form(...),
        anchor: str = Form(""),  # row id to scroll back to after save
        return_to: str = Form(""),  # 'preview' → bounce back to session preview
    ) -> Response:
        if team not in ("user", "opponent"):
            raise HTTPException(400, f"team must be 'user' or 'opponent'")
        if not 0 <= slot < 5:
            raise HTTPException(400, f"slot must be 0..4")
        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                raise HTTPException(404, f"capture {capture_id} not found")

            team_list = list(cap.user_team if team == "user" else cap.opponent_team)
            while len(team_list) < 5:
                team_list.append("")
            previous_value = (team_list[slot] or "").strip()
            cleaned = character.strip()
            team_list[slot] = cleaned
            if team == "user":
                cap.user_team = team_list
            else:
                cap.opponent_team = team_list

            # Also mark this cell confident in capture_quality so it doesn't
            # show up as needing review again.
            quality = dict(cap.capture_quality or {})
            tq = dict(quality.get(team, {}))
            chars = list(tq.get("characters", []))
            while len(chars) < 5:
                chars.append(None)
            chars[slot] = cleaned or None
            tq["characters"] = chars
            quality[team] = tq
            cap.capture_quality = quality

            # Recompute needs_review across both teams.
            still_review = False
            for t in ("user", "opponent"):
                t_chars = (quality.get(t) or {}).get("characters") or []
                if any(c is None for c in t_chars):
                    still_review = True
                    break
            cap.needs_review = still_review

            session.add(cap)

            # Snapshot the screenshot path + mode BEFORE committing so the
            # post-commit feedback-loop save uses the right file location.
            snap_path = cap.pre_battle_screenshot
            snap_mode = cap.mode

            session.commit()

        # Feedback loop: ONLY save when the user actually changed the value.
        # Saving when the override input was already pre-populated with the
        # best-match value (and the user just clicked Save) would pollute the
        # exemplar index with whatever the matcher guessed — exactly the
        # opposite of "labeled feedback". The previous bug: round-1 cells
        # auto-saved their best matches as exemplars, then round-2 cells
        # with similar UI chrome matched against those exemplars and
        # returned wrong answers.
        if cleaned and snap_path and cleaned != previous_value:
            try:
                _save_feedback_exemplar(
                    capture_id, team, slot, cleaned, snap_path, snap_mode
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "feedback exemplar save failed for capture %s slot %s: %s",
                    capture_id, slot, exc,
                )

        # Anchor-redirect so the page scrolls back to the cell that was
        # just saved instead of jumping to the top. When the override was
        # triggered from the session preview (return_to=preview) we bounce
        # back there instead of the per-capture detail page.
        if return_to == "preview":
            sid: Optional[str] = None
            with get_session(engine) as session:
                row = session.get(ArenaMatch, capture_id)
                if row is not None:
                    sid = row.session_id
            if sid:
                target = f"/uploads/preview/{sid}"
                if anchor:
                    safe = anchor.lstrip("#").strip()
                    if safe:
                        target = f"{target}#{safe}"
                return RedirectResponse(url=target, status_code=303)
        target = f"/captures/{capture_id}"
        if anchor:
            # Strip any user-supplied '#' so we can prepend our own.
            safe = anchor.lstrip("#").strip()
            if safe:
                target = f"{target}#{safe}"
        return RedirectResponse(url=target, status_code=303)

    def _save_feedback_exemplar(
        capture_id: int, team: str, slot: int,
        character_name: str, stored_path: str, mode: Optional[str],
    ) -> None:
        """Crop the corrected cell + feed it back into the matcher.

        Writes the crop to ``<library>/feedback/<Character>/<ts>_<id>_<slot>.webp``
        AND calls ``matcher.add_exemplar`` so the running index gets the
        new entry without restart. The next capture in this session will
        match against the in-game-style exemplar in addition to the
        curated catalog art.
        """
        from PIL import Image as _PILImage
        import time

        if app.state.portrait_library is None or app.state.matcher is None:
            return  # nothing to feed back into

        resolved = _resolve_screenshot_path(stored_path, mode)
        if resolved is None:
            log.warning(
                "feedback: cannot resolve screenshot %r for capture %s",
                stored_path, capture_id,
            )
            return

        try:
            full_image = _PILImage.open(resolved).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            log.warning("feedback: open failed for %s: %s", resolved, exc)
            return

        # Re-derive the per-cell crop using the same geometry the importer
        # used. We re-import these constants so a future re-tune of cell
        # boxes auto-flows into feedback exemplars too.
        from ..roster.arena import (
            _ARENA_INFO_REGIONS, _PORTRAIT_BOX_CHAMPION,
            _PORTRAIT_BOX_PREBATTLE, _PREBATTLE_REGIONS,
        )
        cell_crop = _crop_review_cell(
            full_image, mode, team, slot,
            _ARENA_INFO_REGIONS, _PREBATTLE_REGIONS,
            _PORTRAIT_BOX_CHAMPION, _PORTRAIT_BOX_PREBATTLE,
            tight_face=True,  # avoid saving UI chrome as part of the exemplar
        )
        if cell_crop is None:
            return

        # Save under feedback/<Character>/<ts>_<id>_<slot>.webp
        feedback_root = Path(app.state.portrait_library) / "feedback" / character_name
        feedback_root.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        out_path = feedback_root / f"{ts}_cap{capture_id}_slot{slot}.webp"
        try:
            cell_crop.save(out_path, "WEBP", quality=90)
        except Exception as exc:  # noqa: BLE001
            log.warning("feedback: write failed for %s: %s", out_path, exc)
            return

        # Hot-append into the running matcher so the next capture this
        # session benefits without a restart.
        app.state.matcher.add_exemplar(
            character_name, cell_crop, source_path=out_path,
        )

    # Modest trim applied AFTER the regular portrait box. The portrait box
    # captures the character art *plus* small chrome bits at the edges
    # (LV banner at bottom, icon column at left, level badge at top-left).
    # The chrome is identical across all Champions cells — including it in
    # a labeled exemplar means a new crop with the same chrome but a
    # different face matches with artificially low distance.
    #
    # Coordinates are relative to the existing portrait box. We trim only
    # the obvious edge chrome (10% on each side, 5% top, 15% bottom) and
    # keep face + hair + upper costume — those are what actually
    # distinguish characters. Once we accumulate ~10 exemplars per
    # character, the law of large numbers handles the residual chrome
    # noise; at that point this trim can become more permissive.
    _FEEDBACK_FACE_BOX = (0.08, 0.05, 0.92, 0.85)

    def _crop_review_cell(
        image, mode, team, slot,
        arena_info_regions, prebattle_regions,
        portrait_box_champion, portrait_box_prebattle,
        *, tight_face: bool = False,
    ):
        """Crop the per-cell portrait from a stored screenshot.

        Mirrors the geometry used at import time so the hover-preview
        and feedback exemplars match what the matcher actually saw.

        When ``tight_face=True``, applies an additional inner sub-crop to
        cut UI chrome (LV banner / star count / card frame). Used for
        feedback exemplars to avoid the chrome dominating the embedding.
        """
        from ..roster.arena import _CHAMPION_TILE_BOXES
        if not mode:
            return None
        w, h = image.size
        # Champions Arena Info — use the explicit per-tile boxes (slice #138).
        # No strip+grid+portrait layering; the box IS the full card crop.
        if mode == "champion":
            if not 0 <= slot < len(_CHAMPION_TILE_BOXES):
                return None
            x1, y1, x2, y2 = _CHAMPION_TILE_BOXES[slot]
            portrait = image.crop(
                (int(w * x1), int(h * y1), int(w * x2), int(h * y2))
            )
        elif mode in ("rookie", "special"):
            # Rookie / SP retain the legacy strip+grid+portrait pipeline.
            band_box = (
                prebattle_regions["bottom_team_strip"] if team == "user"
                else prebattle_regions["top_team_strip"]
            )
            x1, y1, x2, y2 = band_box
            band = image.crop((int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)))
            bw, bh = band.size
            cell_w = bw // 5
            cell = band.crop((slot * cell_w, 0, (slot + 1) * cell_w, bh))
            cw, ch = cell.size
            px1, py1, px2, py2 = portrait_box_prebattle
            portrait = cell.crop(
                (int(cw * px1), int(ch * py1), int(cw * px2), int(ch * py2))
            )
        else:
            return None
        if tight_face:
            pw, ph = portrait.size
            fx1, fy1, fx2, fy2 = _FEEDBACK_FACE_BOX
            return portrait.crop(
                (int(pw * fx1), int(ph * fy1), int(pw * fx2), int(ph * fy2))
            )
        return portrait

    # ------------------------------------------------------------------
    # Delete / discard routes (slice #136)
    #
    # Three granularities:
    #   POST /captures/{id}/delete          — single row + its screenshot
    #   POST /sessions/{sid}/delete         — every row in a Champions session
    #   POST /captures/discard-needs-review — bulk: all needs_review rows
    #
    # All three accept an `existing_session_id` form field so we can
    # re-route back to the session preview when the source page wants to
    # stay there. They also remove the orphaned upload file under
    # <db_dir>/uploads/ so storage doesn't accumulate over time.
    # ------------------------------------------------------------------

    def _delete_screenshot_file(stored_path: Optional[str]) -> None:
        """Best-effort delete of an upload file referenced by a row.

        Only deletes when the file lives under <db_dir>/uploads/ — refuses
        to touch anything outside that directory so a stray absolute path
        in the DB can't be exploited to delete arbitrary files.
        """
        if not stored_path:
            return
        try:
            target = Path(stored_path).resolve()
        except Exception:
            return
        try:
            db = app.state.db_path or default_db_path()
            uploads_dir = (Path(db).parent / "uploads").resolve()
        except Exception:
            return
        try:
            target.relative_to(uploads_dir)
        except ValueError:
            return  # outside uploads dir → never delete
        try:
            target.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("upload cleanup failed for %s: %s", target, exc)

    def _delete_capture_row(session, cap: ArenaMatch) -> Optional[str]:
        """Delete one ArenaMatch row + its screenshot files.

        Returns the row's `session_id` (when set) so the caller can
        re-run `_refresh_session_kind` after the deletion.
        """
        sid = cap.session_id
        _delete_screenshot_file(cap.pre_battle_screenshot)
        _delete_screenshot_file(cap.battle_record_screenshot)
        session.delete(cap)
        return sid

    @app.post("/captures/{capture_id}/delete")
    def captures_delete(
        capture_id: int,
        return_to: str = Form(""),
    ) -> Response:
        """Discard one capture row + its screenshot file."""
        from ..roster.arena_importer import _refresh_session_kind
        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                raise HTTPException(404, f"capture {capture_id} not found")
            sid = _delete_capture_row(session, cap)
            session.flush()
            if sid:
                _refresh_session_kind(session, sid)
            session.commit()
        # Redirect target: prefer return_to=preview when set + we know
        # the session, otherwise fall back to /captures.
        if return_to == "preview" and sid:
            return RedirectResponse(
                url=f"/uploads/preview/{sid}", status_code=303,
            )
        return RedirectResponse(url="/captures", status_code=303)

    @app.post("/sessions/{session_id}/delete")
    def sessions_delete(session_id: str) -> Response:
        """Discard every row in a session + their screenshot files."""
        with get_session(engine) as session:
            rows = list(session.exec(
                select(ArenaMatch).where(ArenaMatch.session_id == session_id)
            ).all())
            if not rows:
                raise HTTPException(404, f"session {session_id} has no rows")
            for cap in rows:
                _delete_capture_row(session, cap)
            session.commit()
        return RedirectResponse(url="/captures", status_code=303)

    @app.post("/feedback/clear")
    def feedback_clear(
        confirm: str = Form(""),
        character: str = Form(""),
    ) -> Response:
        """Wipe feedback exemplars from the portrait library.

        Two modes:
          * No `character` arg → wipe ALL feedback exemplars (full reset).
          * `character` set    → wipe only that character's subdir.

        Also rebuilds the in-process matcher index so wiped exemplars
        stop influencing matches immediately. Requires `confirm=yes`.
        """
        import shutil
        if confirm != "yes":
            raise HTTPException(400, "clear requires confirm=yes")
        if app.state.portrait_library is None:
            raise HTTPException(
                400, "no portrait library configured; nothing to clear",
            )
        feedback_root = Path(app.state.portrait_library) / "feedback"
        cleared = 0
        if character:
            target = feedback_root / character
            if target.exists() and target.is_dir():
                cleared = sum(1 for _ in target.glob("*"))
                shutil.rmtree(target)
        else:
            if feedback_root.exists():
                for sub in feedback_root.iterdir():
                    if sub.is_dir():
                        cleared += sum(1 for _ in sub.glob("*"))
                        shutil.rmtree(sub)
        # Force a matcher rebuild on next access so the in-memory index
        # drops the wiped exemplars.
        app.state.matcher = None
        log.info(
            "cleared %d feedback exemplar(s)%s",
            cleared,
            f" for {character!r}" if character else " (all)",
        )
        return RedirectResponse(
            url=f"/captures?feedback_cleared={cleared}",
            status_code=303,
        )

    @app.post("/captures/discard-needs-review")
    def captures_discard_needs_review(
        confirm: str = Form(""),
        session_kind: str = Form(""),
    ) -> Response:
        """Bulk-discard every capture currently flagged needs_review.

        Optional `session_kind` scopes the bulk-delete to one kind
        (e.g. delete only `predictions` sessions still in review).
        Requires `confirm=yes` from the form so a stray click can't
        wipe data — the UI sets this via a JS prompt confirmation.
        """
        from ..roster.arena_importer import _refresh_session_kind
        if confirm != "yes":
            raise HTTPException(
                400, "discard requires confirm=yes (set by the UI prompt)",
            )
        affected_sessions: set[str] = set()
        deleted_count = 0
        with get_session(engine) as session:
            query = select(ArenaMatch).where(
                ArenaMatch.needs_review == True  # noqa: E712
            )
            if session_kind in ("predictions", "partial", "complete"):
                query = query.where(ArenaMatch.session_kind == session_kind)
            for cap in list(session.exec(query).all()):
                sid = _delete_capture_row(session, cap)
                if sid:
                    affected_sessions.add(sid)
                deleted_count += 1
            session.flush()
            for sid in affected_sessions:
                _refresh_session_kind(session, sid)
            session.commit()
        log.info(
            "bulk-discarded %d needs_review captures across %d sessions",
            deleted_count, len(affected_sessions),
        )
        return RedirectResponse(
            url=f"/captures?review_only=true&discarded={deleted_count}",
            status_code=303,
        )

    @app.post("/captures/{capture_id}/outcome")
    def captures_set_outcome(
        capture_id: int,
        outcome: str = Form(""),  # 'win' | 'loss' | 'timeout' | '' (clear)
        user_role: str = Form(""),  # 'attack' | 'defense' | '' (clear)
        seconds_to_clear: Optional[int] = Form(None),
    ) -> Response:
        """Tag an arena capture's match outcome.

        Foundation for damage-formula validation: with real
        ``outcome`` + ``seconds_to_clear`` data captured per match, the
        simulator's predictions can eventually be backtested. ``''``
        clears the field so a mistakenly-set outcome can be reset.
        """
        valid_outcomes = {"", "win", "loss", "timeout"}
        valid_roles = {"", "attack", "defense"}
        if outcome not in valid_outcomes:
            raise HTTPException(400, f"outcome must be one of {sorted(valid_outcomes)}")
        if user_role not in valid_roles:
            raise HTTPException(400, f"user_role must be one of {sorted(valid_roles)}")
        if seconds_to_clear is not None and (seconds_to_clear < 0 or seconds_to_clear > 600):
            raise HTTPException(400, "seconds_to_clear must be 0..600")

        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                raise HTTPException(404, f"capture {capture_id} not found")
            cap.outcome = outcome or None
            cap.user_role = user_role or None
            # Persist seconds_to_clear inside raw_battle_record (JSON dict)
            # so we don't need a schema migration. Clear when set to None.
            record = dict(cap.raw_battle_record or {})
            if seconds_to_clear is None:
                record.pop("seconds_to_clear", None)
            else:
                record["seconds_to_clear"] = int(seconds_to_clear)
            cap.raw_battle_record = record
            session.add(cap)
            session.commit()
        return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Optimizer
    # ------------------------------------------------------------------

    @app.get("/counter", response_class=HTMLResponse)
    def counter_freeform(
        request: Request,
        n1: str = "",
        n2: str = "",
        n3: str = "",
        n4: str = "",
        n5: str = "",
        top_k: int = 5,
        min_power: int = 50_000,
    ) -> Response:
        """Counter-pick a free-form opponent lineup (no capture required).

        Same recommendation engine as ``captures_counter``; this route
        just lets the user type 5 names instead of pulling them from a
        captured ``ArenaMatch``. Useful for theorycrafting or
        countering teams the user hasn't yet captured (e.g., a friend's
        roster, or a team posted in chat).
        """
        from ..optimizer.counter import recommend_counter
        from ..optimizer.loader import get_context
        from .evaluator_helper import burst_timings_for

        opp_names_raw = [n1, n2, n3, n4, n5]
        opp_names = [n.strip() for n in opp_names_raw if n and n.strip()]

        # Validate: every supplied name must resolve to a known character
        # (DB lookup) before we run the optimizer. Missing names go into
        # ``unknown_names`` for surfacing in the form.
        unknown_names: list[str] = []
        char_names: list[str] = []
        with get_session(engine) as session:
            char_names = sorted(c.name for c in session.exec(select(Character)).all())
            known = set(char_names)
            for n in opp_names:
                if n not in known:
                    unknown_names.append(n)

            rec = None
            if opp_names and not unknown_names and len(opp_names) == 5:
                ctx = get_context(session, db_path=app.state.db_path)
                rec = recommend_counter(
                    session,
                    opp_names,
                    top_k=top_k,
                    beam_width=200,
                    min_power=min_power,
                    context=ctx,
                )
        team_timings = burst_timings_for(rec.teams) if rec and rec.teams else []
        return templates.TemplateResponse(
            request,
            "counter_freeform.html",
            {
                "rec": rec,
                "top_k": top_k,
                "min_power": min_power,
                "opp_names_raw": opp_names_raw,
                "unknown_names": unknown_names,
                "char_names": char_names,
                "team_timings": team_timings,
            },
        )

    @app.get("/captures/{capture_id}/counter", response_class=HTMLResponse)
    def captures_counter(
        request: Request,
        capture_id: int,
        top_k: int = 5,
        min_power: int = 50_000,
    ) -> Response:
        from ..optimizer.counter import recommend_counter
        from ..optimizer.loader import get_context
        from .evaluator_helper import burst_timings_for

        with get_session(engine) as session:
            cap = session.get(ArenaMatch, capture_id)
            if cap is None:
                raise HTTPException(404, f"capture {capture_id} not found")
            opp_names = [n for n in (cap.opponent_team or []) if n]
            rec = None
            if opp_names:
                ctx = get_context(session, db_path=app.state.db_path)
                rec = recommend_counter(
                    session,
                    opp_names,
                    top_k=top_k,
                    beam_width=200,
                    min_power=min_power,
                    context=ctx,
                )
        team_timings = burst_timings_for(rec.teams) if rec and rec.teams else []
        return templates.TemplateResponse(
            request,
            "counter.html",
            {
                "capture": cap,
                "rec": rec,
                "top_k": top_k,
                "min_power": min_power,
                "opp_names": opp_names,
                "team_timings": team_timings,
            },
        )

    def _parse_weight_overrides(
        power_w, element_diversity_w, role_balance_w, synergy_w,
        investment_w, durability_w, burst_gen_w,
    ):
        """Map non-None weight query params → ScoringWeights override.

        Returns ``None`` when no overrides are present (caller uses
        the role-default presets). Otherwise returns a ScoringWeights
        constructed from ATTACK_WEIGHTS as a base with the supplied
        fields replaced. Slice #104 — shared between rookie / SP /
        Champions routes.
        """
        from dataclasses import replace as _replace
        from ..optimizer.scoring import ATTACK_WEIGHTS, ScoringWeights

        overrides: dict = {}
        for field, value in (
            ("power_sum", power_w),
            ("element_diversity", element_diversity_w),
            ("role_balance", role_balance_w),
            ("synergy_pairs", synergy_w),
            ("investment", investment_w),
            ("durability", durability_w),
            ("burst_gen", burst_gen_w),
        ):
            if value is not None:
                overrides[field] = float(value)
        if not overrides:
            return None
        return _replace(ATTACK_WEIGHTS, **overrides)

    @app.get("/optimize/champions", response_class=HTMLResponse)
    def optimize_champions(
        request: Request,
        min_power: int = 100_000,
        power_w: Optional[float] = None,
        element_diversity_w: Optional[float] = None,
        role_balance_w: Optional[float] = None,
        synergy_w: Optional[float] = None,
        investment_w: Optional[float] = None,
        durability_w: Optional[float] = None,
        burst_gen_w: Optional[float] = None,
    ) -> Response:
        from ..optimizer.champions import recommend_champions
        from ..optimizer.scoring import ATTACK_WEIGHTS, BALANCED_WEIGHTS
        from .evaluator_helper import (
            burst_timings_for,
            rescored_teams_with_evaluations,
        )

        custom_weights = _parse_weight_overrides(
            power_w, element_diversity_w, role_balance_w, synergy_w,
            investment_w, durability_w, burst_gen_w,
        )
        with get_session(engine) as session:
            rec = recommend_champions(
                session, beam_width=200, min_power=min_power,
                override_weights=custom_weights,
            )
        rescore_w = custom_weights or BALANCED_WEIGHTS
        rescored, evaluations = rescored_teams_with_evaluations(
            rec.teams, weights=rescore_w
        )
        # Champions teams are season-locked as a group of 5; preserve
        # the optimizer's lineup ordering rather than re-sorting per team.
        rec.teams[:] = rescored
        team_timings = burst_timings_for(rec.teams)
        return templates.TemplateResponse(
            request,
            "optimize_champions.html",
            {
                "rec": rec,
                "min_power": min_power,
                "team_evaluations": evaluations,
                "team_timings": team_timings,
                "active_weights": custom_weights or BALANCED_WEIGHTS,
                "using_custom_weights": custom_weights is not None,
                "default_weights": ATTACK_WEIGHTS,
            },
        )

    @app.get("/optimize/sp", response_class=HTMLResponse)
    def optimize_sp(
        request: Request,
        min_power: int = 100_000,
        power_w: Optional[float] = None,
        element_diversity_w: Optional[float] = None,
        role_balance_w: Optional[float] = None,
        synergy_w: Optional[float] = None,
        investment_w: Optional[float] = None,
        durability_w: Optional[float] = None,
        burst_gen_w: Optional[float] = None,
    ) -> Response:
        from ..optimizer.sp_arena import recommend_sp_arena
        from ..optimizer.scoring import ATTACK_WEIGHTS, DEFENSE_WEIGHTS
        from .evaluator_helper import (
            burst_timings_for,
            rescored_teams_with_evaluations,
        )

        custom_weights = _parse_weight_overrides(
            power_w, element_diversity_w, role_balance_w, synergy_w,
            investment_w, durability_w, burst_gen_w,
        )
        with get_session(engine) as session:
            rec = recommend_sp_arena(
                session, beam_width=200, min_power=min_power,
                override_weights=custom_weights,
            )
        attack_w = custom_weights or ATTACK_WEIGHTS
        defense_w = custom_weights or DEFENSE_WEIGHTS
        rec.attack[:], attack_evals = rescored_teams_with_evaluations(
            rec.attack, weights=attack_w
        )
        rec.defense[:], defense_evals = rescored_teams_with_evaluations(
            rec.defense, weights=defense_w
        )
        attack_timings = burst_timings_for(rec.attack)
        defense_timings = burst_timings_for(rec.defense)
        return templates.TemplateResponse(
            request,
            "optimize_sp.html",
            {
                "rec": rec,
                "min_power": min_power,
                "attack_evaluations": attack_evals,
                "defense_evaluations": defense_evals,
                "attack_timings": attack_timings,
                "defense_timings": defense_timings,
                "active_weights": custom_weights or ATTACK_WEIGHTS,
                "using_custom_weights": custom_weights is not None,
                "default_weights": ATTACK_WEIGHTS,
            },
        )

    @app.get("/optimize/rookie", response_class=HTMLResponse)
    def optimize_rookie(
        request: Request,
        top_k: int = 5,
        min_power: int = 100_000,
        # Slice #103 — custom weight overrides. None = use the role default
        # (ATTACK_WEIGHTS for attack, DEFENSE_WEIGHTS for defense). Any value
        # set will override BOTH role presets — the rookie page surfaces a
        # single set of sliders for simplicity.
        power_w: Optional[float] = None,
        element_diversity_w: Optional[float] = None,
        role_balance_w: Optional[float] = None,
        synergy_w: Optional[float] = None,
        investment_w: Optional[float] = None,
        durability_w: Optional[float] = None,
        burst_gen_w: Optional[float] = None,
    ) -> Response:
        from ..optimizer.rookie import recommend_rookie
        from ..optimizer.scoring import (
            ATTACK_WEIGHTS, DEFENSE_WEIGHTS, ScoringWeights,
        )
        from .evaluator_helper import (
            burst_timings_for,
            rescored_teams_with_evaluations,
        )

        custom_weights: Optional[ScoringWeights] = _parse_weight_overrides(
            power_w, element_diversity_w, role_balance_w, synergy_w,
            investment_w, durability_w, burst_gen_w,
        )

        with get_session(engine) as session:
            rec = recommend_rookie(
                session, top_k=top_k, beam_width=200, min_power=min_power,
                weights=custom_weights,
            )
        attack_w = custom_weights or ATTACK_WEIGHTS
        defense_w = custom_weights or DEFENSE_WEIGHTS
        attack_rescored, attack_evals = rescored_teams_with_evaluations(
            rec.attack, weights=attack_w
        )
        defense_rescored, defense_evals = rescored_teams_with_evaluations(
            rec.defense, weights=defense_w
        )
        attack_timings = burst_timings_for(attack_rescored)
        defense_timings = burst_timings_for(defense_rescored)

        # Slice #119 — predicted clear-time vs a canonical meta defense
        # for each attack team. Lets users see "this team would clear a
        # generic Helm/Centi/Blanc defense in Xs" without going through
        # counter-pick. None when team isn't fully encoded.
        from ..simulator.damage import resolve_by_names
        BENCHMARK_DEFENSE = ("Helm", "Centi", "Blanc", "Bay", "Anchor")
        attack_resolutions: list = []
        for cand in attack_rescored:
            names = [m.name for m in cand.members]
            try:
                attack_resolutions.append(resolve_by_names(names, BENCHMARK_DEFENSE))
            except Exception:
                attack_resolutions.append(None)

        return templates.TemplateResponse(
            request,
            "optimize_rookie.html",
            {
                "attack": attack_rescored,
                "defense": defense_rescored,
                "attack_evaluations": attack_evals,
                "defense_evaluations": defense_evals,
                "attack_timings": attack_timings,
                "defense_timings": defense_timings,
                "attack_resolutions": attack_resolutions,
                "top_k": top_k,
                "min_power": min_power,
                "active_weights": custom_weights or ATTACK_WEIGHTS,
                "using_custom_weights": custom_weights is not None,
                "default_weights": ATTACK_WEIGHTS,
            },
        )

    @app.get("/validate", response_class=HTMLResponse)
    def damage_validation(
        request: Request,
        damage_per_shot: Optional[float] = None,
        cycle_period: Optional[float] = None,
        min_def_through: Optional[float] = None,
    ) -> Response:
        """Backtest the damage formula against tagged match outcomes.

        Slice #108 — for every capture with both a tagged ``outcome``
        and a complete user_team + opponent_team, run the damage
        resolver and compare predicted win/loss to the actual.

        Slice #123 — accepts URL overrides for the three tunable
        constants (`damage_per_shot`, `cycle_period`,
        `min_def_through`) so users can sweep these and watch accuracy
        / mean clear-time error change.
        """
        from ..simulator.damage import (
            DAMAGE_PER_SHOT_FRACTION,
            DEFAULT_CYCLE_PERIOD_SEC,
            MIN_DAMAGE_FRACTION_THROUGH_DEF,
            resolve_by_names,
        )

        # Resolve effective tuning constants — params override defaults.
        tuning_kwargs: dict = {}
        if damage_per_shot is not None:
            tuning_kwargs["damage_per_shot_fraction"] = float(damage_per_shot)
        if cycle_period is not None:
            tuning_kwargs["cycle_period_sec"] = float(cycle_period)
        if min_def_through is not None:
            tuning_kwargs["min_damage_fraction_through_def"] = float(min_def_through)

        rows: list[dict] = []
        n_total = 0
        n_predictable = 0
        n_correct = 0
        confusion = {"true_pos": 0, "true_neg": 0, "false_pos": 0, "false_neg": 0}
        clear_time_errors: list[float] = []
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
            # Determine attacker / defender based on user_role.
            if cap.user_role == "attack":
                attacker_names, defender_names = user, opp
            elif cap.user_role == "defense":
                attacker_names, defender_names = opp, user
            else:
                continue  # need a tagged role to attribute attack side
            try:
                resolution = resolve_by_names(
                    attacker_names, defender_names, **tuning_kwargs,
                )
            except Exception:  # pragma: no cover - defensive
                resolution = None
            if resolution is None:
                continue
            n_predictable += 1
            # User's "win" maps to: attacker beats defender if user is attacking,
            # OR attacker fails to beat defender if user is defending.
            if cap.user_role == "attack":
                user_predicted_to_win = resolution.attacker_wins_within_5min
            else:
                user_predicted_to_win = not resolution.attacker_wins_within_5min
            user_actually_won = cap.outcome == "win"
            correct = user_predicted_to_win == user_actually_won
            if correct:
                n_correct += 1
            if user_predicted_to_win and user_actually_won:
                confusion["true_pos"] += 1
            elif (not user_predicted_to_win) and (not user_actually_won):
                confusion["true_neg"] += 1
            elif user_predicted_to_win and (not user_actually_won):
                confusion["false_pos"] += 1
            else:
                confusion["false_neg"] += 1
            actual_seconds = (cap.raw_battle_record or {}).get("seconds_to_clear")
            err = None
            if actual_seconds is not None:
                err = abs(resolution.seconds_to_clear_defender - float(actual_seconds))
                clear_time_errors.append(err)
            rows.append({
                "capture_id": cap.id,
                "mode": cap.mode,
                "user_role": cap.user_role,
                "outcome": cap.outcome,
                "predicted_user_wins": user_predicted_to_win,
                "predicted_clear_sec": resolution.seconds_to_clear_defender,
                "actual_seconds": actual_seconds,
                "clear_time_error_sec": err,
                "correct": correct,
            })
        accuracy = (n_correct / n_predictable) if n_predictable else None
        mean_err = (
            sum(clear_time_errors) / len(clear_time_errors)
            if clear_time_errors else None
        )

        # Per-Nikke Battle Records aggregate (slice #135). When Champions
        # Battle Records screens have been imported, each row carries a
        # ``raw_battle_record["matchups"]`` list with per-Nikke damage,
        # damage_taken, healing, burst_uses. We aggregate these into per-
        # character mean / count tables so the user can see "we have 12
        # damage observations for Crown averaging 1.4M" — foundation for
        # eventual simulator-vs-actual per-character bias tuning.
        per_nikke_actuals: dict[str, dict[str, list[int]]] = {}
        n_battle_records = 0
        for cap in captures:
            payload = (cap.raw_battle_record or {}).get("matchups") or []
            if not payload:
                continue
            n_battle_records += 1
            for m in payload:
                for who_key, dmg_key, taken_key, heal_key in (
                    ("my_nikke", "my_damage_dealt", "my_damage_taken", "my_healing"),
                    ("opponent_nikke", "opponent_damage_dealt",
                     "opponent_damage_taken", "opponent_healing"),
                ):
                    name = m.get(who_key)
                    if not name:
                        continue
                    bucket = per_nikke_actuals.setdefault(
                        name,
                        {"damage_dealt": [], "damage_taken": [], "healing": []},
                    )
                    if m.get(dmg_key) is not None:
                        bucket["damage_dealt"].append(m[dmg_key])
                    if m.get(taken_key) is not None:
                        bucket["damage_taken"].append(m[taken_key])
                    if m.get(heal_key) is not None:
                        bucket["healing"].append(m[heal_key])
        per_nikke_summary = []
        for name, stats in sorted(per_nikke_actuals.items()):
            row = {"name": name}
            for k, vals in stats.items():
                row[f"{k}_n"] = len(vals)
                row[f"{k}_mean"] = (sum(vals) / len(vals)) if vals else None
            per_nikke_summary.append(row)

        return templates.TemplateResponse(
            request,
            "validate.html",
            {
                "rows": rows,
                "n_total": n_total,
                "n_predictable": n_predictable,
                "n_correct": n_correct,
                "accuracy": accuracy,
                "confusion": confusion,
                "mean_clear_time_error": mean_err,
                "n_clear_time_samples": len(clear_time_errors),
                "per_nikke_summary": per_nikke_summary,
                "n_battle_records": n_battle_records,
                "tuning": {
                    "damage_per_shot": (
                        damage_per_shot
                        if damage_per_shot is not None
                        else DAMAGE_PER_SHOT_FRACTION
                    ),
                    "cycle_period": (
                        cycle_period
                        if cycle_period is not None
                        else DEFAULT_CYCLE_PERIOD_SEC
                    ),
                    "min_def_through": (
                        min_def_through
                        if min_def_through is not None
                        else MIN_DAMAGE_FRACTION_THROUGH_DEF
                    ),
                    "is_custom": any(
                        v is not None for v in
                        (damage_per_shot, cycle_period, min_def_through)
                    ),
                },
                "defaults": {
                    "damage_per_shot": DAMAGE_PER_SHOT_FRACTION,
                    "cycle_period": DEFAULT_CYCLE_PERIOD_SEC,
                    "min_def_through": MIN_DAMAGE_FRACTION_THROUGH_DEF,
                },
            },
        )

    @app.get("/optimize/ga", response_class=HTMLResponse)
    def optimize_ga(
        request: Request,
        role: str = "attack",
        top_k: int = 5,
        pop_size: int = 100,
        generations: int = 50,
        min_power: int = 100_000,
        seed: Optional[int] = None,
    ) -> Response:
        """Phase 4 GA team search — surfaces non-obvious comps the
        beam-search heuristic might miss. Compares to beam-top-K
        side-by-side. Slice #128.
        """
        from ..optimizer.constraints import effective_min_skill_sum
        from ..optimizer.genetic import genetic_search
        from ..optimizer.loader import filter_eligible, load_owned
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

        with get_session(engine) as session:
            owned = load_owned(session)
        pool = filter_eligible(
            owned, min_power=min_power, min_skill_sum=effective_min_skill_sum(),
        )
        ga_result = genetic_search(
            pool,
            weights=weights,
            population_size=pop_size,
            generations=generations,
            top_k=top_k,
            seed=seed,
        )
        beam_teams = beam_search_top_teams(
            pool, top_k=top_k, beam_width=200, weights=weights,
        ) if pool else []
        # Set comparison.
        ga_sets = {frozenset(m.name for m in t.members) for t in ga_result.teams}
        beam_sets = {frozenset(m.name for m in t.members) for t in beam_teams}
        return templates.TemplateResponse(
            request,
            "optimize_ga.html",
            {
                "ga": ga_result,
                "beam": beam_teams,
                "ga_only": ga_sets - beam_sets,
                "beam_only": beam_sets - ga_sets,
                "shared": ga_sets & beam_sets,
                "role": role,
                "top_k": top_k,
                "pop_size": pop_size,
                "generations": generations,
                "min_power": min_power,
                "seed": seed,
                "pool_size": len(pool),
            },
        )

    @app.get("/explain", response_class=HTMLResponse)
    def explain(
        request: Request,
        character: Optional[str] = None,
        role: str = "balanced",
        min_power: int = 100_000,
    ) -> Response:
        from ..optimizer.explain import explain_character

        if role not in ("attack", "defense", "balanced"):
            role = "balanced"

        result = None
        char_names: list[str] = []
        with get_session(engine) as session:
            char_names = sorted(c.name for c in session.exec(select(Character)).all())
            if character:
                result = explain_character(
                    session,
                    character,
                    role=role,  # type: ignore[arg-type]
                    beam_width=200,
                    min_power=min_power,
                )

        return templates.TemplateResponse(
            request,
            "explain.html",
            {
                "result": result,
                "character": character or "",
                "role": role,
                "min_power": min_power,
                "char_names": char_names,
            },
        )

    # ------------------------------------------------------------------
    # Promotion Tournament archive browser
    # ------------------------------------------------------------------

    def _promo_image_url(file_path: str) -> Optional[str]:
        """Map an absolute screenshot path to its /promo-images URL."""
        try:
            rel = Path(file_path).resolve().relative_to(_PROMO_ROOT)
        except (ValueError, OSError):
            return None
        return "/promo-images/" + rel.as_posix()

    # Round-priority for canonical loadout lookup. Earliest rounds with
    # full loadouts win — those are the most reliable source of a
    # player's season-locked team.
    _CANONICAL_ROUND_PRIORITY = {
        "round_64": 0,
        "quarterfinals": 1,
        "top_32": 2,
        "semifinals": 3,
        "top_16": 4,
        "finals": 5,
    }

    def _promo_canonical_loadout(
        session,
        player_name: Optional[str],
        *,
        current_overview_id: Optional[int] = None,
        current_side: Optional[str] = None,
    ) -> Optional[dict]:
        """Find a representative loadout for ``player_name``.

        Tier 1 (OCR-based, fast):
          Searches every player_loadout screenshot whose ``player_name``
          OCR matches (exact → case-insensitive → fuzzy ratio ≥ 80) and
          picks the one with the earliest round_label by
          ``_CANONICAL_ROUND_PRIORITY``.

        Tier 2 (image-hash fallback):
          When tier 1 has nothing to search by (player_name is empty),
          and the caller supplied ``current_overview_id`` /
          ``current_side``, perceptually-hash that overview's name crop
          and find another overview whose ``left_name`` / ``right_name``
          crop is the same player. Use that match's loadouts as the
          canonical source. Handles the case where the current match's
          overview name OCR returned nothing.
        """
        from rapidfuzz import fuzz

        from ..roster.promo_tournament_regions import PLAYER_LOADOUT

        # ---- Tier 2 prep: resolve canonical via image hashing -------
        if not player_name and current_overview_id and current_side:
            from ..roster.promo_tournament_player_match import (
                find_canonical_match_via_image,
                loadout_for_matched_overview,
            )

            query_ov = session.get(PromoMatchScreenshot, current_overview_id)
            if query_ov is not None:
                hash_match = find_canonical_match_via_image(
                    session, query_ov, current_side
                )
                if hash_match is not None:
                    source = loadout_for_matched_overview(
                        session,
                        hash_match.matched_match_id,
                        hash_match.matched_side,
                    )
                    if source is not None:
                        return _build_canonical_from_loadout(
                            session,
                            source,
                            tier="image-hash",
                            hash_distance=hash_match.distance,
                        )

        if not player_name:
            return None
        pn = player_name.strip()
        if not pn:
            return None

        # Find player_name extractions on player_loadout screenshots.
        rows = session.exec(
            select(PromoExtractedField, PromoMatchScreenshot)
            .where(
                PromoExtractedField.region_slug == "player_name",
                PromoExtractedField.screenshot_id == PromoMatchScreenshot.id,
                PromoMatchScreenshot.kind == "player_loadout",
            )
        ).all()
        if not rows:
            return None
        # Tier 1: exact match.
        matches = [(f, sh) for f, sh in rows if f.text and f.text.strip() == pn]
        # Tier 2: case-insensitive.
        if not matches:
            lp = pn.lower()
            matches = [
                (f, sh) for f, sh in rows
                if f.text and f.text.strip().lower() == lp
            ]
        # Tier 3: fuzzy ratio ≥ 80.
        if not matches:
            lp = pn.lower()
            matches = [
                (f, sh) for f, sh in rows
                if f.text and fuzz.ratio(f.text.strip().lower(), lp) >= 80
            ]
        if not matches:
            return None

        # Pick the one from the earliest-priority round, then earliest
        # round_no within the match.
        match_ids = list({sh.match_id for _, sh in matches})
        match_rows = session.exec(
            select(PromoMatch).where(PromoMatch.id.in_(match_ids))
        ).all()
        match_label = {m.id: m.round_label for m in match_rows}

        def _key(item):
            _f, sh = item
            return (
                _CANONICAL_ROUND_PRIORITY.get(match_label.get(sh.match_id, ""), 99),
                sh.round_no or 0,
                sh.id,
            )
        matches.sort(key=_key)
        _, source = matches[0]
        return _build_canonical_from_loadout(
            session, source, player_name=pn, tier="ocr"
        )

    def _build_canonical_from_loadout(
        session,
        source: PromoMatchScreenshot,
        *,
        player_name: Optional[str] = None,
        tier: Optional[str] = None,
        hash_distance: Optional[int] = None,
    ) -> Optional[dict]:
        """Assemble the canonical-loadout view-model dict from a chosen
        source loadout screenshot.

        Champions Arena teams are season-locked but each ROUND uses a
        different 5-character team. The view-model exposes all 5
        round-N team comps (sourced from the same match + same side
        as ``source``) so the template can render them as tabs. Player
        identity metadata (name, tier, source match) lives at the top
        level since it's shared across rounds.

        Shared between the OCR-based path (tier 1) and the image-hash
        fallback (tier 2). ``player_name`` defaults to the source
        loadout's own ``player_name`` OCR text when not supplied.
        """
        from ..roster.promo_tournament_regions import PLAYER_LOADOUT

        # Find every sibling round-N loadout for the same match + side.
        # In a complete capture this gives us 5 (one per round). Some
        # captures may have fewer — we render whatever's available.
        siblings = session.exec(
            select(PromoMatchScreenshot)
            .where(
                PromoMatchScreenshot.match_id == source.match_id,
                PromoMatchScreenshot.kind == "player_loadout",
                PromoMatchScreenshot.side == source.side,
            )
            .order_by(PromoMatchScreenshot.round_no)
        ).all()
        if not siblings:
            siblings = [source]

        # Pre-fetch every PromoExtractedField row for the sibling
        # screenshots in one query, then pivot by screenshot_id.
        sibling_ids = [s.id for s in siblings]
        all_fields = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id.in_(sibling_ids)
            )
        ).all()
        fields_by_screenshot: dict[int, dict[str, PromoExtractedField]] = {}
        for f in all_fields:
            fields_by_screenshot.setdefault(f.screenshot_id, {})[
                f.region_slug
            ] = f

        # Resolve player_name from the source loadout if not passed in.
        source_fields = fields_by_screenshot.get(source.id, {})
        if player_name is None:
            pn_field = source_fields.get("player_name")
            player_name = (pn_field.text if pn_field else None) or None

        # Collect every distinct character_id across all siblings'
        # portrait rows so the Character-name lookup is one query.
        char_ids: set[int] = set()
        for slug_map in fields_by_screenshot.values():
            for slug, f in slug_map.items():
                if f.character_id and slug.endswith(".portrait"):
                    char_ids.add(f.character_id)
        char_names: dict[int, str] = {}
        if char_ids:
            crows = session.exec(
                select(Character.id, Character.name).where(
                    Character.id.in_(char_ids)
                )
            ).all()
            char_names = {int(cid): str(name) for cid, name in crows}

        portrait_bbox_by_slug = {
            r.slug: r.bbox for r in PLAYER_LOADOUT
            if r.slug.endswith(".portrait")
        }

        def _build_round_data(loadout: PromoMatchScreenshot) -> dict:
            by_slug = fields_by_screenshot.get(loadout.id, {})

            team_cp_field = by_slug.get("team_cp")
            try:
                team_cp = (
                    int(team_cp_field.normalized)
                    if team_cp_field and team_cp_field.normalized else None
                )
            except (TypeError, ValueError):
                team_cp = None

            characters = []
            for n in range(1, 6):
                portrait = by_slug.get(f"char{n}.portrait")
                cp_field = by_slug.get(f"char{n}.cp")
                doll = by_slug.get(f"char{n}.doll")
                try:
                    cp = (
                        int(cp_field.normalized)
                        if cp_field and cp_field.normalized else None
                    )
                except (TypeError, ValueError):
                    cp = None
                characters.append({
                    "slot": n,
                    "character_id": portrait.character_id if portrait else None,
                    "character_name": (
                        char_names.get(portrait.character_id)
                        if portrait and portrait.character_id else None
                    ),
                    "raw_name": portrait.text if portrait else None,
                    "cp": cp,
                    "portrait_bbox": portrait_bbox_by_slug.get(
                        f"char{n}.portrait"
                    ),
                    "doll_label": doll.text if doll else None,
                    "doll_key": doll.normalized if doll else None,
                    "doll_manually_corrected": (
                        doll.manually_corrected if doll else False
                    ),
                })
            return {
                "round_no": loadout.round_no,
                "team_cp": team_cp,
                "source_screenshot_id": loadout.id,
                "source_image_url": _promo_image_url(loadout.file_path),
                "characters": characters,
            }

        rounds_data = [_build_round_data(ld) for ld in siblings]

        # Resolve the source match's round_label (tournament-stage label).
        source_match = session.get(PromoMatch, source.match_id)
        source_round_label = source_match.round_label if source_match else None

        return {
            "player_name": player_name,
            "source_screenshot_id": source.id,
            "source_round_label": source_round_label,
            "rounds": rounds_data,
            "match_tier": tier,
            "hash_distance": hash_distance,
        }

    def _promo_derived_loadouts(session, match_id: int) -> Optional[dict]:
        """For results-only matches (top_32 / top_16 / semifinals / finals),
        build per-side, per-round team comps from the duel result extractions.

        Returns ``None`` when there are no duel screenshots or no extractions.
        Otherwise returns:

        ``{"left": {"name": str|None, "rounds": [{"round_no": int, "winner": str|None, "screenshot_id": int, "characters": [{...}]*5}]}, "right": {...}}``

        Each character is a dict with: slot (1..5), raw_name, character_id,
        character_name, match_score, atk_int, def_int, heal_int, hp_pct.
        """
        duels = session.exec(
            select(PromoMatchScreenshot)
            .where(
                PromoMatchScreenshot.match_id == match_id,
                PromoMatchScreenshot.kind == "results_duel",
            )
            .order_by(PromoMatchScreenshot.round_no)
        ).all()
        if not duels:
            return None

        # Player names + per-round winners come from the overview extractions.
        overview = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.match_id == match_id,
                PromoMatchScreenshot.kind == "results_overview",
            )
        ).first()
        left_name = right_name = None
        winners: dict[int, str] = {}
        if overview is not None:
            ext_overview = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.screenshot_id == overview.id
                )
            ).all()
            for e in ext_overview:
                if e.region_slug == "left_name":
                    left_name = e.text
                elif e.region_slug == "right_name":
                    right_name = e.text
                elif e.region_slug.endswith("_winner") and e.normalized:
                    # 'round1_winner' → 1
                    try:
                        n = int(e.region_slug[len("round"):-len("_winner")])
                        winners[n] = e.normalized
                    except ValueError:
                        pass

        # Collect every duel's extractions in one shot, then pivot.
        duel_ids = [d.id for d in duels]
        duel_fields = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id.in_(duel_ids)
            )
        ).all()
        by_screenshot: dict[int, dict[str, PromoExtractedField]] = {}
        char_ids: set[int] = set()
        for f in duel_fields:
            by_screenshot.setdefault(f.screenshot_id, {})[f.region_slug] = f
            if f.character_id is not None:
                char_ids.add(f.character_id)

        char_names: dict[int, str] = {}
        if char_ids:
            rows = session.exec(
                select(Character.id, Character.name).where(
                    Character.id.in_(char_ids)
                )
            ).all()
            char_names = {int(cid): str(name) for cid, name in rows}

        def _try_int(s: Optional[str]) -> Optional[int]:
            if not s:
                return None
            try:
                return int(s)
            except ValueError:
                return None

        sides: dict[str, dict] = {
            "left": {"name": left_name, "rounds": []},
            "right": {"name": right_name, "rounds": []},
        }
        for duel in duels:
            slugs = by_screenshot.get(duel.id, {})
            for side in ("left", "right"):
                chars = []
                for n in range(1, 6):
                    name = slugs.get(f"{side}.char{n}.name")
                    atk = slugs.get(f"{side}.char{n}.atk")
                    deff = slugs.get(f"{side}.char{n}.def")
                    heal = slugs.get(f"{side}.char{n}.heal")
                    hp = slugs.get(f"{side}.char{n}.hp")
                    chars.append({
                        "slot": n,
                        "raw_name": name.text if name else None,
                        "character_id": name.character_id if name else None,
                        "character_name": (
                            char_names.get(name.character_id)
                            if name and name.character_id else None
                        ),
                        "match_score": (
                            name.character_match_score if name else None
                        ),
                        "atk_int": _try_int(atk.normalized) if atk else None,
                        "def_int": _try_int(deff.normalized) if deff else None,
                        "heal_int": _try_int(heal.normalized) if heal else None,
                        "hp_pct": hp.normalized if hp else None,
                    })
                sides[side]["rounds"].append({
                    "round_no": duel.round_no,
                    "screenshot_id": duel.id,
                    "winner": winners.get(duel.round_no),
                    "characters": chars,
                })
        return sides

    def _promo_match_thumb_url(session, match_id: int) -> Optional[str]:
        """URL of a representative screenshot for a match — used as a tile thumbnail.

        Prefers ``results_overview`` (most recognizable), falls back to
        any other screenshot in the match.
        """
        shots = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.match_id == match_id
            )
        ).all()
        if not shots:
            return None
        for s in shots:
            if s.kind == "results_overview":
                return _promo_image_url(s.file_path)
        return _promo_image_url(shots[0].file_path)

    _DUEL_ROUND_LABELS = ("quarterfinals", "semifinals", "finals")
    _PROMO_ROUND_LABELS = ("round_64", "top_32", "top_16")

    @app.get("/promo", response_class=HTMLResponse)
    def promo_index(request: Request) -> Response:
        """Capture dates → tournaments grid (mixed formats)."""
        with get_session(engine) as session:
            tournaments = session.exec(
                select(PromoTournament).order_by(
                    PromoTournament.capture_date.desc(),
                    PromoTournament.captured_at.desc(),
                )
            ).all()
            t_meta = []
            for t in tournaments:
                n_matches = len(
                    session.exec(
                        select(PromoMatch).where(PromoMatch.tournament_id == t.id)
                    ).all()
                )
                n_groups = len(
                    session.exec(
                        select(PromoGroup).where(PromoGroup.tournament_id == t.id)
                    ).all()
                )
                t_meta.append({
                    "row": t,
                    "format": tournament_format(t.storage_root),
                    "n_matches": n_matches,
                    "n_groups": n_groups,
                })
            by_date: dict[str, list] = {}
            for m in t_meta:
                key = m["row"].capture_date.isoformat()
                by_date.setdefault(key, []).append(m)
        return templates.TemplateResponse(
            request,
            "promo_index.html",
            {"by_date": by_date, "n_tournaments": len(tournaments)},
        )

    @app.get("/promo/{tournament_id}", response_class=HTMLResponse)
    def promo_tournament(request: Request, tournament_id: int) -> Response:
        """Tournament landing page.

        Promo tournaments show 8 group tiles. Champions duel has no
        groups — the page shows three round sections (QF / SF / Final)
        with match tiles directly, identical in layout to a promo
        group page.
        """
        with get_session(engine) as session:
            tournament = session.get(PromoTournament, tournament_id)
            if tournament is None:
                raise HTTPException(404, f"tournament {tournament_id} not found")
            fmt = tournament_format(tournament.storage_root)
            ctx: dict = {"tournament": tournament, "format": fmt}
            if fmt == FORMAT_PROMO:
                groups = session.exec(
                    select(PromoGroup)
                    .where(PromoGroup.tournament_id == tournament_id)
                    .order_by(PromoGroup.group_no)
                ).all()
                group_meta = []
                for g in groups:
                    n_matches = len(
                        session.exec(
                            select(PromoMatch).where(PromoMatch.group_id == g.id)
                        ).all()
                    )
                    group_meta.append({"row": g, "n_matches": n_matches})
                ctx["groups"] = group_meta
            else:
                # Duel: build round sections directly off the matches.
                matches = session.exec(
                    select(PromoMatch)
                    .where(PromoMatch.tournament_id == tournament_id)
                    .order_by(PromoMatch.round_label, PromoMatch.match_no)
                ).all()
                sections: dict[str, list] = {
                    label: [] for label in _DUEL_ROUND_LABELS
                }
                for m in matches:
                    if m.round_label in sections:
                        thumb = _promo_match_thumb_url(session, m.id)
                        sections[m.round_label].append({"row": m, "thumb": thumb})
                ctx["sections"] = sections
        return templates.TemplateResponse(request, "promo_tournament.html", ctx)

    @app.get("/promo/{tournament_id}/groups/{group_no}", response_class=HTMLResponse)
    def promo_group(request: Request, tournament_id: int, group_no: int) -> Response:
        with get_session(engine) as session:
            tournament = session.get(PromoTournament, tournament_id)
            if tournament is None:
                raise HTTPException(404, f"tournament {tournament_id} not found")
            group = session.exec(
                select(PromoGroup).where(
                    PromoGroup.tournament_id == tournament_id,
                    PromoGroup.group_no == group_no,
                )
            ).first()
            if group is None:
                raise HTTPException(
                    404, f"group {group_no} not found in tournament {tournament_id}"
                )
            matches = session.exec(
                select(PromoMatch)
                .where(PromoMatch.group_id == group.id)
                .order_by(PromoMatch.round_label, PromoMatch.match_no)
            ).all()
            sections: dict[str, list] = {"round_64": [], "top_32": [], "top_16": []}
            for m in matches:
                thumb = _promo_match_thumb_url(session, m.id)
                if m.round_label in sections:
                    sections[m.round_label].append({"row": m, "thumb": thumb})
        return templates.TemplateResponse(
            request,
            "promo_group.html",
            {"tournament": tournament, "group": group, "sections": sections},
        )

    @app.get("/promo/{tournament_id}/matches/{match_id}", response_class=HTMLResponse)
    def promo_match(
        request: Request, tournament_id: int, match_id: int
    ) -> Response:
        with get_session(engine) as session:
            match = session.get(PromoMatch, match_id)
            if match is None or match.tournament_id != tournament_id:
                raise HTTPException(404, f"match {match_id} not found")
            tournament = session.get(PromoTournament, tournament_id)
            fmt = tournament_format(tournament.storage_root) if tournament else FORMAT_PROMO
            # Group is only meaningful for promo tournaments.
            group = (
                session.get(PromoGroup, match.group_id)
                if fmt == FORMAT_PROMO else None
            )
            shots = session.exec(
                select(PromoMatchScreenshot)
                .where(PromoMatchScreenshot.match_id == match_id)
                .order_by(
                    PromoMatchScreenshot.kind,
                    PromoMatchScreenshot.side,
                    PromoMatchScreenshot.round_no,
                )
            ).all()
            buckets: dict[str, list] = {
                "player_top": [],
                "player_bottom": [],
                "results_overview": [],
                "results_duel": [],
            }
            for s in shots:
                key = s.kind
                if s.kind == "player_loadout":
                    key = f"player_{s.side}"
                if key in buckets:
                    buckets[key].append({
                        "row": s,
                        "url": _promo_image_url(s.file_path),
                    })
            # Derived team comps from duel results AND the canonical
            # loadout lookup (round_64 / quarterfinals where loadouts
            # exist) for portraits + CPs + dolls. Always compute when
            # there's a results overview — round_64 matches benefit
            # from the same canonical-team panel that results-only
            # matches use, since the OCR-based lookup naturally
            # picks each side's own loadout.
            derived_loadouts = _promo_derived_loadouts(session, match_id)
            canonical = None
            if derived_loadouts:
                overview = session.exec(
                    select(PromoMatchScreenshot).where(
                        PromoMatchScreenshot.match_id == match_id,
                        PromoMatchScreenshot.kind == "results_overview",
                    )
                ).first()
                overview_id = overview.id if overview else None
                canonical = {
                    "left": _promo_canonical_loadout(
                        session,
                        derived_loadouts["left"]["name"],
                        current_overview_id=overview_id,
                        current_side="left",
                    ),
                    "right": _promo_canonical_loadout(
                        session,
                        derived_loadouts["right"]["name"],
                        current_overview_id=overview_id,
                        current_side="right",
                    ),
                }
        return templates.TemplateResponse(
            request,
            "promo_match.html",
            {
                "tournament": tournament,
                "group": group,
                "match": match,
                "derived_loadouts": derived_loadouts,
                "canonical": canonical,
                "buckets": buckets,
                "format": fmt,
                "ref_w": PROMO_REF_SIZE[0],
                "ref_h": PROMO_REF_SIZE[1],
            },
        )

    def _promo_matching_provenance(
        session, viewer_screenshot_id: int, from_match_id: int
    ) -> Optional[dict]:
        """Explain how this loadout came to be picked as canonical for
        ``from_match_id``.

        Compares the loadout's ``player_name`` OCR against the from-match's
        overview ``left_name`` / ``right_name`` and reports which side
        matched + at what tier (exact / case-insensitive / fuzzy %).
        """
        from rapidfuzz import fuzz

        viewer = session.get(PromoMatchScreenshot, viewer_screenshot_id)
        if viewer is None or viewer.kind != "player_loadout":
            return None
        from_match = session.get(PromoMatch, from_match_id)
        if from_match is None:
            return None

        loadout_player_field = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id == viewer_screenshot_id,
                PromoExtractedField.region_slug == "player_name",
            )
        ).first()
        loadout_player = (loadout_player_field.text if loadout_player_field else None) or None

        from_overview = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.match_id == from_match_id,
                PromoMatchScreenshot.kind == "results_overview",
            )
        ).first()
        left_name = right_name = None
        if from_overview is not None:
            for f in session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.screenshot_id == from_overview.id,
                    PromoExtractedField.region_slug.in_(["left_name", "right_name"]),
                )
            ).all():
                if f.region_slug == "left_name":
                    left_name = f.text
                elif f.region_slug == "right_name":
                    right_name = f.text

        matched_side = None
        tier = None
        score: Optional[float] = None
        if loadout_player:
            lp = loadout_player.strip()
            if (left_name or "").strip() == lp:
                matched_side, tier = "left", "exact"
            elif (right_name or "").strip() == lp:
                matched_side, tier = "right", "exact"
            elif left_name and (left_name).strip().lower() == lp.lower():
                matched_side, tier = "left", "case-insensitive"
            elif right_name and (right_name).strip().lower() == lp.lower():
                matched_side, tier = "right", "case-insensitive"
            else:
                ls = fuzz.ratio(lp.lower(), (left_name or "").lower()) if left_name else 0
                rs = fuzz.ratio(lp.lower(), (right_name or "").lower()) if right_name else 0
                if max(ls, rs) >= 60:
                    if ls >= rs:
                        matched_side, score = "left", float(ls)
                    else:
                        matched_side, score = "right", float(rs)
                    tier = "fuzzy"

        # Build a human-readable label for the from-match.
        if from_match.match_no is not None:
            label = f"{from_match.round_label.replace('_', ' ')} match {from_match.match_no}"
        else:
            label = from_match.round_label.replace("_", " ")

        return {
            "from_match_id": from_match_id,
            "from_match_tournament_id": from_match.tournament_id,
            "from_match_label": label,
            "loadout_player_name": loadout_player,
            "left_name": left_name,
            "right_name": right_name,
            "matched_side": matched_side,
            "tier": tier,
            "score": score,
        }

    @app.get("/promo/screenshots/{screenshot_id}", response_class=HTMLResponse)
    def promo_screenshot_viewer(
        request: Request,
        screenshot_id: int,
        from_match: Optional[int] = None,
    ) -> Response:
        """Double-pane viewer: original on left, labeled crops on right.

        Hovering a crop on the right highlights its bbox over the
        original on the left. ``?from_match={id}`` populates a banner
        at the top explaining how this loadout was selected as that
        match's canonical team.
        """
        with get_session(engine) as session:
            screenshot = session.get(PromoMatchScreenshot, screenshot_id)
            if screenshot is None:
                raise HTTPException(404, f"screenshot {screenshot_id} not found")
            match = session.get(PromoMatch, screenshot.match_id)
            tournament = (
                session.get(PromoTournament, match.tournament_id) if match else None
            )
            fmt = tournament_format(tournament.storage_root) if tournament else FORMAT_PROMO
            group = (
                session.get(PromoGroup, match.group_id)
                if match and fmt == FORMAT_PROMO else None
            )
        url = _promo_image_url(screenshot.file_path)
        if url is None:
            raise HTTPException(
                404,
                f"image not under {_PROMO_ROOT}: {screenshot.file_path}",
            )
        regions = promo_regions_for_kind(screenshot.kind)
        ref_w, ref_h = PROMO_REF_SIZE
        view_regions = _promo_view_regions(engine, screenshot.id, regions)
        provenance = None
        if from_match is not None:
            with get_session(engine) as session:
                provenance = _promo_matching_provenance(
                    session, screenshot.id, from_match
                )
        return templates.TemplateResponse(
            request,
            "promo_viewer.html",
            {
                "screenshot": screenshot,
                "match": match,
                "group": group,
                "tournament": tournament,
                "image_url": url,
                "regions": regions,
                "view_regions": view_regions,
                "ref_w": ref_w,
                "ref_h": ref_h,
                "format": fmt,
                "provenance": provenance,
            },
        )

    def _promo_view_regions(engine, screenshot_id: int, regions):
        """Build per-region view-model dicts for the viewer template.

        Each entry merges the base ``Region`` with any
        ``PromoExtractedField`` row keyed on the same slug, plus the
        derived ``round{N}_winner`` value for round-strip regions and
        the matched character name for ``*.name`` fields.
        """
        with get_session(engine) as session:
            extracted = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.screenshot_id == screenshot_id
                )
            ).all()
            by_slug = {e.region_slug: e for e in extracted}
            char_ids = {e.character_id for e in extracted if e.character_id}
            char_names: dict[int, str] = {}
            if char_ids:
                rows = session.exec(
                    select(Character.id, Character.name).where(
                        Character.id.in_(char_ids)
                    )
                ).all()
                char_names = {int(cid): str(name) for cid, name in rows}

        out = []
        for r in regions:
            ext = by_slug.get(r.slug)
            matched = (
                char_names.get(ext.character_id)
                if ext and ext.character_id is not None
                else None
            )
            extra = None
            if r.slug.endswith("_strip"):
                winner_ext = by_slug.get(r.slug.replace("_strip", "_winner"))
                if winner_ext is not None and winner_ext.normalized:
                    extra = f"winner: {winner_ext.normalized}"
            out.append(
                {
                    "region": r,
                    "ext": ext,
                    "matched_character": matched,
                    "extra": extra,
                }
            )
        return out

    @app.get("/promo/screenshots/{screenshot_id}/overlay", response_class=HTMLResponse)
    def promo_screenshot_overlay(request: Request, screenshot_id: int) -> Response:
        """Verification page: every region drawn over the source image.

        Used to spot misaligned coords before building the rest of the
        UI. ``promo_regions_for_kind(kind)`` selects the schema that
        applies to this screenshot's ``kind``.
        """
        with get_session(engine) as session:
            screenshot = session.get(PromoMatchScreenshot, screenshot_id)
            if screenshot is None:
                raise HTTPException(404, f"screenshot {screenshot_id} not found")
            match = session.get(PromoMatch, screenshot.match_id)
            tournament = (
                session.get(PromoTournament, match.tournament_id) if match else None
            )
            fmt = tournament_format(tournament.storage_root) if tournament else FORMAT_PROMO
        url = _promo_image_url(screenshot.file_path)
        if url is None:
            raise HTTPException(
                404,
                f"image not under {_PROMO_ROOT}: {screenshot.file_path}",
            )
        regions = promo_regions_for_kind(screenshot.kind)
        ref_w, ref_h = PROMO_REF_SIZE
        return templates.TemplateResponse(
            request,
            "promo_overlay.html",
            {
                "screenshot": screenshot,
                "match": match,
                "tournament": tournament,
                "image_url": url,
                "regions": regions,
                "ref_w": ref_w,
                "ref_h": ref_h,
                "kinds": PROMO_KINDS,
                "format": fmt,
            },
        )

    # ------------------------------------------------------------------
    # Audit — review + correct extracted-field classifications
    # ------------------------------------------------------------------

    from ..roster.promo_tournament_doll_match import (
        DISPLAY_LABELS as _DOLL_DISPLAY_LABELS,
        EXEMPLAR_FILES as _DOLL_EXEMPLAR_FILES,
    )

    # Stable display order across the audit page button row.
    _DOLL_AUDIT_KEYS: tuple[str, ...] = (
        "r_partial",
        "r_max",
        "sr_partial",
        "sr_max",
        "treasure_partial",
        "treasure_max",
        "unknown",
    )

    @app.get("/audit", response_class=HTMLResponse)
    def audit_index(request: Request) -> Response:
        with get_session(engine) as session:
            doll_total = len(session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.region_slug.like("%.doll")
                )
            ).all())
            doll_corrected = len(session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.region_slug.like("%.doll"),
                    PromoExtractedField.manually_corrected == True,  # noqa: E712
                )
            ).all())
        return templates.TemplateResponse(
            request,
            "audit_index.html",
            {
                "doll_total": doll_total,
                "doll_corrected": doll_corrected,
            },
        )

    @app.get("/audit/dolls", response_class=HTMLResponse)
    def audit_dolls_root() -> Response:
        with get_session(engine) as session:
            rows = _audit_doll_sorted(session)
            if not rows:
                return RedirectResponse("/audit/dolls/0", status_code=302)
            return RedirectResponse(
                f"/audit/dolls/{rows[0].id}", status_code=302
            )

    def _audit_doll_sorted(session) -> list[PromoExtractedField]:
        """All ``%.doll`` extractions in priority order.

        Sort: ``manually_corrected ASC`` (un-audited first), then
        ``confidence ASC NULLS FIRST`` (suspicious first), then ``id ASC``.
        Field-id-based audit URLs use this list for prev/next + position
        lookup. Confidence and manually_corrected only change via the
        audit POSTs, so the order between requests is stable enough for
        per-field URLs.
        """
        return session.exec(
            select(PromoExtractedField)
            .where(PromoExtractedField.region_slug.like("%.doll"))
            .order_by(
                PromoExtractedField.manually_corrected.asc(),
                PromoExtractedField.confidence.asc().nulls_first(),
                PromoExtractedField.id.asc(),
            )
        ).all()

    def _audit_doll_neighbors(
        rows: list[PromoExtractedField], field_id: int
    ) -> tuple[int, Optional[int], Optional[int]]:
        """Return ``(position_index, prev_id, next_id)`` for the field
        with ``field_id`` in the sorted list. ``-1, None, None`` when
        not found."""
        for i, r in enumerate(rows):
            if r.id == field_id:
                prev_id = rows[i - 1].id if i > 0 else None
                next_id = rows[i + 1].id if i < len(rows) - 1 else None
                return i, prev_id, next_id
        return -1, None, None

    @app.get("/audit/dolls/{field_id}", response_class=HTMLResponse)
    def audit_dolls(request: Request, field_id: int) -> Response:
        from ..roster.promo_tournament_regions import PLAYER_LOADOUT

        with get_session(engine) as session:
            rows = _audit_doll_sorted(session)
            if not rows:
                return templates.TemplateResponse(
                    request,
                    "audit_dolls.html",
                    {"empty": True, "total": 0},
                )
            position, prev_id, next_id = _audit_doll_neighbors(rows, field_id)
            if position < 0:
                # Field doesn't match a doll-slug row — redirect to the
                # head of the list rather than 404 so the audit flow
                # stays usable.
                return RedirectResponse(
                    f"/audit/dolls/{rows[0].id}", status_code=302
                )
            field = rows[position]
            shot = session.get(PromoMatchScreenshot, field.screenshot_id)
            total = len(rows)
            match = session.get(PromoMatch, shot.match_id) if shot else None
            tournament = (
                session.get(PromoTournament, match.tournament_id)
                if match else None
            )
            group = (
                session.get(PromoGroup, match.group_id) if match else None
            )
            # Player + same-slot character_id from the loadout's other
            # extractions, for breadcrumb context.
            player_name_field = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.screenshot_id == shot.id,
                    PromoExtractedField.region_slug == "player_name",
                )
            ).first() if shot else None
            slot = field.region_slug.split(".")[0]  # e.g. "char3"
            portrait_field = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.screenshot_id == shot.id,
                    PromoExtractedField.region_slug == f"{slot}.portrait",
                )
            ).first() if shot else None
            character_name = None
            if portrait_field and portrait_field.character_id:
                row = session.exec(
                    select(Character.name).where(
                        Character.id == portrait_field.character_id
                    )
                ).first()
                character_name = str(row) if row else None

        # Compute the source image URL + bbox for this doll region so
        # the page can render the icon via background-position.
        image_url = _promo_image_url(shot.file_path) if shot else None
        bbox = next(
            (r.bbox for r in PLAYER_LOADOUT if r.slug == field.region_slug),
            None,
        )
        ref_w, ref_h = PROMO_REF_SIZE

        # Build the choice list for the buttons row.
        choices = []
        for key in _DOLL_AUDIT_KEYS:
            filename = _DOLL_EXEMPLAR_FILES.get(key)
            choices.append({
                "key": key,
                "label": _DOLL_DISPLAY_LABELS.get(key, key),
                "exemplar_url": (
                    f"/static/doll-icons/{filename}" if filename else None
                ),
                "is_current": (field.normalized == key),
            })

        return templates.TemplateResponse(
            request,
            "audit_dolls.html",
            {
                "empty": False,
                "field": field,
                "shot": shot,
                "match": match,
                "tournament": tournament,
                "group": group,
                "player_name": (
                    player_name_field.text if player_name_field else None
                ),
                "slot": slot,
                "character_name": character_name,
                "image_url": image_url,
                "bbox": bbox,
                "ref_w": ref_w,
                "ref_h": ref_h,
                "choices": choices,
                "total": total,
                "position": position,
                "prev_id": prev_id,
                "next_id": next_id,
            },
        )

    @app.post("/audit/dolls/{field_id}/correct")
    def audit_dolls_correct(
        field_id: int,
        normalized: str = Form(...),
        next_id: Optional[int] = Form(None),
    ) -> Response:
        if normalized not in _DOLL_AUDIT_KEYS:
            raise HTTPException(400, f"unknown doll key: {normalized}")
        with get_session(engine) as session:
            field = session.get(PromoExtractedField, field_id)
            if field is None:
                raise HTTPException(404, f"field {field_id} not found")
            field.normalized = normalized
            field.text = _DOLL_DISPLAY_LABELS.get(normalized, normalized)
            field.confidence = 1.0
            field.manually_corrected = True
            session.add(field)
            session.commit()
        # Auto-advance to the embedded next field so that browser-back
        # always returns to the just-corrected field with the user's
        # pick highlighted. If we computed "next" post-correction the
        # field would have shuffled to the end of the sorted list.
        if next_id is not None:
            return RedirectResponse(
                f"/audit/dolls/{next_id}", status_code=303
            )
        return RedirectResponse(
            f"/audit/dolls/{field_id}", status_code=303
        )

    @app.post("/audit/dolls/{field_id}/skip")
    def audit_dolls_skip(
        field_id: int,
        prev_id: Optional[int] = Form(None),
        next_id: Optional[int] = Form(None),
        direction: str = Form("next"),
    ) -> Response:
        target = prev_id if direction == "prev" else next_id
        if target is None:
            target = field_id
        return RedirectResponse(
            f"/audit/dolls/{target}", status_code=303
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "matcher_loaded": app.state.matcher is not None}

    return app
