"""Visual crop-coordinate utility (`nikkecopilot crop-tool`).

GUI to derive precise crop coordinates by visual selection. Built for
retuning region constants like ``_ARENA_INFO_REGIONS`` and
``_PORTRAIT_BOX_CHAMPION`` without the "save crop, eyeball, adjust,
repeat" loop in /tmp.

Behavior:
  * Image loads via drag-and-drop, "Open..." button, or CLI arg.
  * Click 1 marks the first corner; mouse motion draws a live
    rectangle preview from corner 1 to the cursor; click 2 locks
    the second corner.
  * Press ``s`` to save the cropped PNG (defaults to ``<repo>/debug/``)
    AND copy image-relative coordinates ``(x1, y1, x2, y2)`` (4-decimal
    fractions) to the system clipboard. A toast confirms.
  * Press ``f`` to reset (next click starts a fresh selection).
  * Mouse wheel zooms in/out 1.2x per tick, centered on the cursor —
    the pixel under the cursor stays under the cursor.
  * Coords on the clipboard are always image-relative regardless of
    zoom level, so they can be pasted straight into the codebase.
"""

from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-logic helpers (no Tk dependency — unit-testable in any env)
# ---------------------------------------------------------------------------


@dataclass
class ViewTransform:
    """Maps between image pixels and canvas pixels at a given zoom + pan.

    ``scale``: image-pixels-to-canvas-pixels factor (1.0 = native).
    ``offset_x`` / ``offset_y``: canvas pixel position of the image's
    (0, 0) origin. Negative values mean we're scrolled into the image.
    """

    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    image_w: int = 0
    image_h: int = 0

    def canvas_to_image(self, cx: float, cy: float) -> tuple[float, float]:
        """Map a canvas pixel to its image-pixel coordinates."""
        ix = (cx - self.offset_x) / self.scale
        iy = (cy - self.offset_y) / self.scale
        return ix, iy

    def image_to_canvas(self, ix: float, iy: float) -> tuple[float, float]:
        """Map an image pixel to its canvas-pixel coordinates."""
        cx = ix * self.scale + self.offset_x
        cy = iy * self.scale + self.offset_y
        return cx, cy

    def zoom_at_cursor(self, cx: float, cy: float, factor: float) -> "ViewTransform":
        """Return a new transform zoomed by ``factor`` keeping (cx, cy) fixed.

        After the zoom, the same image pixel that was under the cursor
        before remains under the cursor — the standard "zoom toward
        cursor" UX. Math: solve for new offset such that
        ``image_to_canvas(canvas_to_image(cx, cy))`` equals (cx, cy)
        at the new scale.
        """
        ix, iy = self.canvas_to_image(cx, cy)
        new_scale = self.scale * factor
        new_offset_x = cx - ix * new_scale
        new_offset_y = cy - iy * new_scale
        return ViewTransform(
            scale=new_scale,
            offset_x=new_offset_x,
            offset_y=new_offset_y,
            image_w=self.image_w,
            image_h=self.image_h,
        )


def normalize_selection(
    p1: tuple[float, float], p2: tuple[float, float]
) -> tuple[float, float, float, float]:
    """Return (x1, y1, x2, y2) where (x1, y1) is top-left, (x2, y2) bottom-right."""
    x1, x2 = sorted((p1[0], p2[0]))
    y1, y2 = sorted((p1[1], p2[1]))
    return x1, y1, x2, y2


def clamp_selection_to_image(
    sel: tuple[float, float, float, float], image_w: int, image_h: int
) -> tuple[int, int, int, int]:
    """Clamp a selection to the image bounds + round to integer pixels."""
    x1, y1, x2, y2 = sel
    x1 = max(0, min(image_w, int(round(x1))))
    y1 = max(0, min(image_h, int(round(y1))))
    x2 = max(0, min(image_w, int(round(x2))))
    y2 = max(0, min(image_h, int(round(y2))))
    return x1, y1, x2, y2


def format_relative_coords(
    sel: tuple[float, float, float, float], image_w: int, image_h: int,
    *, decimals: int = 4,
) -> str:
    """Format a pixel selection as the image-relative tuple string.

    Output looks like ``(0.3130, 0.4980, 0.6870, 0.6820)`` so it can be
    pasted directly into a region-constant definition.
    """
    if image_w <= 0 or image_h <= 0:
        return "(0.0, 0.0, 0.0, 0.0)"
    x1, y1, x2, y2 = sel
    rel = (
        x1 / image_w,
        y1 / image_h,
        x2 / image_w,
        y2 / image_h,
    )
    fmt = f"%.{decimals}f"
    return "(" + ", ".join(fmt % v for v in rel) + ")"


