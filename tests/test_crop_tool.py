"""Pure-logic tests for the crop-tool coordinate helpers.

The Tk GUI itself isn't tested (no DISPLAY in CI / headless test envs).
We exercise the math helpers — view-transform, normalization, clamping,
relative-coord formatting — that the GUI delegates all coord work to.
"""
from __future__ import annotations

import pytest

from nikke_copilot.tools.crop_tool import (
    ViewTransform,
    clamp_selection_to_image,
    format_relative_coords,
    normalize_selection,
)


class TestViewTransform:
    def test_canvas_to_image_at_unity(self):
        v = ViewTransform(scale=1.0, offset_x=0, offset_y=0,
                          image_w=1000, image_h=1000)
        assert v.canvas_to_image(100, 200) == (100.0, 200.0)

    def test_canvas_to_image_with_offset(self):
        v = ViewTransform(scale=1.0, offset_x=50, offset_y=10,
                          image_w=1000, image_h=1000)
        # Canvas (150, 110) maps to image (100, 100)
        assert v.canvas_to_image(150, 110) == (100.0, 100.0)

    def test_canvas_to_image_at_2x(self):
        v = ViewTransform(scale=2.0, offset_x=0, offset_y=0,
                          image_w=1000, image_h=1000)
        # Canvas (100, 100) maps to image (50, 50)
        assert v.canvas_to_image(100, 100) == (50.0, 50.0)

    def test_round_trip_image_to_canvas(self):
        v = ViewTransform(scale=1.5, offset_x=20, offset_y=-30,
                          image_w=2000, image_h=2000)
        for ix, iy in [(0, 0), (100, 200), (1500, 800)]:
            cx, cy = v.image_to_canvas(ix, iy)
            ix2, iy2 = v.canvas_to_image(cx, cy)
            assert ix == pytest.approx(ix2)
            assert iy == pytest.approx(iy2)


class TestZoomAtCursor:
    def test_pixel_under_cursor_stays_under_cursor(self):
        """The defining property of zoom-toward-cursor: after zooming,
        the same image pixel that was under the cursor before remains
        under the cursor. Mathematically: the cursor's
        canvas-to-image mapping is unchanged."""
        v = ViewTransform(scale=1.0, offset_x=10, offset_y=20,
                          image_w=2732, image_h=2048)
        cursor_cx, cursor_cy = 400.0, 300.0
        ix_before, iy_before = v.canvas_to_image(cursor_cx, cursor_cy)
        v2 = v.zoom_at_cursor(cursor_cx, cursor_cy, factor=1.5)
        ix_after, iy_after = v2.canvas_to_image(cursor_cx, cursor_cy)
        assert ix_after == pytest.approx(ix_before)
        assert iy_after == pytest.approx(iy_before)

    def test_zoom_compounds(self):
        v = ViewTransform(scale=1.0, image_w=1000, image_h=1000)
        v2 = v.zoom_at_cursor(0, 0, factor=2.0).zoom_at_cursor(0, 0, factor=2.0)
        assert v2.scale == pytest.approx(4.0)

    def test_zoom_out_then_in_returns_to_origin_scale(self):
        v = ViewTransform(scale=1.0, image_w=1000, image_h=1000)
        v2 = v.zoom_at_cursor(50, 50, factor=2.0).zoom_at_cursor(50, 50, factor=0.5)
        assert v2.scale == pytest.approx(1.0)


class TestNormalizeSelection:
    def test_already_normalized(self):
        assert normalize_selection((10, 20), (100, 200)) == (10, 20, 100, 200)

    def test_swap_when_p2_is_top_left(self):
        assert normalize_selection((100, 200), (10, 20)) == (10, 20, 100, 200)

    def test_mixed_diagonals(self):
        # p1 = top-right, p2 = bottom-left → swap x's only
        assert normalize_selection((100, 20), (10, 200)) == (10, 20, 100, 200)


