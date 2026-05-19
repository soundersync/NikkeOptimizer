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
    RosterSnapshot,
    RosterSnapshotCharacter,
)
from ..roster.portrait_matcher import PortraitMatcher
from ..roster.promo_tournament_ingest import (
    FORMAT_DUEL,
    FORMAT_LEAGUE,
    FORMAT_PROMO,
    FORMAT_PROMO_PLAYER_DATA,
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

    def _serve_resized_png(path: Path, w: int) -> Response:
        """Downscale a PNG to ``w`` pixels wide (preserve aspect ratio)
        and serve as image/png. Used by /matches for inline thumbnails
        on session cards so we don't ship 1MB PNGs per cell.
        """
        from io import BytesIO
        from PIL import Image as _PILImage
        try:
            img = _PILImage.open(path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"open failed: {exc}")
        if img.width > w:
            h = round(img.height * (w / img.width))
            img = img.resize((w, h), _PILImage.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, "PNG", optimize=True)
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/png")

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

    def _build_session_card(
        rows: list[ArenaMatch], snap_by_id: dict[int, str],
    ) -> dict:
        """Build the per-session view-model for the /matches page card.

        Sorts rows by round_index (1..5). Derives the session-level
        score (W-L) from per-round outcomes, the canonical user/opp
        names, and a header subtitle that varies by mode.
        """
        rows = sorted(rows, key=lambda r: r.round_index or 0)
        first = rows[0]
        mode = first.mode
        wins = sum(1 for r in rows if r.outcome == "win")
        losses = sum(1 for r in rows if r.outcome == "loss")

        # Session-level snap status: champion has a fixed opponent so
        # all rows share the same status; rookie has 5 different opps
        # so we aggregate as "all" / "some" / "none".
        sess_snap_summary: str
        if mode == "champion":
            sess_snap_summary = snap_by_id.get(first.id, "none")
        else:
            statuses = [snap_by_id.get(r.id, "none") for r in rows]
            if all(s == "both" for s in statuses):
                sess_snap_summary = "both"
            elif any(s == "both" for s in statuses):
                sess_snap_summary = "partial"
            else:
                sess_snap_summary = "none"

        # Champion sessions have a fixed (user, opp) pair; rookie
        # sessions face 5 different opponents.
        opp_label = first.opponent_username if mode == "champion" else None

        # Header subtitle.
        if mode == "champion":
            # session_label looks like "Champions g1-finals M1 R1 2026-05-14"
            # — strip the "R{n}" so the session-level header reads cleanly.
            import re as _re
            base = (first.session_label or "").strip()
            base = _re.sub(r" R\d+", "", base)
            subtitle = base or first.session_id
        else:
            # Rookie session_label: "Rookie Arena 2026-05-18 17:22 UTC"
            subtitle = first.session_label or first.session_id

        captured_local = None
        if first.captured_at is not None:
            from datetime import timezone as _tz
            dt = first.captured_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            captured_local = dt.astimezone().strftime("%Y-%m-%d %-I:%M %p %Z")

        cells: list[dict] = []
        for r in rows:
            cells.append(_build_round_cell(r, snap_by_id.get(r.id, "none")))

        return {
            "session_id": first.session_id or "",
            "mode": mode,
            "subtitle": subtitle,
            "captured_local": captured_local,
            "user_label": first.user_username,
            "opp_label": opp_label,
            "wins": wins,
            "losses": losses,
            "snap_summary": sess_snap_summary,
            "cells": cells,
        }

    def _build_round_cell(
        r: ArenaMatch, snap_status: str,
    ) -> dict:
        """One round/battle cell within a session card."""
        thumb_w = 240
        cell = {
            "capture_id": r.id,
            "round_index": r.round_index,
            "outcome": r.outcome,
            "opp_username": r.opponent_username,
            "user_team": [n for n in (r.user_team or []) if n],
            "opp_team": [n for n in (r.opponent_team or []) if n],
            "snap": snap_status,
            "detail_url": f"/captures/{r.id}",
            "loadout_thumb_url": None,
            "loadout_full_url": None,
            "opp_loadout_thumb_url": None,
            "opp_loadout_full_url": None,
            "result_thumb_url": None,
            "result_full_url": None,
            "opp_level": None,
        }
        if r.pre_battle_screenshot:
            cell["loadout_thumb_url"] = (
                f"/captures/{r.id}/screenshot/pre?w={thumb_w}"
            )
            cell["loadout_full_url"] = f"/captures/{r.id}/screenshot/pre"
        if r.battle_record_screenshot:
            cell["result_thumb_url"] = (
                f"/captures/{r.id}/screenshot/record?w={thumb_w}"
            )
            cell["result_full_url"] = f"/captures/{r.id}/screenshot/record"
        # Champion: second-player loadout served by the new endpoint.
        if r.mode == "champion" and r.session_id and r.round_index:
            base = f"/sessions/{r.session_id}/round/{r.round_index}/opp-loadout"
            cell["opp_loadout_thumb_url"] = f"{base}?w={thumb_w}"
            cell["opp_loadout_full_url"] = base
        # Rookie opponent level — pulled out of capture_quality.
        if r.mode == "rookie" and r.capture_quality:
            lvl = r.capture_quality.get("opponent_level")
            if isinstance(lvl, int):
                cell["opp_level"] = lvl
        return cell

    def _arena_match_snapshot_status(row: ArenaMatch, session) -> str:
        """Return 'both' / 'user' / 'opp' / 'none' for the row's
        snapshot completeness, **dispatched by mode** because Champions
        and Rookie use different snapshot systems:

          * Champion: ``user_snapshot_id`` + ``opponent_snapshot_id``
            FKs point at ``RosterSnapshot`` rows (with character data
            verified at build time by ``_find_snapshot_id``).
          * Rookie: user side is the live ``OwnedCharacter`` table
            (always present; refreshed daily by the post-rookie
            self-refresh hook). Opponent side is
            ``RookieArenaSnapshot`` keyed on
            ``(run_date, player_username)`` with ≥1 char row.
        """
        if row.mode == "rookie":
            from ..data.models import (
                RookieArenaSnapshot, RookieArenaSnapshotCharacter,
            )
            user_ok = True  # OwnedCharacter is always present for the user
            opp_ok = False
            opp_name = (row.opponent_username or "").strip().upper()
            if opp_name and row.captured_at is not None:
                ras = session.exec(
                    select(RookieArenaSnapshot).where(
                        RookieArenaSnapshot.run_date == row.captured_at.date(),
                    )
                ).all()
                for r in ras:
                    if (r.player_username or "").strip().upper() != opp_name:
                        continue
                    has_chars = session.exec(
                        select(RookieArenaSnapshotCharacter).where(
                            RookieArenaSnapshotCharacter.snapshot_id == r.id
                        ).limit(1)
                    ).first() is not None
                    if has_chars:
                        opp_ok = True
                        break
        else:
            # Champion (or any future mode that uses the FK columns).
            user_ok = row.user_snapshot_id is not None
            opp_ok = row.opponent_snapshot_id is not None

        if user_ok and opp_ok:
            return "both"
        if user_ok:
            return "user"
        if opp_ok:
            return "opp"
        return "none"

    @app.get("/captures", response_class=HTMLResponse)
    @app.get("/matches", response_class=HTMLResponse)
    def captures_list(
        request: Request,
        mode: Optional[str] = None,
        outcome: Optional[str] = None,
        snapshots: Optional[str] = None,
        since: Optional[str] = None,
        page: int = 1,
    ) -> Response:
        """Match history grouped by session (rookie run / champion duel).

        Each session card surfaces:
          * Header: mode, captured-at (local time), W-L score, snap status
          * 5 round/battle cells: inline loadout + result thumbnails,
            outcome pill, per-cell snap status, link to /captures/{id}
            detail page
        """
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        SESSIONS_PER_PAGE = 10
        page = max(1, page)

        with get_session(engine) as session:
            # Pull the union we'll show (after filters), then group + paginate.
            query = select(ArenaMatch).where(ArenaMatch.mode.in_(("rookie", "champion")))
            if mode in ("rookie", "champion"):
                query = query.where(ArenaMatch.mode == mode)
            rows = list(session.exec(query).all())

            if outcome == "untagged":
                rows = [r for r in rows if not r.outcome]
            elif outcome in ("win", "loss"):
                rows = [r for r in rows if r.outcome == outcome]

            row_snap_status = {
                r.id: _arena_match_snapshot_status(r, session)
                for r in rows if r.id is not None
            }
            if snapshots in ("both", "user", "opp", "none"):
                rows = [r for r in rows if row_snap_status.get(r.id) == snapshots]

            if since in ("7d", "30d"):
                days = 7 if since == "7d" else 30
                cutoff = _dt.now(_tz.utc) - _td(days=days)
                def _aware(d):
                    if d.tzinfo is None:
                        return d.replace(tzinfo=_tz.utc)
                    return d
                rows = [r for r in rows if _aware(r.captured_at) >= cutoff]

            # Group rows by session_id; sort sessions by their newest
            # captured_at descending so the just-ingested run is at top.
            from collections import defaultdict as _dd
            by_sid: dict[str, list[ArenaMatch]] = _dd(list)
            for r in rows:
                by_sid[r.session_id or f"_unsessioned_{r.id}"].append(r)
            def _sid_sort_key(sid: str) -> _dt:
                latest = max(
                    (r.captured_at for r in by_sid[sid] if r.captured_at),
                    default=_dt.min.replace(tzinfo=_tz.utc),
                )
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=_tz.utc)
                return latest
            session_ids = sorted(by_sid.keys(), key=_sid_sort_key, reverse=True)

            n_sessions = len(session_ids)
            total_pages = max(1, (n_sessions + SESSIONS_PER_PAGE - 1) // SESSIONS_PER_PAGE)
            page = min(page, total_pages)
            start = (page - 1) * SESSIONS_PER_PAGE
            page_sids = session_ids[start:start + SESSIONS_PER_PAGE]

            sessions = [
                _build_session_card(by_sid[sid], row_snap_status)
                for sid in page_sids
            ]

            # Dashboard counts use the unfiltered table so the user
            # always sees totals, not the filtered subset.
            all_rows = list(session.exec(select(ArenaMatch)).all())
            rookie_rows = [r for r in all_rows if r.mode == "rookie"]
            champion_rows = [r for r in all_rows if r.mode == "champion"]
            all_snap = {
                r.id: _arena_match_snapshot_status(r, session)
                for r in all_rows if r.id is not None
            }
            n_complete_snap = sum(1 for s in all_snap.values() if s == "both")
            n_rookie_sessions = len({
                r.session_id for r in rookie_rows if r.session_id
            })
            n_champion_sessions = len({
                r.session_id for r in champion_rows if r.session_id
            })

        # Last-ingest stanza from the daemon audit log.
        try:
            from .. import auto_import as ai
            last_entries = ai.parse_audit_log_entries(ai.DEFAULT_LOG_PATH, n=1)
            last_ingest = last_entries[0] if last_entries else None
        except Exception:  # noqa: BLE001
            last_ingest = None

        return templates.TemplateResponse(
            request,
            "captures_list.html",
            {
                "sessions": sessions,
                "n_sessions_total": n_sessions,
                "page": page,
                "total_pages": total_pages,
                "mode": mode,
                "outcome": outcome,
                "snapshots": snapshots,
                "since": since,
                "dashboard": {
                    "n_rookie_sessions": n_rookie_sessions,
                    "n_rookie_rows": len(rookie_rows),
                    "n_champion_sessions": n_champion_sessions,
                    "n_champion_rows": len(champion_rows),
                    "n_complete_snap": n_complete_snap,
                    "n_total_rows": len(all_rows),
                    "last_ingest": last_ingest,
                },
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

    # Legacy iOS-screenshot upload flow — removed 2026-05-18 per user
    # direction ("entirely rewritten with how we listen to incoming
    # captures now"). The Syncthing-driven auto-import daemon
    # (auto_import.py + ingest_root + ingest_rookie_root) covers
    # every capture mode end-to-end; drag-drop into the web UI is no
    # longer needed.
    #
    # Routes kept as 303-redirects so any stale bookmark / button on
    # an old tab lands somewhere useful instead of 404'ing. The
    # `/uploads/preview/{session_id}` matrix view was built for the
    # OLD per-row data model (3 rows per Champion round: P1 loadout
    # / P2 loadout / round result) and renders the NEW per-round
    # builder's single-row format incorrectly — see champion-pm130
    # incident note in `champion_arena_match.py`.

    @app.post("/captures/upload")
    @app.get("/captures/upload")
    def captures_upload_removed() -> Response:
        return RedirectResponse(url="/captures", status_code=303)

    @app.get("/uploads/preview/{session_id}")
    def upload_preview_removed(session_id: str) -> Response:
        return RedirectResponse(url="/captures", status_code=303)

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
    def captures_screenshot(
        capture_id: int, which: str, w: Optional[int] = None,
    ) -> Response:
        """Serve the PNG referenced by an ArenaMatch row.

        ``which`` is one of ``pre`` or ``record``. Only screenshots
        actually referenced by a DB row can be served — no arbitrary
        filesystem access via this endpoint.

        ``w`` (optional, capped at 1510) downscales the image to the
        given width via PIL — used by /matches for inline thumbnails so
        we don't ship 1MB PNGs per cell × 25 cells × N sessions on one
        page. Aspect ratio preserved.

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
        if w is not None and 0 < w < 1510:
            return _serve_resized_png(resolved, w)
        return FileResponse(resolved, media_type="image/png")

    @app.get("/sessions/{session_id}/round/{round_no}/opp-loadout")
    def champion_opp_loadout(
        session_id: str, round_no: int, w: Optional[int] = None,
    ) -> Response:
        """Serve the OPPONENT-side loadout PNG for a Champion duel round.

        The user-side loadout lives on ``ArenaMatch.pre_battle_screenshot``,
        but the opponent's per-round loadout isn't on the ArenaMatch row
        (the per-round payload only stores one side). For the /matches
        card view we need both, so this endpoint looks up the sibling
        loadout from ``PromoMatchScreenshot`` via the
        ``champion-pm{promo_match_id}`` session_id convention.
        """
        if not session_id.startswith("champion-pm"):
            raise HTTPException(400, "only champion sessions have an opp loadout")
        try:
            pm_id = int(session_id[len("champion-pm"):])
        except ValueError:
            raise HTTPException(400, "malformed session_id") from None
        if not 1 <= round_no <= 5:
            raise HTTPException(400, "round_no must be 1..5")
        with get_session(engine) as session:
            # Find the ArenaMatch row to know which side is "user" (so
            # we serve the OTHER side here).
            am = session.exec(
                select(ArenaMatch).where(
                    ArenaMatch.session_id == session_id,
                    ArenaMatch.round_index == round_no,
                )
            ).first()
            if am is None:
                raise HTTPException(404, "no ArenaMatch row for that round")
            cq = am.capture_quality or {}
            user_pos = cq.get("user_position", "top")
            opp_pos = "bottom" if user_pos == "top" else "top"
            opp_dir = f"player_{opp_pos}"

            shots = session.exec(
                select(PromoMatchScreenshot).where(
                    PromoMatchScreenshot.match_id == pm_id,
                    PromoMatchScreenshot.kind == "player_loadout",
                )
            ).all()
            target = None
            for s in shots:
                p = Path(s.file_path)
                if opp_dir in p.parts and p.name == f"round_{round_no}.png":
                    target = s.file_path
                    break
        if target is None:
            raise HTTPException(404, f"no {opp_dir}/round_{round_no}.png for pm{pm_id}")
        resolved = _resolve_screenshot_path(target, "champion")
        if resolved is None:
            raise HTTPException(404, f"file missing on disk: {target}")
        if w is not None and 0 < w < 1510:
            return _serve_resized_png(resolved, w)
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
                # Legacy preview removed; fall back to /captures.
                target = "/captures"
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
        # Legacy session preview removed — always bounce to /captures.
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
        tournament_id: Optional[int] = None,
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

        ``tournament_id`` scopes both tiers to a single tournament.
        Every format (league, promotion, duel) uploads its own loadouts
        with the match data, so canonical fallback should never reach
        across tournaments / seasons.
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
                    session,
                    query_ov,
                    current_side,
                    tournament_id=tournament_id,
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
        ocr_stmt = (
            select(PromoExtractedField, PromoMatchScreenshot)
            .where(
                PromoExtractedField.region_slug == "player_name",
                PromoExtractedField.screenshot_id == PromoMatchScreenshot.id,
                PromoMatchScreenshot.kind == "player_loadout",
            )
        )
        if tournament_id is not None:
            ocr_stmt = ocr_stmt.join(
                PromoMatch, PromoMatch.id == PromoMatchScreenshot.match_id
            ).where(PromoMatch.tournament_id == tournament_id)
        rows = session.exec(ocr_stmt).all()
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
        char_rarities: dict[int, str] = {}
        if char_ids:
            crows = session.exec(
                select(Character.id, Character.name, Character.rarity).where(
                    Character.id.in_(char_ids)
                )
            ).all()
            char_names = {int(cid): str(name) for cid, name, _ in crows}
            char_rarities = {
                int(cid): (rarity.value if hasattr(rarity, "value") else str(rarity))
                for cid, _, rarity in crows
            }

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
        """Beta seasons → tournaments grid (mixed formats)."""
        from ..data.config import get_self_username
        from ..data.seasons import (
            parse_season_number,
            season_for_date,
            season_start,
        )

        self_name = (get_self_username() or "").casefold()

        with get_session(engine) as session:
            tournaments = session.exec(
                select(PromoTournament).order_by(
                    PromoTournament.capture_date.desc(),
                    PromoTournament.captured_at.desc(),
                )
            ).all()
            # PromoTournament is reused by the rookie_arena ingest as
            # a per-daily-run container. Filter those out — they have
            # their own dedicated /rookie page and shouldn't appear
            # twice in the UI.
            from ..roster.promo_tournament_ingest import (
                FORMAT_ROOKIE_ARENA as _FORMAT_ROOKIE,
            )
            tournaments = [
                t for t in tournaments
                if tournament_format(t.storage_root) != _FORMAT_ROOKIE
            ]
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
                # Prefer the season encoded in storage_root (canonical
                # archive layout); fall back to deriving from the
                # captured date via the cadence table.
                parent_name = Path(t.storage_root).parent.name
                season_n = parse_season_number(parent_name)
                if season_n is None:
                    season_n = season_for_date(t.capture_date)
                fmt = tournament_format(t.storage_root)
                pd_total: Optional[int] = None
                pd_found: Optional[int] = None
                if fmt == FORMAT_PROMO_PLAYER_DATA:
                    from ..roster.promo_tournament_player_data import (
                        read_sidecar as _read_pd_sidecar,
                    )
                    from ..roster.promo_tournament_player_data_scrape import (
                        STATUS_FOUND,
                        STATUS_PRIVATE_BOTH,
                        StatusSidecar,
                    )
                    pd = _read_pd_sidecar(Path(t.storage_root))
                    pd_total = len({
                        r.player_name for r in (pd.players if pd else [])
                        if r.player_name
                    })
                    status = StatusSidecar.load_or_init(
                        Path(t.storage_root),
                        tournament_id=t.id,
                        season_number=season_n,
                    )
                    pd_found = sum(
                        1 for rec in status.players.values()
                        if rec.status in (STATUS_FOUND, STATUS_PRIVATE_BOTH)
                    )
                t_meta.append({
                    "row": t,
                    "format": fmt,
                    "n_matches": n_matches,
                    "n_groups": n_groups,
                    "season_n": season_n,
                    "pd_total": pd_total,
                    "pd_found": pd_found,
                })
            by_season: dict[int, dict] = {}
            for m in t_meta:
                bucket = by_season.setdefault(m["season_n"], {
                    "items": [],
                    "n_players": 0,
                    "has_self": False,
                    "start": season_start(m["season_n"]).isoformat(),
                })
                bucket["items"].append(m)

            # Player roster snapshots — collapsed to a single per-season
            # count + has_self indicator. The dedicated
            # ``/promo/players/<season>`` page lists individual players.
            snapshots = session.exec(
                select(RosterSnapshot).order_by(
                    RosterSnapshot.season_number.desc(),
                    RosterSnapshot.captured_at.desc(),
                )
            ).all()
            for snap in snapshots:
                bucket = by_season.setdefault(snap.season_number, {
                    "items": [],
                    "n_players": 0,
                    "has_self": False,
                    "start": season_start(snap.season_number).isoformat(),
                })
                bucket["n_players"] += 1
                if (
                    bool(self_name)
                    and (snap.player_username or "").casefold() == self_name
                ):
                    bucket["has_self"] = True

            # Newest season first.
            by_season_sorted = dict(
                sorted(by_season.items(), key=lambda kv: kv[0], reverse=True)
            )
        return templates.TemplateResponse(
            request,
            "promo_index.html",
            {
                "by_season": by_season_sorted,
                "n_tournaments": len(tournaments),
                "n_snapshots": len(snapshots),
            },
        )

    @app.get("/promo/players/{season_number}", response_class=HTMLResponse)
    def promo_players(request: Request, season_number: int) -> Response:
        """Per-season list of player roster snapshots."""
        from ..data.config import get_self_username
        from ..data.seasons import season_start

        self_name = (get_self_username() or "").casefold()
        with get_session(engine) as session:
            snapshots = session.exec(
                select(RosterSnapshot)
                .where(RosterSnapshot.season_number == season_number)
                .order_by(RosterSnapshot.captured_at.desc())
            ).all()
            tiles = []
            for snap in snapshots:
                n_chars = len(session.exec(
                    select(RosterSnapshotCharacter).where(
                        RosterSnapshotCharacter.snapshot_id == snap.id
                    )
                ).all())
                tiles.append({
                    "row": snap,
                    "n_chars": n_chars,
                    "is_self": bool(self_name)
                        and (snap.player_username or "").casefold() == self_name,
                })
        return templates.TemplateResponse(
            request,
            "promo_players.html",
            {
                "season_number": season_number,
                "season_start": season_start(season_number).isoformat(),
                "tiles": tiles,
            },
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
            elif fmt == FORMAT_PROMO_PLAYER_DATA:
                # Pre-bracket Arena Info popups. The detail view is the
                # players_lookup.json sidecar grouped by player + scrape
                # status (when the scrape has run). Match/group rows
                # exist in the DB for archival completeness but the
                # natural UI unit is the unique player.
                from ..data.seasons import parse_season_number
                from ..roster.promo_tournament_player_data import (
                    read_sidecar as _read_pd_sidecar,
                )
                from ..roster.promo_tournament_player_data_scrape import (
                    StatusSidecar,
                    dedupe_by_player,
                )

                pd_root = Path(tournament.storage_root)
                pd = _read_pd_sidecar(pd_root)
                season_n = parse_season_number(pd_root.parent.name)
                status = StatusSidecar.load_or_init(
                    pd_root,
                    tournament_id=tournament_id,
                    season_number=season_n,
                )

                # Scrape progress panel — derived from the status sidecar
                # file's mtime + per-player rec counts. Heuristic: file
                # touched within the last 60s = scrape "actively running"
                # (good enough; the scrape writes after every player).
                import time as _time
                from ..roster.promo_tournament_player_data_scrape import (
                    STATUS_SIDECAR_FILENAME,
                )
                status_path = pd_root / STATUS_SIDECAR_FILENAME
                progress_status_counts: dict[str, int] = {}
                for rec in status.players.values():
                    progress_status_counts[rec.status] = (
                        progress_status_counts.get(rec.status, 0) + 1
                    )
                if status_path.is_file():
                    last_mtime = status_path.stat().st_mtime
                    seconds_ago = int(max(0, _time.time() - last_mtime))
                else:
                    seconds_ago = None
                # Total unique players in the sidecar (post-aggregation,
                # one record per player). Used as the denominator in the
                # "X / Y processed" panel.
                total_unique = len(pd.players) if pd else 0
                scrape_progress = {
                    "has_status": bool(status.players),
                    "processed": len(status.players),
                    "total": total_unique,
                    "status_counts": progress_status_counts,
                    "last_update_seconds_ago": seconds_ago,
                    "currently_running": (
                        seconds_ago is not None and seconds_ago < 60
                    ),
                }
                ctx["scrape_progress"] = scrape_progress

                # URL builder for a player's BlablaLink ShiftyPad page —
                # quoted base64 uid stored verbatim in the status sidecar.
                from urllib.parse import quote as _urlquote

                def _bl_url(uid_b64: Optional[str]) -> Optional[str]:
                    if not uid_b64:
                        return None
                    q = _urlquote(uid_b64)
                    return (
                        f"https://www.blablalink.com/shiftyspad/home"
                        f"?uid={q}&openid={q}"
                    )

                unique_players = dedupe_by_player(pd.players) if pd else []
                # Stable sort: by player_name (case-insensitive).
                unique_players.sort(key=lambda r: (r.player_name or "").lower())
                player_rows = []
                for rec in unique_players:
                    scrape = status.players.get(rec.player_name)
                    # Build per-team view-model rows (Team 1 / 2 / ...)
                    # plus the deduped union for the scrape's --names
                    # plumbing. Each team also gets its own audit link
                    # via its source screenshot.
                    teams_view = [
                        {
                            "round_no": t.round_no,
                            "screenshot_id": t.screenshot_id,
                            "names": [c.name or f"?{c.slot}" for c in t.chars],
                        }
                        for t in rec.teams
                    ]
                    player_rows.append({
                        "name": rec.player_name,
                        "level": rec.player_level,
                        "team_cp": rec.team_cp,
                        "group_no": rec.group_no,
                        "match_no": rec.match_no,
                        # Source screenshot id powers the audit-view link
                        # to /promo/screenshots/{id} (image + per-region
                        # crops + extracted values, side-by-side).
                        "screenshot_id": rec.screenshot_id,
                        "side": rec.side,
                        "char_names": [c.name for c in rec.chars if c.name],
                        "teams": teams_view,
                        "scrape_status": scrape.status if scrape else None,
                        "snapshot_id": scrape.snapshot_id if scrape else None,
                        # Detail from the scrape's status sidecar — only
                        # populated for Found rows.
                        "actual_level": (
                            scrape.actual_level if scrape else None
                        ),
                        "is_roster_private": (
                            scrape.is_roster_private if scrape else None
                        ),
                        "is_outpost_private": (
                            scrape.is_outpost_private if scrape else None
                        ),
                        "bl_url": _bl_url(scrape.uid) if scrape else None,
                        "char_names_matched": (
                            scrape.char_names_matched if scrape else []
                        ),
                    })
                ctx["players"] = player_rows
                ctx["players_season"] = season_n
                ctx["players_link"] = (
                    f"/promo/players/{season_n}" if season_n is not None else None
                )
            elif fmt == FORMAT_LEAGUE:
                # League: 4 player matches + a leaderboard sidecar.
                from dataclasses import asdict

                from ..roster.league_leaderboard import read_sidecar

                matches = session.exec(
                    select(PromoMatch)
                    .where(PromoMatch.tournament_id == tournament_id)
                    .order_by(PromoMatch.match_no)
                ).all()
                player_tiles = []
                for m in matches:
                    thumb = _promo_match_thumb_url(session, m.id)
                    player_tiles.append({"row": m, "thumb": thumb})
                ctx["player_tiles"] = player_tiles

                # Master leaderboard image URL (always shown when present).
                league_root = Path(tournament.storage_root)
                master_path = league_root / "leaderboard.png"
                ctx["leaderboard_image_url"] = (
                    _promo_image_url(str(master_path)) if master_path.is_file()
                    else None
                )

                # Leaderboard entries — augment with /promo-images URLs
                # for each crop so the template can show "extracted text
                # ← source crop" inline.
                entries = read_sidecar(league_root) or []
                rich_entries = []
                for e in entries:
                    d = asdict(e)
                    for fld in ("name_crop", "cp_crop", "synchro_crop"):
                        crop_name = d.get(fld) or ""
                        d[f"{fld}_url"] = (
                            _promo_image_url(str(league_root / crop_name))
                            if crop_name else None
                        )
                    rich_entries.append(d)
                ctx["leaderboard"] = rich_entries
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
                "player": [],
                "results_overview": [],
                "results_duel": [],
            }
            for s in shots:
                key = s.kind
                if s.kind == "player_loadout":
                    # League uploads one player per match (side=NULL);
                    # promo + duel are head-to-head (side="top"/"bottom").
                    key = f"player_{s.side}" if s.side else "player"
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
                        tournament_id=match.tournament_id,
                    ),
                    "right": _promo_canonical_loadout(
                        session,
                        derived_loadouts["right"]["name"],
                        current_overview_id=overview_id,
                        current_side="right",
                        tournament_id=match.tournament_id,
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
    # Rookie Arena — daily run battles + opponent / loadout / results
    # ------------------------------------------------------------------

    @app.get("/rookie", response_class=HTMLResponse)
    def rookie_index(request: Request) -> Response:
        """Daily-run grid. Each card shows the 5 battles in a run with
        opponent name + level-source precision chip, plus a per-run
        scrape progress panel."""
        import time as _time

        from ..roster.promo_tournament_ingest import (
            FORMAT_ROOKIE_ARENA,
            tournament_format,
        )
        from ..roster.rookie_arena_scrape import (
            STATUS_FOUND,
            STATUS_PRIVATE_BOTH,
            STATUS_SIDECAR_FILENAME as _ROOKIE_STATUS_SIDECAR,
            RookieStatusSidecar,
        )
        from ..roster.rookie_arena_sidecar import read_sidecar as _read_rookie_sidecar

        with get_session(engine) as session:
            tournaments = [
                t for t in session.exec(
                    select(PromoTournament).order_by(
                        PromoTournament.captured_at.desc()
                    )
                ).all()
                if tournament_format(t.storage_root) == FORMAT_ROOKIE_ARENA
            ]
            runs = []
            any_currently_running = False
            for t in tournaments:
                matches = session.exec(
                    select(PromoMatch).where(
                        PromoMatch.tournament_id == t.id,
                        PromoMatch.round_label == "rookie",
                    ).order_by(PromoMatch.match_no)
                ).all()
                # Outcomes for the 5 battles — derived from the
                # `(left|right).char{N}.disconnect` OCR fields. Loaded
                # in one query keyed by round_index.
                sid = f"rookie-run-{t.id}"
                outcome_by_round = {
                    am.round_index: am.outcome
                    for am in session.exec(
                        select(ArenaMatch).where(
                            ArenaMatch.session_id == sid,
                        )
                    ).all()
                }
                battle_summaries = []
                for m in matches:
                    shots = session.exec(
                        select(PromoMatchScreenshot).where(
                            PromoMatchScreenshot.match_id == m.id,
                        )
                    ).all()
                    shot_by_kind = {s.kind: s for s in shots}
                    loadout = shot_by_kind.get("rookie_loadout")
                    has_opp_png = "rookie_opponent" in shot_by_kind
                    opp_name = None
                    if loadout is not None:
                        opp_field = session.exec(
                            select(PromoExtractedField).where(
                                PromoExtractedField.screenshot_id == loadout.id,
                                PromoExtractedField.region_slug == "opponent_name",
                            )
                        ).first()
                        opp_name = (
                            opp_field.text.strip()
                            if opp_field is not None and opp_field.text
                            else None
                        )
                    battle_summaries.append({
                        "match_no": m.match_no,
                        "opponent_name": opp_name,
                        "has_opponent_png": has_opp_png,
                        "outcome": outcome_by_round.get(m.match_no),
                    })

                # Scrape progress derived from the per-run status sidecar.
                run_root = Path(t.storage_root)
                sidecar = _read_rookie_sidecar(run_root)
                total_unique = (
                    len(sidecar.opponents) if sidecar is not None else 0
                )
                status_path = run_root / _ROOKIE_STATUS_SIDECAR
                progress_counts: dict[str, int] = {}
                seconds_ago: Optional[int] = None
                processed = 0
                if status_path.is_file():
                    try:
                        run_date_str = (
                            t.capture_date.isoformat() if t.capture_date else ""
                        )
                        rookie_status = RookieStatusSidecar.load_or_init(
                            run_root, run_id=t.id, run_date=run_date_str,
                        )
                        processed = len(rookie_status.players)
                        for rec in rookie_status.players.values():
                            progress_counts[rec.status] = (
                                progress_counts.get(rec.status, 0) + 1
                            )
                    except Exception:  # noqa: BLE001
                        pass
                    seconds_ago = int(
                        max(0, _time.time() - status_path.stat().st_mtime)
                    )
                currently_running = (
                    seconds_ago is not None and seconds_ago < 60
                )
                if currently_running:
                    any_currently_running = True

                n_snapshots_for_run = (
                    progress_counts.get(STATUS_FOUND, 0)
                    + progress_counts.get(STATUS_PRIVATE_BOTH, 0)
                )

                runs.append({
                    "tournament": t,
                    "battles": battle_summaries,
                    "n_with_opp_png": sum(
                        1 for b in battle_summaries if b["has_opponent_png"]
                    ),
                    "scrape": {
                        "has_status": processed > 0,
                        "processed": processed,
                        "total": total_unique,
                        "snapshots": n_snapshots_for_run,
                        "status_counts": progress_counts,
                        "last_update_seconds_ago": seconds_ago,
                        "currently_running": currently_running,
                    },
                })

        return templates.TemplateResponse(
            request,
            "rookie_index.html",
            {
                "runs": runs,
                "any_currently_running": any_currently_running,
            },
        )

    @app.get(
        "/rookie/{tournament_id}/battle/{battle_no}",
        response_class=HTMLResponse,
    )
    def rookie_battle(
        request: Request, tournament_id: int, battle_no: int,
    ) -> Response:
        """Aggregated view of one rookie battle — opponent.png +
        loadout.png + results.png with extraction summaries side-by-side,
        plus the opponent-match decision and my-level resolution chips.

        Each PNG is linked to the existing ``/promo/screenshots/<id>``
        viewer for per-region crop + OCR inspection.
        """
        from ..roster.rookie_arena_match import (
            LevelSource,
            match_opponent_card,
            opponent_level_source,
            resolve_my_level,
        )
        from ..data.models import (
            Character as _Character,
            PromoExtractedField as _Field,
        )

        with get_session(engine) as session:
            tournament = session.get(PromoTournament, tournament_id)
            if tournament is None:
                raise HTTPException(404, f"tournament {tournament_id} not found")
            match = session.exec(
                select(PromoMatch).where(
                    PromoMatch.tournament_id == tournament_id,
                    PromoMatch.match_no == battle_no,
                    PromoMatch.round_label == "rookie",
                )
            ).first()
            if match is None:
                raise HTTPException(
                    404, f"battle_{battle_no} not in tournament {tournament_id}"
                )
            shots = session.exec(
                select(PromoMatchScreenshot).where(
                    PromoMatchScreenshot.match_id == match.id,
                )
            ).all()
            shot_by_kind: dict[str, PromoMatchScreenshot] = {
                s.kind: s for s in shots
            }

            opp_shot = shot_by_kind.get("rookie_opponent")
            loadout_shot = shot_by_kind.get("rookie_loadout")
            results_shot = shot_by_kind.get("results_duel")

            opp_match = None
            if loadout_shot is not None:
                opp_match = match_opponent_card(
                    session,
                    loadout_screenshot_id=loadout_shot.id,
                    opponent_screenshot_id=opp_shot.id if opp_shot else None,
                )

            my_lv = resolve_my_level(
                session,
                battle_match_id=match.id,
                this_opponent_screenshot_id=opp_shot.id if opp_shot else None,
            )

            # Build per-screenshot extraction summaries for the page.
            # Each summary is (label, image_url, source_id, fields[])
            # where fields is a list of (label, slug, text, normalized,
            # matched_char_name, score) tuples.
            char_ids: set[int] = set()
            for shot in shots:
                fields = session.exec(
                    select(_Field).where(_Field.screenshot_id == shot.id)
                ).all()
                for f in fields:
                    if f.character_id is not None:
                        char_ids.add(f.character_id)
            char_name_by_id: dict[int, str] = {}
            if char_ids:
                rows = session.exec(
                    select(_Character.id, _Character.name).where(
                        _Character.id.in_(char_ids)
                    )
                ).all()
                char_name_by_id = {int(cid): str(name) for cid, name in rows}

            def _summary_for(shot: Optional[PromoMatchScreenshot]) -> dict:
                if shot is None:
                    return {"present": False, "image_url": None, "fields": []}
                fields = session.exec(
                    select(_Field).where(_Field.screenshot_id == shot.id)
                    .order_by(_Field.region_slug)
                ).all()
                rows = []
                for f in fields:
                    matched_char = (
                        char_name_by_id.get(f.character_id)
                        if f.character_id is not None
                        else None
                    )
                    rows.append({
                        "slug": f.region_slug,
                        "text": f.text,
                        "normalized": f.normalized,
                        "confidence": f.confidence,
                        "matched_char": matched_char,
                        "match_score": f.character_match_score,
                    })
                return {
                    "present": True,
                    "screenshot_id": shot.id,
                    "image_url": _promo_image_url(shot.file_path),
                    "fields": rows,
                }

            opponent_summary = _summary_for(opp_shot)
            loadout_summary = _summary_for(loadout_shot)
            results_summary = _summary_for(results_shot)

            # Chip classification for the opponent-level precision.
            opp_level_chip = {
                LevelSource.OPPONENT_PNG: ("matched", "green",
                                            "matched on opponent.png"),
                LevelSource.OPPONENT_PNG_FALLBACK: ("ambiguous", "yellow",
                                                     "weak fuzzy match"),
                LevelSource.ESTIMATED_FROM_MY_LEVEL: ("estimated", "yellow",
                                                       "no opponent.png — estimated from my level"),
                LevelSource.ACCOUNT_STATE: ("stale", "yellow",
                                             "AccountState fallback"),
                LevelSource.UNKNOWN: ("unknown", "red", "could not determine"),
            }
            opp_source = opponent_level_source(opp_match)
            opp_chip_label, opp_chip_color, opp_chip_title = opp_level_chip[opp_source]
            my_chip_label, my_chip_color, my_chip_title = opp_level_chip[my_lv.source]

        return templates.TemplateResponse(
            request,
            "rookie_battle.html",
            {
                "tournament": tournament,
                "match": match,
                "battle_no": battle_no,
                "opponent_summary": opponent_summary,
                "loadout_summary": loadout_summary,
                "results_summary": results_summary,
                "opp_match": opp_match,
                "opp_level_source": opp_source.value,
                "opp_chip_label": opp_chip_label,
                "opp_chip_color": opp_chip_color,
                "opp_chip_title": opp_chip_title,
                "my_level": my_lv,
                "my_chip_label": my_chip_label,
                "my_chip_color": my_chip_color,
                "my_chip_title": my_chip_title,
            },
        )

    # ------------------------------------------------------------------
    # Roster snapshots — per-(season, player) frozen rosters
    # ------------------------------------------------------------------

    @app.get("/snapshots/{snapshot_id}", response_class=HTMLResponse)
    def snapshot_detail(request: Request, snapshot_id: int) -> Response:
        """Show one player's roster snapshot for a season.

        Lists per-character data (power, synchro, LB/core, skill levels)
        joined with the static Character table for canonical names.
        Account-wide research is shown in the header.
        """
        from ..data.config import get_self_username
        from ..data.seasons import season_start

        self_name = (get_self_username() or "").casefold()
        with get_session(engine) as session:
            snap = session.get(RosterSnapshot, snapshot_id)
            if snap is None:
                raise HTTPException(404, f"snapshot {snapshot_id} not found")
            entries = session.exec(
                select(RosterSnapshotCharacter).where(
                    RosterSnapshotCharacter.snapshot_id == snap.id
                )
            ).all()
            char_ids = [e.character_id for e in entries]
            chars = {
                c.id: c for c in session.exec(
                    select(Character).where(Character.id.in_(char_ids))
                ).all()
            }
            rows = []
            for e in entries:
                ch = chars.get(e.character_id)
                if ch is None:
                    continue
                d = e.data or {}
                rows.append({
                    "name": ch.name,
                    "rarity": ch.rarity.value if ch.rarity else None,
                    "element": ch.element.value if ch.element else None,
                    "weapon_class": ch.weapon_class.value if ch.weapon_class else None,
                    "burst_type": ch.burst_type.value if ch.burst_type else None,
                    "manufacturer": ch.manufacturer.value if ch.manufacturer else None,
                    "power": d.get("power"),
                    "sync_level": d.get("sync_level"),
                    "limit_break": d.get("limit_break"),
                    "core": d.get("core"),
                    "skill1_level": d.get("skill1_level"),
                    "skill2_level": d.get("skill2_level"),
                    "burst_skill_level": d.get("burst_skill_level"),
                    "battle_cube_name": d.get("battle_cube_name"),
                    "arena_cube_name": d.get("arena_cube_name"),
                    "treasure_name": d.get("treasure_name"),
                    "treasure_phase": d.get("treasure_phase"),
                })
            # Highest power first.
            rows.sort(key=lambda r: r["power"] or 0, reverse=True)

        is_self = bool(self_name) and (snap.player_username or "").casefold() == self_name
        return templates.TemplateResponse(
            request,
            "snapshot_detail.html",
            {
                "snapshot": snap,
                "rows": rows,
                "is_self": is_self,
                "season_start_date": season_start(snap.season_number).isoformat(),
            },
        )

    # ------------------------------------------------------------------
    # Audit — review + correct extracted-field classifications
    # ------------------------------------------------------------------

    from ..roster.promo_tournament_doll_match import (
        DISPLAY_LABELS as _DOLL_DISPLAY_LABELS,
        EXEMPLAR_FILES as _DOLL_EXEMPLAR_FILES,
    )
    from ..roster.promo_tournament_lb_core_audit import (
        AUDIT_KEYS as _LB_CORE_AUDIT_KEYS,
        DISPLAY_LABELS as _LB_CORE_DISPLAY_LABELS,
        EXEMPLAR_FILES as _LB_CORE_EXEMPLAR_FILES,
    )

    # Stable display order across the audit page button row.
    # ``none`` (absence of any doll/treasure) sits before ``unknown``
    # — semantically distinct: ``none`` = slot is empty,
    # ``unknown`` = classifier couldn't decide.
    _DOLL_AUDIT_KEYS: tuple[str, ...] = (
        "r_partial",
        "r_max",
        "sr_partial",
        "sr_max",
        "treasure_partial",
        "treasure_max",
        "none",
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
            lb_core_total = len(session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.region_slug.like("%.lb_core")
                )
            ).all())
            lb_core_corrected = len(session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.region_slug.like("%.lb_core"),
                    PromoExtractedField.manually_corrected == True,  # noqa: E712
                )
            ).all())
        return templates.TemplateResponse(
            request,
            "audit_index.html",
            {
                "doll_total": doll_total,
                "doll_corrected": doll_corrected,
                "lb_core_total": lb_core_total,
                "lb_core_corrected": lb_core_corrected,
            },
        )

    _DOLL_DEFAULT_CLASS = "r_partial"

    def _audit_doll_class_counts(session) -> dict[str, int]:
        """``{class_key: count}`` over all ``%.doll`` rows."""
        from sqlalchemy import func as sa_func

        rows = session.exec(
            select(
                PromoExtractedField.normalized,
                sa_func.count(PromoExtractedField.id),
            )
            .where(PromoExtractedField.region_slug.like("%.doll"))
            .group_by(PromoExtractedField.normalized)
        ).all()
        out: dict[str, int] = {}
        for normalized, count in rows:
            key = normalized if normalized in _DOLL_AUDIT_KEYS else "unknown"
            out[key] = out.get(key, 0) + int(count)
        for k in _DOLL_AUDIT_KEYS:
            out.setdefault(k, 0)
        return out

    def _audit_doll_class_rows(session, class_key: str):
        """Return rows for ``class_key`` enriched with per-icon context.

        Sort: manually_corrected ASC (un-audited first), then confidence
        ASC NULLS FIRST (suspicious first), then id ASC. Each entry
        carries the data the grid template needs to render a cropped
        icon button.
        """
        from ..roster.promo_tournament_regions import PLAYER_LOADOUT

        # Doll bbox by slug, so we can resolve per-row crop coords.
        doll_bbox_by_slug = {
            r.slug: r.bbox for r in PLAYER_LOADOUT if r.slug.endswith(".doll")
        }

        rows = session.exec(
            select(PromoExtractedField)
            .where(
                PromoExtractedField.region_slug.like("%.doll"),
                PromoExtractedField.normalized == class_key,
            )
            .order_by(
                PromoExtractedField.manually_corrected.asc(),
                PromoExtractedField.confidence.asc().nulls_first(),
                PromoExtractedField.id.asc(),
            )
        ).all()
        if not rows:
            return []

        # Batch-fetch screenshots + per-screenshot context fields so
        # each grid row doesn't trigger N queries.
        shot_ids = list({r.screenshot_id for r in rows})
        shots = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.id.in_(shot_ids)
            )
        ).all()
        shot_by_id = {s.id: s for s in shots}

        # Pull player_name + char.portrait extractions for tooltip context.
        slugs_needed = {"player_name"}
        for r in rows:
            slot = r.region_slug.split(".")[0]  # "char3"
            slugs_needed.add(f"{slot}.portrait")
        ctx_fields = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id.in_(shot_ids),
                PromoExtractedField.region_slug.in_(list(slugs_needed)),
            )
        ).all()
        ctx_by_shot: dict[int, dict[str, PromoExtractedField]] = {}
        for f in ctx_fields:
            ctx_by_shot.setdefault(f.screenshot_id, {})[f.region_slug] = f

        char_ids: set[int] = set()
        for slug_map in ctx_by_shot.values():
            for slug, f in slug_map.items():
                if slug.endswith(".portrait") and f.character_id:
                    char_ids.add(f.character_id)
        char_names: dict[int, str] = {}
        char_rarities: dict[int, str] = {}
        if char_ids:
            crows = session.exec(
                select(Character.id, Character.name, Character.rarity).where(
                    Character.id.in_(char_ids)
                )
            ).all()
            char_names = {int(cid): str(name) for cid, name, _ in crows}
            char_rarities = {
                int(cid): (rarity.value if hasattr(rarity, "value") else str(rarity))
                for cid, _, rarity in crows
            }

        match_ids = list({s.match_id for s in shots})
        matches = session.exec(
            select(PromoMatch).where(PromoMatch.id.in_(match_ids))
        ).all()
        match_by_id = {m.id: m for m in matches}

        out = []
        for f in rows:
            shot = shot_by_id.get(f.screenshot_id)
            if shot is None:
                continue
            slot = f.region_slug.split(".")[0]
            ctx = ctx_by_shot.get(shot.id, {})
            player_field = ctx.get("player_name")
            portrait_field = ctx.get(f"{slot}.portrait")
            character_name = (
                char_names.get(portrait_field.character_id)
                if portrait_field and portrait_field.character_id
                else None
            )
            character_rarity = (
                char_rarities.get(portrait_field.character_id)
                if portrait_field and portrait_field.character_id
                else None
            )
            match = match_by_id.get(shot.match_id)
            tooltip_parts = []
            if player_field and player_field.text:
                tooltip_parts.append(player_field.text)
            if character_name:
                if character_rarity:
                    tooltip_parts.append(f"{character_name} ({character_rarity})")
                else:
                    tooltip_parts.append(character_name)
            elif portrait_field and portrait_field.text:
                tooltip_parts.append(portrait_field.text)
            if match:
                ml = match.round_label.replace("_", " ")
                tooltip_parts.append(
                    f"{ml}{(' #' + str(match.match_no)) if match.match_no else ''}"
                )
            tooltip_parts.append(f"{shot.side or '-'} round {shot.round_no or '-'}")
            tooltip_parts.append(f"slot {slot[4:]}")
            if f.confidence is not None:
                tooltip_parts.append(f"conf {f.confidence:.2f}")
            if f.manually_corrected:
                tooltip_parts.append("manually corrected")
            out.append({
                "field": f,
                "image_url": _promo_image_url(shot.file_path),
                "bbox": doll_bbox_by_slug.get(f.region_slug),
                "tooltip": " · ".join(tooltip_parts),
            })
        return out

    @app.get("/audit/dolls", response_class=HTMLResponse)
    def audit_dolls_root() -> Response:
        return RedirectResponse(
            f"/audit/dolls/{_DOLL_DEFAULT_CLASS}", status_code=302
        )

    @app.get("/audit/dolls/{class_key}", response_class=HTMLResponse)
    def audit_dolls(request: Request, class_key: str) -> Response:
        if class_key not in _DOLL_AUDIT_KEYS:
            return RedirectResponse(
                f"/audit/dolls/{_DOLL_DEFAULT_CLASS}", status_code=302
            )
        with get_session(engine) as session:
            counts = _audit_doll_class_counts(session)
            entries = _audit_doll_class_rows(session, class_key)

        # Build the dropdown options (preserves canonical order).
        class_options = [
            {
                "key": k,
                "label": _DOLL_DISPLAY_LABELS.get(k, k),
                "count": counts.get(k, 0),
                "is_current": k == class_key,
            }
            for k in _DOLL_AUDIT_KEYS
        ]

        # Reference image for the currently-selected class — None for
        # classes without an exemplar (r_max / none / unknown).
        exemplar_filename = _DOLL_EXEMPLAR_FILES.get(class_key)
        reference_url = (
            f"/static/doll-icons/{exemplar_filename}"
            if exemplar_filename else None
        )

        # Reassign-popover choices: same shape as the dropdown but
        # always with the small reference thumbnail.
        reassign_choices = []
        for k in _DOLL_AUDIT_KEYS:
            filename = _DOLL_EXEMPLAR_FILES.get(k)
            reassign_choices.append({
                "key": k,
                "label": _DOLL_DISPLAY_LABELS.get(k, k),
                "exemplar_url": (
                    f"/static/doll-icons/{filename}" if filename else None
                ),
                "is_current": k == class_key,
            })

        ref_w, ref_h = PROMO_REF_SIZE
        n_corrected = sum(
            1 for e in entries if e["field"].manually_corrected
        )
        n_auto = len(entries) - n_corrected
        return templates.TemplateResponse(
            request,
            "audit_dolls.html",
            {
                "class_key": class_key,
                "class_label": _DOLL_DISPLAY_LABELS.get(class_key, class_key),
                "reference_url": reference_url,
                "class_options": class_options,
                "entries": entries,
                "reassign_choices": reassign_choices,
                "ref_w": ref_w,
                "ref_h": ref_h,
                "n_corrected": n_corrected,
                "n_auto": n_auto,
            },
        )

    _BULK_CORRECT_LIMIT = 5000  # safety net against a runaway POST

    @app.post("/audit/dolls/bulk-correct")
    def audit_dolls_bulk_correct(
        field_ids: str = Form(...),
        normalized: str = Form(...),
        return_class: str = Form(""),
    ) -> Response:
        """Reassign many doll-classification rows in a single request.

        ``field_ids`` is a comma-separated list of integer ids — what
        the multi-select toolbar's hidden input emits. We validate +
        cap the count, then update each row's ``normalized`` / ``text``
        / ``confidence`` / ``manually_corrected`` together.
        """
        if normalized not in _DOLL_AUDIT_KEYS:
            raise HTTPException(400, f"unknown doll key: {normalized}")
        try:
            ids = [int(x) for x in field_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "field_ids must be a CSV of ints")
        if not ids:
            raise HTTPException(400, "field_ids is empty")
        if len(ids) > _BULK_CORRECT_LIMIT:
            raise HTTPException(
                400,
                f"refusing to update more than {_BULK_CORRECT_LIMIT} rows at once",
            )

        new_text = _DOLL_DISPLAY_LABELS.get(normalized, normalized)
        with get_session(engine) as session:
            rows = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.id.in_(ids)
                )
            ).all()
            for row in rows:
                if not row.region_slug.endswith(".doll"):
                    # Defensive: this endpoint is doll-specific; skip
                    # unrelated rows even if their id was passed in.
                    continue
                row.normalized = normalized
                row.text = new_text
                row.confidence = 1.0
                row.manually_corrected = True
                session.add(row)
            session.commit()

        target = (
            return_class
            if return_class in _DOLL_AUDIT_KEYS
            else _DOLL_DEFAULT_CLASS
        )
        return RedirectResponse(
            f"/audit/dolls/{target}", status_code=303
        )

    @app.post("/audit/dolls/{class_key}/reclassify-auto")
    def audit_dolls_reclassify_auto(class_key: str) -> Response:
        """Re-classify every auto row in this class against the
        current Vision corpus. ``manually_corrected`` rows are
        untouched. Rows whose Vision-predicted class differs from
        ``class_key`` will appear under the new class's URL.
        """
        if class_key not in _DOLL_AUDIT_KEYS:
            raise HTTPException(400, f"unknown class: {class_key}")
        from ..roster.promo_tournament_doll_match import (
            reclassify_class_auto_rows,
        )
        from ..roster.promo_tournament_doll_vision import DollVisionMatcher

        with get_session(engine) as session:
            matcher = DollVisionMatcher.from_session(session)
            if len(matcher) > 0:
                reclassify_class_auto_rows(session, matcher, class_key)
        return RedirectResponse(
            f"/audit/dolls/{class_key}", status_code=303
        )

    @app.post("/audit/dolls/{class_key}/confirm-all")
    def audit_dolls_confirm_all(class_key: str) -> Response:
        """Mark every row currently classified as ``class_key`` as
        manually corrected. Idempotent — already-corrected rows stay
        corrected, ``normalized`` is unchanged."""
        if class_key not in _DOLL_AUDIT_KEYS:
            raise HTTPException(400, f"unknown class: {class_key}")
        with get_session(engine) as session:
            rows = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.region_slug.like("%.doll"),
                    PromoExtractedField.normalized == class_key,
                )
            ).all()
            for row in rows:
                if not row.manually_corrected:
                    row.manually_corrected = True
                    session.add(row)
            session.commit()
        return RedirectResponse(
            f"/audit/dolls/{class_key}", status_code=303
        )

    @app.post("/audit/dolls/{field_id}/correct")
    def audit_dolls_correct(
        field_id: int,
        normalized: str = Form(...),
        return_class: str = Form(""),
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
        # Stay on the class page the user was viewing — the reassigned
        # icon disappears from this view; user keeps auditing.
        target = (
            return_class
            if return_class in _DOLL_AUDIT_KEYS
            else _DOLL_DEFAULT_CLASS
        )
        return RedirectResponse(
            f"/audit/dolls/{target}", status_code=303
        )

    # ------------------------------------------------------------------
    # Limit-Break / Max-Core audit
    # ------------------------------------------------------------------

    _LB_CORE_DEFAULT_CLASS = "lb0"

    def _audit_lb_core_class_counts(session) -> dict[str, int]:
        from sqlalchemy import func as sa_func

        rows = session.exec(
            select(
                PromoExtractedField.normalized,
                sa_func.count(PromoExtractedField.id),
            )
            .where(PromoExtractedField.region_slug.like("%.lb_core"))
            .group_by(PromoExtractedField.normalized)
        ).all()
        out: dict[str, int] = {}
        for normalized, count in rows:
            key = normalized if normalized in _LB_CORE_AUDIT_KEYS else "unknown"
            out[key] = out.get(key, 0) + int(count)
        for k in _LB_CORE_AUDIT_KEYS:
            out.setdefault(k, 0)
        return out

    def _audit_lb_core_class_rows(session, class_key: str):
        """Return rows for ``class_key`` enriched with per-row context.
        Mirrors :func:`_audit_doll_class_rows` — same sort, same tooltip
        shape, swapped slug filter and bbox map.
        """
        from ..roster.promo_tournament_regions import PLAYER_LOADOUT

        lb_core_bbox_by_slug = {
            r.slug: r.bbox for r in PLAYER_LOADOUT if r.slug.endswith(".lb_core")
        }

        rows = session.exec(
            select(PromoExtractedField)
            .where(
                PromoExtractedField.region_slug.like("%.lb_core"),
                PromoExtractedField.normalized == class_key,
            )
            .order_by(
                PromoExtractedField.manually_corrected.asc(),
                PromoExtractedField.confidence.asc().nulls_first(),
                PromoExtractedField.id.asc(),
            )
        ).all()
        if not rows:
            return []

        shot_ids = list({r.screenshot_id for r in rows})
        shots = session.exec(
            select(PromoMatchScreenshot).where(
                PromoMatchScreenshot.id.in_(shot_ids)
            )
        ).all()
        shot_by_id = {s.id: s for s in shots}

        slugs_needed = {"player_name"}
        for r in rows:
            slot = r.region_slug.split(".")[0]
            slugs_needed.add(f"{slot}.portrait")
        ctx_fields = session.exec(
            select(PromoExtractedField).where(
                PromoExtractedField.screenshot_id.in_(shot_ids),
                PromoExtractedField.region_slug.in_(list(slugs_needed)),
            )
        ).all()
        ctx_by_shot: dict[int, dict[str, PromoExtractedField]] = {}
        for f in ctx_fields:
            ctx_by_shot.setdefault(f.screenshot_id, {})[f.region_slug] = f

        char_ids: set[int] = set()
        for slug_map in ctx_by_shot.values():
            for slug, f in slug_map.items():
                if slug.endswith(".portrait") and f.character_id:
                    char_ids.add(f.character_id)
        char_names: dict[int, str] = {}
        char_rarities: dict[int, str] = {}
        if char_ids:
            crows = session.exec(
                select(Character.id, Character.name, Character.rarity).where(
                    Character.id.in_(char_ids)
                )
            ).all()
            char_names = {int(cid): str(name) for cid, name, _ in crows}
            char_rarities = {
                int(cid): (rarity.value if hasattr(rarity, "value") else str(rarity))
                for cid, _, rarity in crows
            }

        match_ids = list({s.match_id for s in shots})
        matches = session.exec(
            select(PromoMatch).where(PromoMatch.id.in_(match_ids))
        ).all()
        match_by_id = {m.id: m for m in matches}

        out = []
        for f in rows:
            shot = shot_by_id.get(f.screenshot_id)
            if shot is None:
                continue
            slot = f.region_slug.split(".")[0]
            ctx = ctx_by_shot.get(shot.id, {})
            player_field = ctx.get("player_name")
            portrait_field = ctx.get(f"{slot}.portrait")
            character_name = (
                char_names.get(portrait_field.character_id)
                if portrait_field and portrait_field.character_id
                else None
            )
            character_rarity = (
                char_rarities.get(portrait_field.character_id)
                if portrait_field and portrait_field.character_id
                else None
            )
            match = match_by_id.get(shot.match_id)
            tooltip_parts = []
            if player_field and player_field.text:
                tooltip_parts.append(player_field.text)
            if character_name:
                if character_rarity:
                    tooltip_parts.append(f"{character_name} ({character_rarity})")
                else:
                    tooltip_parts.append(character_name)
            elif portrait_field and portrait_field.text:
                tooltip_parts.append(portrait_field.text)
            if match:
                ml = match.round_label.replace("_", " ")
                tooltip_parts.append(
                    f"{ml}{(' #' + str(match.match_no)) if match.match_no else ''}"
                )
            tooltip_parts.append(f"{shot.side or '-'} round {shot.round_no or '-'}")
            tooltip_parts.append(f"slot {slot[4:]}")
            if f.confidence is not None:
                tooltip_parts.append(f"conf {f.confidence:.2f}")
            if f.manually_corrected:
                tooltip_parts.append("manually corrected")
            out.append({
                "field": f,
                "image_url": _promo_image_url(shot.file_path),
                "bbox": lb_core_bbox_by_slug.get(f.region_slug),
                "tooltip": " · ".join(tooltip_parts),
            })
        return out

    @app.get("/audit/lb-core", response_class=HTMLResponse)
    def audit_lb_core_root() -> Response:
        return RedirectResponse(
            f"/audit/lb-core/{_LB_CORE_DEFAULT_CLASS}", status_code=302
        )

    @app.get("/audit/lb-core/{class_key}", response_class=HTMLResponse)
    def audit_lb_core(request: Request, class_key: str) -> Response:
        if class_key not in _LB_CORE_AUDIT_KEYS:
            return RedirectResponse(
                f"/audit/lb-core/{_LB_CORE_DEFAULT_CLASS}", status_code=302
            )
        with get_session(engine) as session:
            counts = _audit_lb_core_class_counts(session)
            entries = _audit_lb_core_class_rows(session, class_key)

        class_options = [
            {
                "key": k,
                "label": _LB_CORE_DISPLAY_LABELS.get(k, k),
                "count": counts.get(k, 0),
                "is_current": k == class_key,
            }
            for k in _LB_CORE_AUDIT_KEYS
        ]

        exemplar_filename = _LB_CORE_EXEMPLAR_FILES.get(class_key)
        reference_url = (
            f"/static/lb-core-icons/{exemplar_filename}"
            if exemplar_filename else None
        )

        reassign_choices = []
        for k in _LB_CORE_AUDIT_KEYS:
            filename = _LB_CORE_EXEMPLAR_FILES.get(k)
            reassign_choices.append({
                "key": k,
                "label": _LB_CORE_DISPLAY_LABELS.get(k, k),
                "exemplar_url": (
                    f"/static/lb-core-icons/{filename}" if filename else None
                ),
                "is_current": k == class_key,
            })

        ref_w, ref_h = PROMO_REF_SIZE
        n_corrected = sum(
            1 for e in entries if e["field"].manually_corrected
        )
        n_auto = len(entries) - n_corrected
        return templates.TemplateResponse(
            request,
            "audit_lb_core.html",
            {
                "class_key": class_key,
                "class_label": _LB_CORE_DISPLAY_LABELS.get(class_key, class_key),
                "reference_url": reference_url,
                "class_options": class_options,
                "entries": entries,
                "reassign_choices": reassign_choices,
                "ref_w": ref_w,
                "ref_h": ref_h,
                "n_corrected": n_corrected,
                "n_auto": n_auto,
            },
        )

    @app.post("/audit/lb-core/bulk-correct")
    def audit_lb_core_bulk_correct(
        field_ids: str = Form(...),
        normalized: str = Form(...),
        return_class: str = Form(""),
    ) -> Response:
        if normalized not in _LB_CORE_AUDIT_KEYS:
            raise HTTPException(400, f"unknown lb-core key: {normalized}")
        try:
            ids = [int(x) for x in field_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "field_ids must be a CSV of ints")
        if not ids:
            raise HTTPException(400, "field_ids is empty")
        if len(ids) > _BULK_CORRECT_LIMIT:
            raise HTTPException(
                400,
                f"refusing to update more than {_BULK_CORRECT_LIMIT} rows at once",
            )

        new_text = _LB_CORE_DISPLAY_LABELS.get(normalized, normalized)
        with get_session(engine) as session:
            rows = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.id.in_(ids)
                )
            ).all()
            for row in rows:
                if not row.region_slug.endswith(".lb_core"):
                    continue
                row.normalized = normalized
                row.text = new_text
                row.confidence = 1.0
                row.manually_corrected = True
                session.add(row)
            session.commit()

        target = (
            return_class
            if return_class in _LB_CORE_AUDIT_KEYS
            else _LB_CORE_DEFAULT_CLASS
        )
        return RedirectResponse(
            f"/audit/lb-core/{target}", status_code=303
        )

    @app.post("/audit/lb-core/{class_key}/reclassify-auto")
    def audit_lb_core_reclassify_auto(class_key: str) -> Response:
        """Re-run :func:`detect_lb_core` on every auto row in this class.

        Detector is deterministic, so this is a no-op until thresholds
        are tuned. Manually-corrected rows are untouched.
        """
        if class_key not in _LB_CORE_AUDIT_KEYS:
            raise HTTPException(400, f"unknown class: {class_key}")
        from ..roster.promo_tournament_lb_core import (
            reclassify_class_auto_rows as _reclassify_lb_core,
        )
        from ..roster.promo_tournament_ocr import ocr_crop

        with get_session(engine) as session:
            _reclassify_lb_core(session, class_key, ocr_crop)
        return RedirectResponse(
            f"/audit/lb-core/{class_key}", status_code=303
        )

    @app.post("/audit/lb-core/{class_key}/confirm-all")
    def audit_lb_core_confirm_all(class_key: str) -> Response:
        if class_key not in _LB_CORE_AUDIT_KEYS:
            raise HTTPException(400, f"unknown class: {class_key}")
        with get_session(engine) as session:
            rows = session.exec(
                select(PromoExtractedField).where(
                    PromoExtractedField.region_slug.like("%.lb_core"),
                    PromoExtractedField.normalized == class_key,
                )
            ).all()
            for row in rows:
                if not row.manually_corrected:
                    row.manually_corrected = True
                    session.add(row)
            session.commit()
        return RedirectResponse(
            f"/audit/lb-core/{class_key}", status_code=303
        )

    @app.post("/audit/lb-core/{field_id}/correct")
    def audit_lb_core_correct(
        field_id: int,
        normalized: str = Form(...),
        return_class: str = Form(""),
    ) -> Response:
        if normalized not in _LB_CORE_AUDIT_KEYS:
            raise HTTPException(400, f"unknown lb-core key: {normalized}")
        with get_session(engine) as session:
            field = session.get(PromoExtractedField, field_id)
            if field is None:
                raise HTTPException(404, f"field {field_id} not found")
            field.normalized = normalized
            field.text = _LB_CORE_DISPLAY_LABELS.get(normalized, normalized)
            field.confidence = 1.0
            field.manually_corrected = True
            session.add(field)
            session.commit()
        target = (
            return_class
            if return_class in _LB_CORE_AUDIT_KEYS
            else _LB_CORE_DEFAULT_CLASS
        )
        return RedirectResponse(
            f"/audit/lb-core/{target}", status_code=303
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "matcher_loaded": app.state.matcher is not None}

    # ------------------------------------------------------------------
    # Auto-import tab — status, controls, live log via SSE
    # ------------------------------------------------------------------

    @app.get("/auto-import", response_class=HTMLResponse)
    def auto_import_page(
        request: Request, action_result: Optional[str] = None,
    ) -> Response:
        from .. import auto_import as ai

        status = ai.daemon_status()
        entries = ai.parse_audit_log_entries(ai.DEFAULT_LOG_PATH, n=10)
        return templates.TemplateResponse(
            request, "auto_importer.html",
            {
                "status": status,
                "entries": entries,
                "log_path": ai.DEFAULT_LOG_PATH,
                "stderr_path": ai.DEFAULT_LOG_PATH.with_name("auto_import.stderr.log"),
                "plist_path": ai.LAUNCHD_PLIST,
                "action_result": action_result,
            },
        )

    @app.post("/auto-import/start")
    def auto_import_start() -> Response:
        from .. import auto_import as ai
        r = ai.launchctl_start()
        msg = "ok" if r.ok else f"err:{r.stderr or r.stdout or r.returncode}"
        return RedirectResponse(
            f"/auto-import?action_result=start:{msg}", status_code=303,
        )

    @app.post("/auto-import/stop")
    def auto_import_stop() -> Response:
        from .. import auto_import as ai
        r = ai.launchctl_stop()
        msg = "ok" if r.ok else f"err:{r.stderr or r.stdout or r.returncode}"
        return RedirectResponse(
            f"/auto-import?action_result=stop:{msg}", status_code=303,
        )

    @app.post("/auto-import/restart")
    def auto_import_restart() -> Response:
        from .. import auto_import as ai
        r = ai.launchctl_restart()
        msg = "ok" if r.ok else f"err:{r.stderr or r.stdout or r.returncode}"
        return RedirectResponse(
            f"/auto-import?action_result=restart:{msg}", status_code=303,
        )

    @app.get("/auto-import/stream")
    def auto_import_stream() -> Response:
        """SSE endpoint: tails the daemon's **stderr** log and emits
        each appended line as a ``data:`` event.

        Why stderr instead of the audit log: the audit log only writes
        one stanza per *completed* run, so a user staring at the UI
        mid-ingest sees nothing for 5-10 minutes. Stderr has the
        live progress (PaddleOCR throughput, scrape per-player ticks,
        polling INFO logs, Python tracebacks). The completed audit
        stanzas show up in the "Recent runs" panel below.

        Handles file rotation (inode change) and sends a ``:keepalive``
        comment every poll cycle when idle so proxies don't drop the
        connection.
        """
        from .. import auto_import as ai
        from fastapi.responses import StreamingResponse
        import time as _time

        def _gen():
            path = ai.DEFAULT_LOG_PATH.with_name("auto_import.stderr.log")
            last_size = path.stat().st_size if path.exists() else 0
            last_inode = path.stat().st_ino if path.exists() else None
            yield ":connected\n\n"
            while True:
                if not path.exists():
                    yield ":waiting\n\n"
                    _time.sleep(1.0)
                    continue
                stat = path.stat()
                if stat.st_ino != last_inode or stat.st_size < last_size:
                    # File rotated or truncated.
                    last_size = 0
                    last_inode = stat.st_ino
                if stat.st_size > last_size:
                    with path.open("rb") as fp:
                        fp.seek(last_size)
                        chunk = fp.read().decode("utf-8", errors="replace")
                    last_size = stat.st_size
                    for line in chunk.splitlines():
                        # Prefix every SSE message with `data:` per the
                        # protocol. Empty lines become blank `data:`.
                        yield f"data: {line}\n\n"
                else:
                    yield ":keepalive\n\n"
                _time.sleep(1.0)

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",  # in case a proxy is in the way
            },
        )

    return app