# ---------------------------------------------------------------------------
# Tk GUI (only imported when run() is called — keeps the module
# importable in headless test envs).
# ---------------------------------------------------------------------------


_REPO_DEBUG_DIR_HINT = Path(__file__).resolve().parents[3] / "debug"


def run(image_path: Optional[Path] = None) -> None:
    """Launch the crop-coord GUI.

    ``image_path`` (optional) loads the given image at startup.
    """
    # Defer Tk imports so this module can be imported in headless test
    # environments (CI, smoke test runs without DISPLAY).
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from PIL import Image, ImageTk

    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        _HAS_DND = True
    except Exception as exc:  # noqa: BLE001
        log.warning("tkinterdnd2 unavailable (%s); drag-and-drop disabled", exc)
        TkinterDnD = None  # type: ignore[assignment]
        DND_FILES = None  # type: ignore[assignment]
        _HAS_DND = False

    # ---- State ---------------------------------------------------------
    state: dict = {
        "image": None,           # PIL.Image — original, unscaled
        "image_path": None,      # Path or None
        "photo": None,           # ImageTk.PhotoImage — current scaled view
        "view": ViewTransform(),
        "first_corner": None,    # (image_x, image_y) or None
        "live_rect_id": None,    # canvas item id for the rubber-band rect
        "second_corner": None,   # (image_x, image_y) or None
        "image_id": None,        # canvas item id for the displayed image
    }

    # ---- Window --------------------------------------------------------
    if _HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    root.title("NikkeCopilot — crop coords")
    root.geometry("1200x900")

    # Top toolbar
    bar = tk.Frame(root, bg="#1a1a1a")
    bar.pack(side="top", fill="x")

    def open_dialog() -> None:
        path = filedialog.askopenfilename(
            title="Open image",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.webp *.PNG *.JPG *.JPEG *.WEBP"),
                ("All files", "*.*"),
            ],
        )
        if path:
            load_image(Path(path))

    open_btn = tk.Button(bar, text="Open…", command=open_dialog,
                        bg="#2a4a8a", fg="white", relief="flat",
                        padx=10, pady=4)
    open_btn.pack(side="left", padx=4, pady=4)

    status = tk.Label(
        bar,
        text=(
            "Drop image · click 2 corners · scroll = zoom · "
            "right-click drag (or space+drag) = pan · "
            "s = save+copy · f = reset"
        ),
        bg="#1a1a1a", fg="#aaaaaa", anchor="w",
    )
    status.pack(side="left", fill="x", expand=True, padx=8)

    coord_label = tk.Label(bar, text="", bg="#1a1a1a", fg="#6fdf80")
    coord_label.pack(side="right", padx=8)

    # Canvas with scrollbars
    canvas_frame = tk.Frame(root, bg="#000")
    canvas_frame.pack(fill="both", expand=True)
    canvas = tk.Canvas(canvas_frame, bg="#0a0a0a", highlightthickness=0,
                       cursor="crosshair")
    canvas.pack(fill="both", expand=True)

    # Toast (transient overlay near the bottom)
    toast = tk.Label(root, text="", bg="#103a18", fg="#6fdf80",
                     padx=12, pady=4, relief="flat")
    toast.place_forget()
    toast_after_id: dict = {"id": None}

    def show_toast(text: str, duration_ms: int = 1800) -> None:
        toast.configure(text=text)
        toast.place(relx=0.5, rely=0.92, anchor="center")
        if toast_after_id["id"] is not None:
            toast.after_cancel(toast_after_id["id"])
        toast_after_id["id"] = toast.after(duration_ms, lambda: toast.place_forget())

    # ---- Image loading + redraw ---------------------------------------

    def load_image(path: Path) -> None:
        try:
            img = Image.open(path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open failed", f"Could not open {path}:\n{exc}")
            return
        state["image"] = img
        state["image_path"] = path
        state["first_corner"] = None
        state["second_corner"] = None
        state["live_rect_id"] = None

        # Reset view: scale to fit window
        canvas.update_idletasks()
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        scale_x = cw / img.width
        scale_y = ch / img.height
        scale = min(scale_x, scale_y, 1.0)
        # Center the image in the canvas
        new_w = img.width * scale
        new_h = img.height * scale
        offset_x = (cw - new_w) / 2
        offset_y = (ch - new_h) / 2
        state["view"] = ViewTransform(
            scale=scale, offset_x=offset_x, offset_y=offset_y,
            image_w=img.width, image_h=img.height,
        )
        root.title(f"NikkeCopilot — crop coords — {path.name} "
                   f"({img.width}x{img.height})")
        redraw()

    def redraw() -> None:
        """Re-render the canvas image at the current view transform.

        Viewport-clipped: only scales the portion of the source image
        visible in the canvas (plus a small margin), so memory stays
        bounded by canvas size regardless of zoom level. Without this,
        zooming in past ~6x on a 2732x2048 source blows up to a
        ~1.5GB scaled bitmap and triggers MemoryError in Tk.
        """
        img = state["image"]
        if img is None:
            return
        v = state["view"]
        canvas.update_idletasks()
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())

        # Map the canvas viewport rectangle back to image-pixel coords.
        ix1, iy1 = v.canvas_to_image(0, 0)
        ix2, iy2 = v.canvas_to_image(cw, ch)
        # Clamp to source-image bounds, with a 1px outset to avoid
        # off-by-one gaps at the edges.
        src_x1 = max(0, int(ix1) - 1)
        src_y1 = max(0, int(iy1) - 1)
        src_x2 = min(img.width, int(ix2) + 1)
        src_y2 = min(img.height, int(iy2) + 1)
        if src_x2 <= src_x1 or src_y2 <= src_y1:
            # Image is entirely off-screen — nothing to draw.
            canvas.delete("all")
            return
        src_crop = img.crop((src_x1, src_y1, src_x2, src_y2))
        # Compute the canvas-pixel size of just this cropped patch.
        out_w = max(1, int(round((src_x2 - src_x1) * v.scale)))
        out_h = max(1, int(round((src_y2 - src_y1) * v.scale)))
        # PIL.Image.LANCZOS for downscale, NEAREST for upscale (>1.5x)
        # so individual pixels stay crisp when zoomed in.
        resample = Image.NEAREST if v.scale > 1.5 else Image.LANCZOS
        scaled = src_crop.resize((out_w, out_h), resample)
        state["photo"] = ImageTk.PhotoImage(scaled)
        canvas.delete("all")
        # Place the scaled patch at the canvas position corresponding
        # to the source crop's (src_x1, src_y1) image corner.
        place_x, place_y = v.image_to_canvas(src_x1, src_y1)
        state["image_id"] = canvas.create_image(
            place_x, place_y, image=state["photo"], anchor="nw",
        )
        # Re-draw any locked second-corner rectangle.
        if state["first_corner"] is not None and state["second_corner"] is not None:
            _draw_locked_rect()
        elif state["first_corner"] is not None:
            # Re-draw a marker at the first corner.
            cx, cy = v.image_to_canvas(*state["first_corner"])
            canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                               outline="#6fdf80", width=2, tags="marker")

    def _draw_locked_rect() -> None:
        v = state["view"]
        c1 = v.image_to_canvas(*state["first_corner"])
        c2 = v.image_to_canvas(*state["second_corner"])
        canvas.create_rectangle(
            c1[0], c1[1], c2[0], c2[1],
            outline="#f4b740", width=2, tags="locked",
        )

    # ---- Drag-and-drop -------------------------------------------------

    def on_drop(event) -> None:
        # tkinterdnd2 returns space-separated paths possibly braced
        raw = event.data
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        path = Path(raw.strip())
        if path.is_file():
            load_image(path)
        else:
            messagebox.showerror("Drop failed", f"Not a file: {raw}")

    if _HAS_DND:
        canvas.drop_target_register(DND_FILES)
        canvas.dnd_bind("<<Drop>>", on_drop)

    # ---- Click + motion handlers --------------------------------------

    def on_left_click(event) -> None:
        if state["image"] is None:
            return
        v = state["view"]
        ix, iy = v.canvas_to_image(event.x, event.y)
        # Clamp to image bounds.
        ix = max(0.0, min(v.image_w, ix))
        iy = max(0.0, min(v.image_h, iy))
        if state["first_corner"] is None:
            # Start new selection.
            state["first_corner"] = (ix, iy)
            state["second_corner"] = None
            if state["live_rect_id"]:
                canvas.delete(state["live_rect_id"])
                state["live_rect_id"] = None
            canvas.delete("locked")
            # Draw the corner marker.
            canvas.create_oval(event.x - 4, event.y - 4,
                               event.x + 4, event.y + 4,
                               outline="#6fdf80", width=2, tags="marker")
            status.configure(text="Corner 1 set — move + click to set corner 2")
        elif state["second_corner"] is None:
            state["second_corner"] = (ix, iy)
            if state["live_rect_id"]:
                canvas.delete(state["live_rect_id"])
                state["live_rect_id"] = None
            canvas.delete("marker")
            _draw_locked_rect()
            sel = clamp_selection_to_image(
                normalize_selection(state["first_corner"], state["second_corner"]),
                v.image_w, v.image_h,
            )
            coord_label.configure(
                text=format_relative_coords(sel, v.image_w, v.image_h)
            )
            status.configure(text="Selection complete — press s to save+copy, f to reset")
        else:
            # Already complete — clicking again starts a new selection.
            reset_selection()
            on_left_click(event)

    def on_motion(event) -> None:
        if state["image"] is None or state["first_corner"] is None:
            return
        if state["second_corner"] is not None:
            return  # selection locked
        v = state["view"]
        c1 = v.image_to_canvas(*state["first_corner"])
        if state["live_rect_id"]:
            canvas.coords(state["live_rect_id"], c1[0], c1[1], event.x, event.y)
        else:
            state["live_rect_id"] = canvas.create_rectangle(
                c1[0], c1[1], event.x, event.y,
                outline="#6fdf80", width=2, dash=(4, 2),
            )
        # Live coord readout.
        ix, iy = v.canvas_to_image(event.x, event.y)
        sel = clamp_selection_to_image(
            normalize_selection(state["first_corner"], (ix, iy)),
            v.image_w, v.image_h,
        )
        coord_label.configure(
            text=format_relative_coords(sel, v.image_w, v.image_h)
        )

    def reset_selection() -> None:
        state["first_corner"] = None
        state["second_corner"] = None
        if state["live_rect_id"]:
            canvas.delete(state["live_rect_id"])
            state["live_rect_id"] = None
        canvas.delete("marker")
        canvas.delete("locked")
        coord_label.configure(text="")
        status.configure(text="Reset — click to set corner 1")

    def on_key_f(_event) -> None:
        reset_selection()

    def on_key_s(_event) -> None:
        if state["image"] is None:
            show_toast("Open an image first")
            return
        if state["first_corner"] is None or state["second_corner"] is None:
            show_toast("Select two corners first")
            return
        v = state["view"]
        sel = clamp_selection_to_image(
            normalize_selection(state["first_corner"], state["second_corner"]),
            v.image_w, v.image_h,
        )
        x1, y1, x2, y2 = sel
        if x2 - x1 < 2 or y2 - y1 < 2:
            show_toast("Selection too small")
            return
        rel = format_relative_coords(sel, v.image_w, v.image_h)
        # Copy to clipboard immediately (so it sticks even if the user
        # cancels the save dialog).
        try:
            root.clipboard_clear()
            root.clipboard_append(rel)
            root.update()  # ensure clipboard persists after focus loss
        except Exception as exc:  # noqa: BLE001
            log.warning("clipboard write failed: %s", exc)
        # Save the cropped PNG.
        default_dir = _REPO_DEBUG_DIR_HINT if _REPO_DEBUG_DIR_HINT.exists() else None
        src_name = (
            state["image_path"].stem if state["image_path"] is not None
            else "crop"
        )
        out_path = filedialog.asksaveasfilename(
            title="Save cropped image",
            initialdir=str(default_dir) if default_dir else None,
            initialfile=f"{src_name}_{x1}-{y1}_{x2}-{y2}.png",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")],
        )
        if out_path:
            try:
                state["image"].crop((x1, y1, x2, y2)).save(out_path)
                show_toast(f"✓ Saved {Path(out_path).name} · coords on clipboard")
            except Exception as exc:  # noqa: BLE001
                show_toast(f"✗ Save failed: {exc}")
        else:
            show_toast(f"✓ Coords copied: {rel}")

    # Zoom guardrails — prevent runaway scale that triggers Tk MemoryError.
    _MIN_SCALE = 0.05
    _MAX_SCALE = 12.0

    def _zoom(event, factor: float) -> None:
        if state["image"] is None:
            return
        v = state["view"]
        proposed = v.scale * factor
        if proposed > _MAX_SCALE or proposed < _MIN_SCALE:
            return  # silently ignore — caller already at the limit
        state["view"] = v.zoom_at_cursor(event.x, event.y, factor)
        redraw()

    def on_wheel(event) -> None:
        # macOS: event.delta is small (often 1 or -1)
        # Windows: event.delta is multiples of 120
        # Linux: separate Button-4 / Button-5 events handled below
        if event.delta == 0:
            return
        factor = 1.2 if event.delta > 0 else (1.0 / 1.2)
        _zoom(event, factor)

    def on_button4(event) -> None:
        _zoom(event, 1.2)

    def on_button5(event) -> None:
        _zoom(event, 1.0 / 1.2)

    # ---- Pan (right-click drag OR space+left-drag) --------------------
    pan_state: dict = {"start_x": None, "start_y": None, "space_held": False}

    def on_pan_start(event) -> None:
        if state["image"] is None:
            return
        pan_state["start_x"] = event.x
        pan_state["start_y"] = event.y
        canvas.configure(cursor="fleur")

    def on_pan_drag(event) -> None:
        if pan_state["start_x"] is None or state["image"] is None:
            return
        dx = event.x - pan_state["start_x"]
        dy = event.y - pan_state["start_y"]
        pan_state["start_x"] = event.x
        pan_state["start_y"] = event.y
        v = state["view"]
        state["view"] = ViewTransform(
            scale=v.scale,
            offset_x=v.offset_x + dx,
            offset_y=v.offset_y + dy,
            image_w=v.image_w,
            image_h=v.image_h,
        )
        redraw()

    def on_pan_end(_event) -> None:
        pan_state["start_x"] = None
        pan_state["start_y"] = None
        canvas.configure(cursor="crosshair" if not pan_state["space_held"] else "fleur")

    def on_space_down(_event) -> None:
        pan_state["space_held"] = True
        canvas.configure(cursor="fleur")

    def on_space_up(_event) -> None:
        pan_state["space_held"] = False
        if pan_state["start_x"] is None:
            canvas.configure(cursor="crosshair")

    # Re-route left-click to pan when space is held; otherwise normal selection.
    def on_left_click_or_pan(event) -> None:
        if pan_state["space_held"]:
            on_pan_start(event)
        else:
            on_left_click(event)

    def on_left_drag(event) -> None:
        if pan_state["space_held"] and pan_state["start_x"] is not None:
            on_pan_drag(event)
        else:
            on_motion(event)

    def on_left_release(event) -> None:
        if pan_state["space_held"] and pan_state["start_x"] is not None:
            on_pan_end(event)

    canvas.bind("<Button-1>", on_left_click_or_pan)
    canvas.bind("<B1-Motion>", on_left_drag)
    canvas.bind("<ButtonRelease-1>", on_left_release)
    canvas.bind("<Motion>", on_motion)
    # Right-click drag for pan (works on every platform — macOS sends
    # Button-2 for two-finger click and Button-3 for control-click;
    # Linux/Windows send Button-3 for right-click).
    canvas.bind("<Button-2>", on_pan_start)
    canvas.bind("<B2-Motion>", on_pan_drag)
    canvas.bind("<ButtonRelease-2>", on_pan_end)
    canvas.bind("<Button-3>", on_pan_start)
    canvas.bind("<B3-Motion>", on_pan_drag)
    canvas.bind("<ButtonRelease-3>", on_pan_end)
    canvas.bind("<MouseWheel>", on_wheel)
    canvas.bind("<Button-4>", on_button4)  # Linux scroll-up
    canvas.bind("<Button-5>", on_button5)  # Linux scroll-down
    root.bind("<KeyPress-s>", on_key_s)
    root.bind("<KeyPress-S>", on_key_s)
    root.bind("<KeyPress-f>", on_key_f)
    root.bind("<KeyPress-F>", on_key_f)
    root.bind("<KeyPress-space>", on_space_down)
    root.bind("<KeyRelease-space>", on_space_up)
    # Re-fit on window resize.
    def on_resize(event) -> None:
        if event.widget is canvas and state["image"] is not None:
            # Don't reset zoom; just redraw at the current view transform.
            redraw()
    canvas.bind("<Configure>", on_resize)

    # Auto-load if path provided.
    if image_path is not None:
        # Defer until after the window has been sized once.
        root.after(50, lambda: load_image(image_path))

    root.mainloop()


def main(argv: Optional[list[str]] = None) -> int:
    """Standalone entry-point used when invoked outside the CLI."""
    args = sys.argv[1:] if argv is None else argv
    image_path = Path(args[0]) if args else None
    if image_path is not None and not image_path.is_file():
        print(f"Image not found: {image_path}", file=sys.stderr)
        return 1
    run(image_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