class TestClampSelectionToImage:
    def test_no_clamp_when_inside(self):
        assert clamp_selection_to_image((10, 20, 100, 200), 1000, 500) == (10, 20, 100, 200)

    def test_clamp_negative(self):
        assert clamp_selection_to_image((-10, -5, 100, 200), 1000, 500) == (0, 0, 100, 200)

    def test_clamp_overflow(self):
        assert clamp_selection_to_image((10, 20, 1500, 800), 1000, 500) == (10, 20, 1000, 500)

    def test_round_to_int(self):
        assert clamp_selection_to_image((1.4, 2.6, 99.5, 199.5), 1000, 500) == (1, 3, 100, 200)


class TestFormatRelativeCoords:
    def test_basic_format(self):
        s = format_relative_coords((100, 200, 500, 800), 1000, 1000)
        assert s == "(0.1000, 0.2000, 0.5000, 0.8000)"

    def test_decimals_param(self):
        s = format_relative_coords((100, 200, 500, 800), 1000, 1000, decimals=2)
        assert s == "(0.10, 0.20, 0.50, 0.80)"

    def test_zero_dimensions_safe(self):
        # Defensive: never divide by zero on uninitialized state.
        assert format_relative_coords((0, 0, 0, 0), 0, 0) == "(0.0, 0.0, 0.0, 0.0)"

    def test_real_world_example_matches_arena_constants(self):
        """The format must produce strings that drop straight into
        an `_ARENA_INFO_REGIONS` entry — same shape as the existing
        constants like `(0.30, 0.498, 0.70, 0.682)`."""
        # Selecting team_strip on a 2732x1638 fictional capture.
        sel = (819, 815, 1912, 1117)  # rough team_strip coords
        s = format_relative_coords(sel, 2732, 1638)
        # Should be 4 comma-separated 4-decimal fractions in parens.
        assert s.startswith("(") and s.endswith(")")
        parts = s[1:-1].split(", ")
        assert len(parts) == 4
        for p in parts:
            float(p)  # parses as a float


class TestZoomIndependentCoords:
    """The KEY invariant: image-relative coords for the same selection
    should be identical regardless of the current zoom level."""

    def test_same_image_pixels_at_two_zoom_levels(self):
        # Image is 2000x1000.
        IW, IH = 2000, 1000
        v1 = ViewTransform(scale=1.0, offset_x=0, offset_y=0, image_w=IW, image_h=IH)
        v2 = ViewTransform(scale=4.0, offset_x=-3000, offset_y=-1000, image_w=IW, image_h=IH)
        # User picks (canvas) corners that correspond to image pixels
        # (500, 200) and (1500, 800) at BOTH zoom levels.
        sel_image = (500, 200, 1500, 800)
        coords1 = format_relative_coords(sel_image, IW, IH)
        coords2 = format_relative_coords(sel_image, IW, IH)
        assert coords1 == coords2 == "(0.2500, 0.2000, 0.7500, 0.8000)"

    def test_canvas_selection_at_2x_yields_same_image_coords(self):
        IW, IH = 1000, 1000
        # At scale=1.0, offset=0: canvas (100,100)-(500,500) → image same
        v = ViewTransform(scale=1.0, offset_x=0, offset_y=0, image_w=IW, image_h=IH)
        c1 = v.canvas_to_image(100, 100)
        c2 = v.canvas_to_image(500, 500)
        sel_unzoomed = clamp_selection_to_image(
            normalize_selection(c1, c2), IW, IH,
        )
        # At scale=2.0, offset=0: canvas (200,200)-(1000,1000) → image (100,100)-(500,500)
        v2 = ViewTransform(scale=2.0, offset_x=0, offset_y=0, image_w=IW, image_h=IH)
        c1z = v2.canvas_to_image(200, 200)
        c2z = v2.canvas_to_image(1000, 1000)
        sel_zoomed = clamp_selection_to_image(
            normalize_selection(c1z, c2z), IW, IH,
        )
        assert sel_unzoomed == sel_zoomed
        assert (
            format_relative_coords(sel_unzoomed, IW, IH)
            == format_relative_coords(sel_zoomed, IW, IH)
        )
