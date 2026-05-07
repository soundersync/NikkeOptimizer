"""Coord picker (`nikkeoptimizer pick-coords`) — drop a screenshot,
click two corners, save absolute-pixel crop + masked variants.

Built for ad-hoc UI element localization in arbitrary screenshots
(arena info modals, tournament brackets, etc). Sister tool to
``crop_tool.py``, which writes *fractional* region constants for the
codebase's runtime crop boxes; this one writes *absolute pixel* outputs
for offline analysis pipelines.

Workflow:
    1. Drop a PNG / JPG / WebP onto the window (or pass a path on the
       CLI).
    2. Click two corners on the image. A red bounding box appears.
    3. Press ``F`` to save:
         <stem>__x1_y1_x2_y2__crop.png      (just the selected region)
         <stem>__x1_y1_x2_y2__masked.png    (full-size, rest black)
       Both files land in the same directory as the source image. The
       coordinates ``(x1, y1, x2, y2)`` also land on the clipboard.
    4. Press ``S`` to clear and start a new selection.

Navigation:
    * Pinch (trackpad) or Cmd+scroll (mouse) → zoom toward cursor.
    * Left-drag, right-drag, or middle-drag → pan.
    * A short left-click (no movement) sets a corner.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-logic helpers (Qt-free — unit-testable in any env)
# ---------------------------------------------------------------------------


@dataclass
class Selection:
    """Two corners of a selection in image-pixel coords."""

    p1: tuple[float, float] | None = None
    p2: tuple[float, float] | None = None

    def is_complete(self) -> bool:
        return self.p1 is not None and self.p2 is not None

    def normalized(self) -> tuple[int, int, int, int] | None:
        """(x1, y1, x2, y2) with x1<=x2, y1<=y2, rounded to integer pixels."""
        if not self.is_complete():
            return None
        x1 = min(self.p1[0], self.p2[0])
        y1 = min(self.p1[1], self.p2[1])
        x2 = max(self.p1[0], self.p2[0])
        y2 = max(self.p1[1], self.p2[1])
        return int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))


def clamp_to_image(
    sel: tuple[int, int, int, int], image_w: int, image_h: int
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = sel
    return (
        max(0, min(image_w, x1)),
        max(0, min(image_h, y1)),
        max(0, min(image_w, x2)),
        max(0, min(image_h, y2)),
    )


def output_paths(src: Path, x1: int, y1: int, x2: int, y2: int) -> tuple[Path, Path]:
    """Return (crop_path, masked_path) given a source path + bbox."""
    coord = f"{x1}_{y1}_{x2}_{y2}"
    crop = src.parent / f"{src.stem}__{coord}__crop.png"
    masked = src.parent / f"{src.stem}__{coord}__masked.png"
    return crop, masked


def coord_string(x1: int, y1: int, x2: int, y2: int) -> str:
    """Clipboard format: ``(x1, y1, x2, y2)`` as a paste-ready Python tuple."""
    return f"({x1}, {y1}, {x2}, {y2})"


# ---------------------------------------------------------------------------
# Qt application — only loaded when run() is called.
# ---------------------------------------------------------------------------


_APP_QSS = """
QMainWindow, QWidget#central {
    background: #0e0f12;
}
QFrame#header {
    background: #14161b;
    border-bottom: 1px solid #1f2228;
}
QLabel#filename {
    color: #e5e7eb;
    font-size: 13px;
    font-weight: 600;
}
QLabel#dim {
    color: #6b7280;
    font-size: 12px;
    font-family: "SF Mono", "Menlo", monospace;
}
QLabel#dropzone {
    color: #9ca3af;
    font-size: 16px;
    border: 2px dashed #3a3f4a;
    border-radius: 18px;
    padding: 70px 100px;
    background: #15171c;
    qproperty-alignment: AlignCenter;
}
QLabel#dropzone[active="true"] {
    color: #f87171;
    border-color: #f87171;
    background: #1a1517;
}
QStatusBar {
    background: #14161b;
    color: #9ca3af;
    border-top: 1px solid #1f2228;
    padding: 2px 4px;
}
QStatusBar QLabel {
    padding: 0 10px;
    font-size: 12px;
}
QStatusBar::item { border: none; }
QLabel#hint { color: #9ca3af; }
QLabel#hint[toast="true"] { color: #6fdf80; font-weight: 600; }
QLabel#cursor_coords {
    color: #d1d5db;
    font-family: "SF Mono", "Menlo", monospace;
}
QLabel#bbox_coords {
    color: #f87171;
    font-family: "SF Mono", "Menlo", monospace;
    font-weight: 600;
}
QGraphicsView {
    background: #0a0b0e;
    border: none;
}
"""


def run(image_path: Optional[Path] = None) -> int:
    """Launch the coord-picker GUI. Returns the Qt exit code."""
    # All Qt imports deferred so this module imports cleanly in headless envs.
    from PySide6.QtCore import (
        QEvent,
        QPoint,
        QPointF,
        QRect,
        QRectF,
        QSize,
        Qt,
        QTimer,
        Signal,
    )
    from PySide6.QtGui import (
        QBrush,
        QColor,
        QGuiApplication,
        QImage,
        QPainter,
        QPen,
        QPixmap,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QFrame,
        QGraphicsEllipseItem,
        QGraphicsItem,
        QGraphicsPixmapItem,
        QGraphicsRectItem,
        QGraphicsScene,
        QGraphicsView,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )

    RED = QColor("#f87171")
    RED_FILL = QColor(248, 113, 113, 200)

    # ----------------------------------------------------------------------
    # ImageView — pan / zoom / click detection on a QGraphicsView.
    # ----------------------------------------------------------------------

    class ImageView(QGraphicsView):
        pointClicked = Signal(QPointF)   # scene coords on a real click (not a drag)
        cursorMoved = Signal(QPointF)    # scene coords; (-1,-1) when off-image
        fileDropped = Signal(str)        # absolute path of a dropped image file

        _CLICK_DRAG_THRESHOLD_PX = 4
        _MIN_SCALE = 0.05
        _MAX_SCALE = 24.0

        def __init__(self, parent=None):
            super().__init__(parent)
            self._scene = QGraphicsScene(self)
            self.setScene(self._scene)
            self.setRenderHints(
                QPainter.Antialiasing | QPainter.SmoothPixmapTransform
            )
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setMouseTracking(True)
            self.setFrameShape(QFrame.NoFrame)
            self.setCursor(Qt.CrossCursor)
            self.viewport().setCursor(Qt.CrossCursor)
            # Drops on QAbstractScrollArea don't propagate to the parent
            # window — handle them here and forward via fileDropped.
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)

            self._pixmap_item: QGraphicsPixmapItem | None = None
            self._marker_items: list[QGraphicsItem] = []
            self._rect_item: QGraphicsRectItem | None = None
            self._live_rect_item: QGraphicsRectItem | None = None

            self._press_pos: QPoint | None = None
            self._press_scroll: tuple[int, int] | None = None
            self._maybe_click: bool = False

            # Pinch gesture (trackpad)
            self.grabGesture(Qt.PinchGesture)

        # ---- public API --------------------------------------------------

        def set_pixmap(self, pixmap: QPixmap) -> None:
            """Replace the displayed image and reset the view."""
            self._scene.clear()
            self._marker_items = []
            self._rect_item = None
            self._live_rect_item = None
            self._pixmap_item = self._scene.addPixmap(pixmap)
            self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
            self._scene.setSceneRect(QRectF(pixmap.rect()))
            self.resetTransform()
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

        def add_corner_marker(self, scene_pos: QPointF) -> None:
            r = self._marker_radius()
            ellipse = QGraphicsEllipseItem(
                scene_pos.x() - r, scene_pos.y() - r, 2 * r, 2 * r
            )
            pen = QPen(RED)
            pen.setWidthF(self._line_width())
            pen.setCosmetic(True)
            ellipse.setPen(pen)
            ellipse.setBrush(QBrush(RED_FILL))
            ellipse.setZValue(10)
            self._scene.addItem(ellipse)
            self._marker_items.append(ellipse)

        def set_locked_rect(self, p1: QPointF, p2: QPointF) -> None:
            """Draw the final solid red bounding box."""
            self._clear_live_rect()
            if self._rect_item is not None:
                self._scene.removeItem(self._rect_item)
            x1, y1 = min(p1.x(), p2.x()), min(p1.y(), p2.y())
            x2, y2 = max(p1.x(), p2.x()), max(p1.y(), p2.y())
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            item = QGraphicsRectItem(rect)
            pen = QPen(RED)
            pen.setWidthF(self._line_width())
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setZValue(9)
            self._scene.addItem(item)
            self._rect_item = item

        def set_live_rect(self, p1: QPointF, current: QPointF) -> None:
            """Update the dashed preview rect that follows the cursor."""
            x1, y1 = min(p1.x(), current.x()), min(p1.y(), current.y())
            x2, y2 = max(p1.x(), current.x()), max(p1.y(), current.y())
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            if self._live_rect_item is None:
                item = QGraphicsRectItem(rect)
                pen = QPen(RED)
                pen.setWidthF(self._line_width())
                pen.setCosmetic(True)
                pen.setStyle(Qt.DashLine)
                item.setPen(pen)
                item.setZValue(8)
                self._scene.addItem(item)
                self._live_rect_item = item
            else:
                self._live_rect_item.setRect(rect)

        def clear_overlays(self) -> None:
            for m in self._marker_items:
                self._scene.removeItem(m)
            self._marker_items = []
            if self._rect_item is not None:
                self._scene.removeItem(self._rect_item)
                self._rect_item = None
            self._clear_live_rect()

        def fit_to_view(self) -> None:
            if self._pixmap_item is not None:
                self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

        def has_pixmap(self) -> bool:
            return self._pixmap_item is not None

        def image_rect(self) -> QRectF:
            return self._pixmap_item.boundingRect() if self._pixmap_item else QRectF()

        # ---- internals ---------------------------------------------------

        def _clear_live_rect(self) -> None:
            if self._live_rect_item is not None:
                self._scene.removeItem(self._live_rect_item)
                self._live_rect_item = None

        def _line_width(self) -> float:
            # Cosmetic pen so the line stays the same screen-pixel width
            # regardless of zoom.
            return 2.0

        def _marker_radius(self) -> float:
            # Marker is drawn in scene coords, so divide by the current
            # scale to keep its on-screen size constant.
            t = self.transform()
            scale = max(t.m11(), 1e-6)
            return 5.0 / scale

        def _refresh_overlay_sizes(self) -> None:
            """Rebuild marker radii on zoom so dots stay constant on-screen."""
            r = self._marker_radius()
            for m in self._marker_items:
                if isinstance(m, QGraphicsEllipseItem):
                    cx = m.rect().center().x()
                    cy = m.rect().center().y()
                    m.setRect(cx - r, cy - r, 2 * r, 2 * r)

        # ---- drag & drop (forwarded to MainWindow) ----------------------

        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                event.ignore()

        def dragMoveEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()

        def dropEvent(self, event):
            urls = event.mimeData().urls()
            if not urls:
                event.ignore()
                return
            local = urls[0].toLocalFile()
            if local:
                event.acceptProposedAction()
                self.fileDropped.emit(local)
            else:
                event.ignore()

        # ---- gesture / wheel zoom ---------------------------------------

        def event(self, ev):  # noqa: D401
            if ev.type() == QEvent.Gesture:
                if self._handle_gesture(ev):
                    return True
            return super().event(ev)

        def _handle_gesture(self, ev) -> bool:
            pinch = ev.gesture(Qt.PinchGesture)
            if pinch is None:
                return False
            factor = float(pinch.scaleFactor())
            self._zoom_by(factor)
            ev.accept()
            return True

        def wheelEvent(self, event):
            if not self.has_pixmap():
                return
            modifiers = event.modifiers()
            # On macOS Qt maps Cmd → ControlModifier by default.
            if modifiers & (Qt.ControlModifier | Qt.MetaModifier):
                delta = event.angleDelta().y()
                if delta == 0:
                    return
                factor = 1.15 if delta > 0 else 1.0 / 1.15
                self._zoom_by(factor)
                event.accept()
            else:
                # Trackpad two-finger scroll → pan via default behavior.
                # Convert to manual scroll-bar adjust since we have scrollbars off.
                pixel_delta = event.pixelDelta()
                if not pixel_delta.isNull():
                    self.translate(pixel_delta.x() / self.transform().m11(),
                                   pixel_delta.y() / self.transform().m22())
                else:
                    angle = event.angleDelta()
                    self.translate(angle.x() / 8.0 / self.transform().m11(),
                                   angle.y() / 8.0 / self.transform().m22())
                event.accept()

        def _zoom_by(self, factor: float) -> None:
            current = self.transform().m11()
            proposed = current * factor
            if proposed < self._MIN_SCALE or proposed > self._MAX_SCALE:
                return
            self.scale(factor, factor)
            self._refresh_overlay_sizes()

        # ---- mouse: click vs pan ----------------------------------------

        def mousePressEvent(self, event):
            if not self.has_pixmap():
                return super().mousePressEvent(event)
            if event.button() == Qt.LeftButton:
                self._press_pos = event.position().toPoint()
                self._press_scroll = (
                    self.horizontalScrollBar().value(),
                    self.verticalScrollBar().value(),
                )
                self._maybe_click = True
                event.accept()
                return
            if event.button() in (Qt.MiddleButton, Qt.RightButton):
                self._press_pos = event.position().toPoint()
                self._press_scroll = (
                    self.horizontalScrollBar().value(),
                    self.verticalScrollBar().value(),
                )
                self._maybe_click = False
                self.viewport().setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event):
            if not self.has_pixmap():
                return super().mouseMoveEvent(event)
            scene_pos = self.mapToScene(event.position().toPoint())
            if self.image_rect().contains(scene_pos):
                self.cursorMoved.emit(scene_pos)
            else:
                self.cursorMoved.emit(QPointF(-1.0, -1.0))

            if self._press_pos is None:
                return super().mouseMoveEvent(event)
            current = event.position().toPoint()
            delta = current - self._press_pos
            if self._maybe_click and (
                abs(delta.x()) > self._CLICK_DRAG_THRESHOLD_PX
                or abs(delta.y()) > self._CLICK_DRAG_THRESHOLD_PX
            ):
                self._maybe_click = False
                self.viewport().setCursor(Qt.ClosedHandCursor)
            if not self._maybe_click and self._press_scroll is not None:
                self.horizontalScrollBar().setValue(self._press_scroll[0] - delta.x())
                self.verticalScrollBar().setValue(self._press_scroll[1] - delta.y())
                event.accept()
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):
            if not self.has_pixmap():
                return super().mouseReleaseEvent(event)
            if event.button() in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
                if (
                    event.button() == Qt.LeftButton
                    and self._maybe_click
                    and self._press_pos is not None
                ):
                    scene_pos = self.mapToScene(self._press_pos)
                    if self.image_rect().contains(scene_pos):
                        self.pointClicked.emit(scene_pos)
                self._press_pos = None
                self._press_scroll = None
                self._maybe_click = False
                self.viewport().setCursor(Qt.CrossCursor)
                event.accept()
                return
            super().mouseReleaseEvent(event)

    # ----------------------------------------------------------------------
    # MainWindow — drop target, status bar, key handling.
    # ----------------------------------------------------------------------

    class MainWindow(QMainWindow):
        _DEFAULT_HINT = (
            "Click 2 corners  ·  F save  ·  S clear  ·  drag to pan  ·  "
            "pinch / Cmd+scroll to zoom  ·  ⌘O / drop a new file to swap"
        )
        _EMPTY_HINT = "Drop an image to begin  ·  ⌘O to open"
        _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

        def __init__(self):
            super().__init__()
            self.setWindowTitle("NikkeOptimizer — Coord Picker")
            self.resize(1280, 920)
            self.setAcceptDrops(True)

            self._image: QImage | None = None
            self._image_path: Path | None = None
            self._selection = Selection()
            self._cursor_scene_pos: QPointF | None = None

            central = QWidget()
            central.setObjectName("central")
            self.setCentralWidget(central)
            v = QVBoxLayout(central)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)

            self.header = QFrame()
            self.header.setObjectName("header")
            self.header.setFixedHeight(46)
            h = QHBoxLayout(self.header)
            h.setContentsMargins(18, 0, 18, 0)
            self.filename_label = QLabel("No image loaded")
            self.filename_label.setObjectName("filename")
            self.dim_label = QLabel("")
            self.dim_label.setObjectName("dim")
            h.addWidget(self.filename_label)
            h.addStretch()
            h.addWidget(self.dim_label)
            v.addWidget(self.header)

            self.stack = QStackedWidget()
            v.addWidget(self.stack, 1)

            # Drop-zone page
            dz_page = QWidget()
            dz_layout = QVBoxLayout(dz_page)
            dz_layout.setAlignment(Qt.AlignCenter)
            self.dropzone = QLabel("Drop an image here\n\nPNG  ·  JPG  ·  WebP")
            self.dropzone.setObjectName("dropzone")
            self.dropzone.setProperty("active", False)
            dz_layout.addWidget(self.dropzone, alignment=Qt.AlignCenter)
            self.stack.addWidget(dz_page)

            # Image-view page
            self.view = ImageView()
            self.view.pointClicked.connect(self._on_point_clicked)
            self.view.cursorMoved.connect(self._on_cursor_moved)
            self.view.fileDropped.connect(self._on_file_dropped)
            self.stack.addWidget(self.view)

            # Status bar
            self.hint_label = QLabel(self._EMPTY_HINT)
            self.hint_label.setObjectName("hint")
            self.bbox_label = QLabel("")
            self.bbox_label.setObjectName("bbox_coords")
            self.cursor_label = QLabel("")
            self.cursor_label.setObjectName("cursor_coords")
            sb = self.statusBar()
            sb.setSizeGripEnabled(False)
            sb.addWidget(self.hint_label, 1)
            sb.addPermanentWidget(self.bbox_label)
            sb.addPermanentWidget(self.cursor_label)

            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._reset_hint)

        # ---- drag & drop -------------------------------------------------

        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                self.dropzone.setProperty("active", True)
                self._restyle(self.dropzone)

        def dragMoveEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()

        def dragLeaveEvent(self, _event):
            self.dropzone.setProperty("active", False)
            self._restyle(self.dropzone)

        def dropEvent(self, event):
            self.dropzone.setProperty("active", False)
            self._restyle(self.dropzone)
            urls = event.mimeData().urls()
            if not urls:
                return
            self._on_file_dropped(urls[0].toLocalFile())

        def _on_file_dropped(self, path_str: str):
            path = Path(path_str)
            if path.suffix.lower() not in self._IMAGE_EXTS:
                self._toast(f"Unsupported file: {path.suffix}", error=True)
                return
            if not path.is_file():
                self._toast(f"Not a file: {path.name}", error=True)
                return
            self.load_image(path)

        # ---- image lifecycle --------------------------------------------

        def load_image(self, path: Path) -> bool:
            image = QImage(str(path))
            if image.isNull():
                self._toast(f"Failed to read: {path.name}", error=True)
                return False
            self._image = image
            self._image_path = path
            self._selection = Selection()
            pixmap = QPixmap.fromImage(image)
            self.view.set_pixmap(pixmap)
            self.stack.setCurrentIndex(1)
            self.filename_label.setText(path.name)
            self.dim_label.setText(f"{image.width()} × {image.height()}")
            self.hint_label.setText(self._DEFAULT_HINT)
            self.bbox_label.setText("")
            self.setWindowTitle(f"NikkeOptimizer — Coord Picker — {path.name}")
            return True

        # ---- click handling ---------------------------------------------

        def _on_point_clicked(self, scene_pos: QPointF):
            if self._image is None:
                return
            x, y = self._clamped_image_xy(scene_pos)
            if self._selection.is_complete():
                # Box already locked — wait for S before starting fresh.
                return
            if self._selection.p1 is None:
                self._selection.p1 = (x, y)
                self.view.add_corner_marker(QPointF(x, y))
                self.hint_label.setText("Click second corner  ·  S to cancel")
            else:
                self._selection.p2 = (x, y)
                self.view.add_corner_marker(QPointF(x, y))
                self.view.set_locked_rect(
                    QPointF(*self._selection.p1), QPointF(x, y)
                )
                bbox = clamp_to_image(
                    self._selection.normalized(),
                    self._image.width(),
                    self._image.height(),
                )
                x1, y1, x2, y2 = bbox
                self.bbox_label.setText(
                    f"({x1}, {y1}, {x2}, {y2})   {x2 - x1}×{y2 - y1}"
                )
                self.hint_label.setText("F to save  ·  S to clear")

        def _on_cursor_moved(self, scene_pos: QPointF):
            if self._image is None:
                return
            self._cursor_scene_pos = scene_pos
            x, y = scene_pos.x(), scene_pos.y()
            if x < 0 or y < 0:
                self.cursor_label.setText("")
                return
            ix = max(0, min(self._image.width() - 1, int(round(x))))
            iy = max(0, min(self._image.height() - 1, int(round(y))))
            self.cursor_label.setText(f"{ix}, {iy}")
            # Live preview rect after first corner is set.
            if self._selection.p1 is not None and self._selection.p2 is None:
                self.view.set_live_rect(
                    QPointF(*self._selection.p1), QPointF(ix, iy)
                )

        def _clamped_image_xy(self, scene_pos: QPointF) -> tuple[float, float]:
            assert self._image is not None
            return (
                max(0.0, min(self._image.width() - 1, scene_pos.x())),
                max(0.0, min(self._image.height() - 1, scene_pos.y())),
            )

        # ---- key handling ------------------------------------------------

        def keyPressEvent(self, event):
            key = event.key()
            mods = event.modifiers()
            cmd_like = mods & (Qt.ControlModifier | Qt.MetaModifier)
            if key == Qt.Key_O and cmd_like:
                self._open_dialog()
                event.accept()
                return
            if key == Qt.Key_F:
                self._save_outputs()
                event.accept()
                return
            if key == Qt.Key_S:
                self._clear_selection()
                event.accept()
                return
            if key in (Qt.Key_0, Qt.Key_Equal) and cmd_like:
                self.view.fit_to_view()
                event.accept()
                return
            super().keyPressEvent(event)

        # ---- actions -----------------------------------------------------

        def _save_outputs(self):
            if self._image is None or self._image_path is None:
                self._toast("Drop an image first", error=True)
                return
            if not self._selection.is_complete():
                self._toast("Select two corners first", error=True)
                return
            bbox = clamp_to_image(
                self._selection.normalized(),
                self._image.width(),
                self._image.height(),
            )
            x1, y1, x2, y2 = bbox
            if x2 - x1 < 2 or y2 - y1 < 2:
                self._toast("Selection too small", error=True)
                return
            crop_rect = QRect(x1, y1, x2 - x1, y2 - y1)
            crop = self._image.copy(crop_rect)
            masked = QImage(self._image.size(), QImage.Format_ARGB32)
            masked.fill(Qt.black)
            painter = QPainter(masked)
            painter.drawImage(crop_rect, self._image, crop_rect)
            painter.end()

            crop_path, masked_path = output_paths(
                self._image_path, x1, y1, x2, y2
            )
            try:
                ok_crop = crop.save(str(crop_path), "PNG")
                ok_mask = masked.save(str(masked_path), "PNG")
            except OSError as exc:
                self._toast(f"Save failed: {exc}", error=True)
                return
            if not (ok_crop and ok_mask):
                self._toast("Save failed (Qt write returned False)", error=True)
                return

            coords = coord_string(x1, y1, x2, y2)
            QGuiApplication.clipboard().setText(coords)
            self._clear_selection()
            self._toast(
                f"Saved · {crop_path.name} + masked · clipboard: {coords}"
            )

        def _open_dialog(self):
            start_dir = (
                str(self._image_path.parent)
                if self._image_path is not None
                else str(Path.home())
            )
            path_str, _ = QFileDialog.getOpenFileName(
                self,
                "Open image",
                start_dir,
                "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All files (*)",
            )
            if path_str:
                self.load_image(Path(path_str))

        def _clear_selection(self):
            self._selection = Selection()
            self.view.clear_overlays()
            self.bbox_label.setText("")
            if self._image is not None:
                self.hint_label.setText(self._DEFAULT_HINT)
            else:
                self.hint_label.setText(self._EMPTY_HINT)

        def _toast(self, text: str, *, error: bool = False, ms: int = 3500):
            prefix = "✗" if error else "✓"
            self.hint_label.setText(f"{prefix}  {text}")
            self.hint_label.setProperty("toast", True)
            self._restyle(self.hint_label)
            self._toast_timer.start(ms)

        def _reset_hint(self):
            self.hint_label.setProperty("toast", False)
            self._restyle(self.hint_label)
            self.hint_label.setText(
                self._DEFAULT_HINT if self._image is not None else self._EMPTY_HINT
            )

        @staticmethod
        def _restyle(widget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    # ----------------------------------------------------------------------
    # Bootstrap
    # ----------------------------------------------------------------------

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(_APP_QSS)
    win = MainWindow()
    win.show()
    if image_path is not None:
        # Defer one tick so the view has been laid out before fitInView.
        QTimer.singleShot(50, lambda: win.load_image(image_path))
    return app.exec()


def main(argv: Optional[list[str]] = None) -> int:
    """Standalone entry-point used when invoked outside the CLI."""
    args = sys.argv[1:] if argv is None else argv
    image_path = Path(args[0]) if args else None
    if image_path is not None and not image_path.is_file():
        print(f"Image not found: {image_path}", file=sys.stderr)
        return 1
    return run(image_path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
