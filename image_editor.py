"""Lumen v2: permanent dark interface and non-destructive JPG/PNG editor."""

from __future__ import annotations

import copy
import faulthandler
import hashlib
import json
import math
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path


# A startup trace helps diagnose a white or unresponsive packaged window.
# It contains only stage names and Python exceptions, never image contents.
_STARTUP_LOG = None
try:
    _STARTUP_LOG = open(Path(tempfile.gettempdir()) / "Lumen-startup.log",
                        "w", encoding="utf-8", buffering=1)
    _STARTUP_LOG.write(f"Lumen startup {datetime.now().isoformat(timespec='seconds')}\n")
    faulthandler.enable(file=_STARTUP_LOG)
    faulthandler.dump_traceback_later(20, repeat=True, file=_STARTUP_LOG)
except OSError:
    _STARTUP_LOG = None


def startup_stage(stage: str) -> None:
    if _STARTUP_LOG is not None:
        _STARTUP_LOG.write(f"{time.monotonic():.3f} {stage}\n")


startup_stage("Importing image and window libraries")

import numpy as np
from PIL import Image
from processing import crop_bounds, load_cube, load_photo, neutral_gains, parade, render

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRectF, QPointF, QTimer, QObject, QRunnable, QThreadPool, QStandardPaths
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QImage, QPainterPath, QFont, QFontMetricsF, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsPathItem, QGraphicsTextItem, QGraphicsItem,
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QSlider, QComboBox, QLineEdit, QFrame, QScrollArea,
    QSizePolicy, QSpacerItem, QFileDialog, QMessageBox, QInputDialog,
)

startup_stage("Libraries imported")


# ---------------------------------------------------------------------------
#  Theme — Windows 11 Fluent, dark only. No light mode, no theme switch.
# ---------------------------------------------------------------------------

COLOR_WINDOW_BG     = "#202020"   # app chrome
COLOR_PANEL_BG      = "#2d2d2d"   # container panels / cards
COLOR_PANEL_BG_ALT  = "#333333"   # hovered / raised surfaces
COLOR_CANVAS_BG     = "#1a1a1a"   # neutral viewport, low eye strain
COLOR_STROKE        = "#3d3d3d"   # 1px Fluent control borders
COLOR_TEXT          = "#ffffff"
COLOR_TEXT_DIM      = "#c5c5c5"
COLOR_ACCENT        = "#4cc2ff"   # Fluent dark-mode accent
COLOR_ACCENT_PRESS  = "#3aa8e0"

QSS = f"""
QWidget {{
    background-color: {COLOR_WINDOW_BG};
    color: {COLOR_TEXT};
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}

/* ---------- Panels / cards ---------- */
QFrame#ControlPanel {{
    background-color: {COLOR_WINDOW_BG};
    border-left: 1px solid {COLOR_STROKE};
}}
QFrame#Card {{
    background-color: {COLOR_PANEL_BG};
    border: 1px solid {COLOR_STROKE};
    border-radius: 8px;
}}
QLabel#SectionTitle {{
    color: {COLOR_TEXT};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.4px;
    background: transparent;
}}
QLabel#FieldLabel {{
    color: {COLOR_TEXT_DIM};
    background: transparent;
}}
QLabel#ValueBadge {{
    background-color: #272727;
    border: 1px solid {COLOR_STROKE};
    border-radius: 5px;
    color: {COLOR_TEXT};
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
    padding: 1px 0px;
    min-width: 46px;
    qproperty-alignment: AlignCenter;
}}
QLabel#StatusText {{
    color: {COLOR_TEXT_DIM};
    background: transparent;
    font-size: 12px;
}}
QFrame#Separator {{
    background-color: {COLOR_STROKE};
    max-height: 1px;
    border: none;
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background-color: #313131;
    border: 1px solid {COLOR_STROKE};
    border-radius: 6px;
    padding: 7px 12px;
    color: {COLOR_TEXT};
}}
QPushButton:hover   {{ background-color: {COLOR_PANEL_BG_ALT}; }}
QPushButton:pressed {{ background-color: #2a2a2a; color: {COLOR_TEXT_DIM}; }}
QPushButton:disabled {{ color: #6b6b6b; border-color: #333333; }}

QPushButton#AccentButton {{
    background-color: {COLOR_ACCENT};
    border: 1px solid {COLOR_ACCENT};
    color: #0d0d0d;
    font-weight: 600;
}}
QPushButton#AccentButton:hover   {{ background-color: #5fcbff; }}
QPushButton#AccentButton:pressed {{ background-color: {COLOR_ACCENT_PRESS}; }}

QPushButton#ToggleButton {{
    background-color: #313131;
    border: 1px solid {COLOR_STROKE};
    border-radius: 6px;
    padding: 9px 10px;
    text-align: center;
}}
QPushButton#ToggleButton:hover {{ background-color: {COLOR_PANEL_BG_ALT}; }}
QPushButton#ToggleButton:checked {{
    background-color: rgba(76, 194, 255, 0.18);
    border: 1px solid {COLOR_ACCENT};
    color: {COLOR_ACCENT};
    font-weight: 600;
}}

QPushButton#CollapseHeader {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 4px;
    text-align: left;
    font-size: 12px;
    font-weight: 600;
    color: {COLOR_TEXT};
}}
QPushButton#CollapseHeader:hover {{ background-color: #282828; }}

/* ---------- Sliders (Fluent track + pill handle) ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background-color: #4a4a4a;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    height: 4px;
    background-color: {COLOR_ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background-color: #e8e8e8;
    border: 5px solid #262626;
    width: 8px;
    height: 8px;
    margin: -8px 0px;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{
    background-color: {COLOR_ACCENT};
    border: 4px solid #262626;
}}
QSlider::handle:horizontal:pressed {{
    background-color: {COLOR_ACCENT_PRESS};
    border: 6px solid #262626;
}}

QSlider#RedSlider::sub-page:horizontal   {{ background-color: #f16a6a; }}
QSlider#GreenSlider::sub-page:horizontal {{ background-color: #6fd38a; }}
QSlider#BlueSlider::sub-page:horizontal  {{ background-color: #6ba8f1; }}

/* ---------- Inputs ---------- */
QComboBox, QLineEdit {{
    background-color: #272727;
    border: 1px solid {COLOR_STROKE};
    border-bottom: 1px solid #585858;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: #0d0d0d;
}}
QComboBox:hover, QLineEdit:hover {{ background-color: #2c2c2c; }}
QLineEdit:focus {{ border-bottom: 2px solid {COLOR_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {COLOR_PANEL_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_STROKE};
    border-radius: 6px;
    outline: none;
    selection-background-color: #3a3a3a;
    padding: 4px;
}}

/* ---------- Canvas + scrollbars ---------- */
QGraphicsView#ImageCanvas {{
    background-color: {COLOR_CANVAS_BG};
    border: none;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #4f4f4f; border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #6a6a6a; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #4f4f4f; border-radius: 4px; min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


# ---------------------------------------------------------------------------
#  Reusable widgets
# ---------------------------------------------------------------------------

class SliderRow(QWidget):
    """Label + Fluent slider + live numeric badge.

    The badge is the only thing this widget updates itself; the owner
    connects `value_changed` to the real (placeholder) processing hook.
    """

    value_changed = pyqtSignal(str, int)   # (key, value)

    def __init__(self, key: str, caption: str, minimum: int, maximum: int,
                 baseline: int = 0, slider_object_name: str | None = None,
                 suffix: str = "", signed: bool = True, parent=None):
        super().__init__(parent)
        self.key = key
        self.baseline = baseline
        self.suffix = suffix
        self.signed = signed

        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("FieldLabel")

        self.value_badge = QLabel()
        self.value_badge.setObjectName("ValueBadge")
        self.value_badge.setFixedWidth(52)
        self.value_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        if slider_object_name:
            self.slider.setObjectName(slider_object_name)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setValue(baseline)
        self.slider.valueChanged.connect(self._on_slider_moved)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(self.caption_label)
        head.addStretch(1)
        head.addWidget(self.value_badge)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addLayout(head)
        root.addWidget(self.slider)

        self._refresh_badge(baseline)

    # -- live label wiring (the one piece of real logic in this file) ------
    def _on_slider_moved(self, value: int) -> None:
        self._refresh_badge(value)
        self.value_changed.emit(self.key, value)

    def _refresh_badge(self, value: int) -> None:
        if self.signed and value > 0:
            text = f"+{value}"
        else:
            text = f"{value}"
        self.value_badge.setText(text + self.suffix)

    def value(self) -> int:
        return self.slider.value()

    def reset(self) -> None:
        self.slider.setValue(self.baseline)

    def set_value_silently(self, value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self._refresh_badge(self.slider.value())


class Card(QFrame):
    """Rounded dark container panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(10)


class CollapsibleSection(QWidget):
    """Section header that collapses its card body (Fluent expander)."""

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._title = title

        self.header_button = QPushButton()
        self.header_button.setObjectName("CollapseHeader")
        self.header_button.setCheckable(True)
        self.header_button.setChecked(expanded)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.toggled.connect(self._on_toggled)

        self.card = Card()
        self.content = self.card.body

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self.header_button)
        root.addWidget(self.card)

        self._on_toggled(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        chevron = "\u2304" if expanded else "\u203a"
        self.header_button.setText(f"  {chevron}   {self._title.upper()}")
        self.card.setVisible(expanded)

    def add_widget(self, widget: QWidget) -> None:
        self.content.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.content.addLayout(layout)


class RGBParadeScope(QFrame):
    """Real-time RGB Parade scope.

    Placeholder surface: paints the three channel columns (R | G | B) with
    IRE gridlines on a near-black ground. `update_parade(QImage)` is where
    the waveform sampling will later write into `self._parade_data`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._parade_data = None   # future: per-column luminance histograms

    # -- placeholder hook -------------------------------------------------
    def update_parade(self, source_image: Image.Image | None) -> None:
        self._parade_data = parade(source_image) if source_image is not None else None
        self._parade_images = []
        if self._parade_data is not None:
            for density, color in zip(self._parade_data,
                                      (QColor("#f16a6a"), QColor("#6fd38a"), QColor("#6ba8f1"))):
                height, width = density.shape
                rgba = np.zeros((height, width, 4), dtype=np.uint8)
                rgba[..., :3] = (color.red(), color.green(), color.blue())
                rgba[..., 3] = np.uint8(np.clip(density ** .65 * 255, 0, 255))
                self._parade_images.append(QImage(rgba.tobytes(), width, height, width * 4,
                                                 QImage.Format.Format_RGBA8888).copy())
        self.update()

    def clear_parade(self) -> None:
        self._parade_data = None
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        area = QRectF(self.rect()).adjusted(9, 9, -9, -9)
        painter.fillRect(area, QColor("#131313"))

        # horizontal IRE gridlines
        painter.setPen(QPen(QColor("#262626"), 1))
        for i in range(1, 4):
            y = area.top() + area.height() * i / 4.0
            painter.drawLine(int(area.left()), int(y),
                             int(area.right()), int(y))

        # channel column dividers + labels
        column_width = area.width() / 3.0
        channels = (("R", "#f16a6a"), ("G", "#6fd38a"), ("B", "#6ba8f1"))
        for index, (name, color) in enumerate(channels):
            left = area.left() + column_width * index
            if index:
                painter.setPen(QPen(QColor("#2e2e2e"), 1))
                painter.drawLine(int(left), int(area.top()),
                                 int(left), int(area.bottom()))
            painter.setPen(QPen(QColor(color).darker(140), 1))
            painter.drawText(
                QRectF(left + 6, area.top() + 4, 20, 14),
                Qt.AlignmentFlag.AlignLeft, name)
            plot = QRectF(left + 4, area.top() + 20, column_width - 8, area.height() - 26)
            if self._parade_data is not None:
                painter.drawImage(plot, self._parade_images[index])
            painter.setPen(QPen(QColor(255, 255, 255, 190), 1))
            painter.drawLine(int(plot.left()), int(plot.top()), int(plot.right()), int(plot.top()))
            painter.drawLine(int(plot.left()), int(plot.bottom()), int(plot.right()), int(plot.bottom()))

        if self._parade_data is None:
            painter.setPen(QPen(QColor("#5a5a5a"), 1))
            font = painter.font()
            font.setFamily("Consolas")
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter,
                             "RGB PARADE  ·  awaiting image data")
        painter.end()


class ImageCanvas(QGraphicsView):
    """Zoom / pan viewport.

    Hard rule: `set_pixmap()` never mutates the view transform. Only
    `fit_to_window()` does, and it is called solely on a new file load.
    """

    zoom_changed = pyqtSignal(float)
    point_picked = pyqtSignal(float, float)
    selection_finished = pyqtSignal(object)
    stroke_finished = pyqtSignal(object)
    erase_requested = pyqtSignal(float, float)
    text_requested = pyqtSignal(float, float)
    markup_moved = pyqtSignal()

    MIN_SCALE = 0.05
    MAX_SCALE = 32.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImageCanvas")
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)

        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor(COLOR_CANVAS_BG))

        self._has_image = False
        self.mode = "pan"
        self.pen_width = 4
        self.pen_color = QColor("#f16a6a")
        self._drag_start = None
        self._points = []
        self._live_path = None
        self.selection_item = QGraphicsRectItem()
        self.selection_item.setPen(QPen(QColor("white"), 1, Qt.PenStyle.DashLine))
        self.selection_item.setBrush(QColor(76, 194, 255, 50))
        self.selection_item.setZValue(3)
        self._scene.addItem(self.selection_item)
        self.selection_item.hide()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if mode == "pan"
                         else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if mode in
                                  ("crop", "pick", "pen", "erase", "text")
                                  else Qt.CursorShape.ArrowCursor)
        if mode != "crop":
            self.selection_item.hide()

    def _point(self, event):
        point = self.mapToScene(event.position().toPoint())
        rect = self._pixmap_item.boundingRect()
        return rect, point

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._has_image:
            rect, point = self._point(event)
            if rect.contains(point):
                if self.mode == "pick":
                    self.point_picked.emit(point.x(), point.y())
                    return
                if self.mode == "erase":
                    self.erase_requested.emit(point.x(), point.y())
                    return
                if self.mode == "crop":
                    self._drag_start = point
                    self.selection_item.setRect(QRectF(point, point))
                    self.selection_item.show()
                    return
                if self.mode == "pen":
                    self._points = [(point.x(), point.y())]
                    self._live_path = QGraphicsPathItem(QPainterPath(point))
                    self._live_path.setPen(QPen(self.pen_color, self.pen_width))
                    self._live_path.setZValue(5)
                    self._scene.addItem(self._live_path)
                    return
                if self.mode == "text":
                    if isinstance(self._scene.itemAt(point, self.transform()), QGraphicsTextItem):
                        super().mousePressEvent(event)
                    else:
                        self.text_requested.emit(point.x(), point.y())
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None or self._live_path is not None:
            rect, point = self._point(event)
            point.setX(max(0, min(rect.width(), point.x())))
            point.setY(max(0, min(rect.height(), point.y())))
            if self._drag_start is not None:
                self.selection_item.setRect(QRectF(self._drag_start, point).normalized())
            else:
                self._points.append((point.x(), point.y()))
                path = self._live_path.path()
                path.lineTo(point)
                self._live_path.setPath(path)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_start is not None:
            self._drag_start = None
            self.selection_finished.emit(self.selection_item.rect())
            return
        if self._live_path is not None:
            self._scene.removeItem(self._live_path)
            self._live_path = None
            self.stroke_finished.emit(self._points)
            self._points = []
            return
        super().mouseReleaseEvent(event)
        self.markup_moved.emit()

    # -- viewport update: transform-safe ----------------------------------
    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Swap displayed pixels. Zoom and pan are intentionally preserved
        so live slider previews cannot yank the user's framing."""
        same_size = (self._has_image
                     and self._pixmap_item.pixmap().size() == pixmap.size())
        horizontal = self.horizontalScrollBar().value()
        vertical = self.verticalScrollBar().value()
        self._pixmap_item.setPixmap(pixmap)
        self._has_image = not pixmap.isNull()
        if not same_size:
            # Scene rect must track pixel dimensions, but do NOT re-fit.
            self._scene.setSceneRect(QRectF(pixmap.rect()))
        else:
            # Qt may shift scrollbars by a few pixels when a pixmap item is
            # invalidated, even though its size and our transform are unchanged.
            self.horizontalScrollBar().setValue(horizontal)
            self.verticalScrollBar().setValue(vertical)

    def fit_to_window(self) -> None:
        """Reset zoom/pan. Call ONLY when a new file is loaded (or from an
        explicit user 'Fit' action) — never from a preview refresh."""
        if not self._has_image:
            return
        self.resetTransform()
        self.fitInView(self._pixmap_item,
                       Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_changed.emit(self.current_scale())

    def current_scale(self) -> float:
        return self.transform().m11()

    def zoom_by(self, factor: float) -> None:
        target = self.current_scale() * factor
        if target < self.MIN_SCALE or target > self.MAX_SCALE:
            return
        self.scale(factor, factor)
        self.zoom_changed.emit(self.current_scale())

    def zoom_to_actual_pixels(self) -> None:
        self.resetTransform()
        self.zoom_changed.emit(self.current_scale())

    # Ctrl-less wheel zoom, Fluent-smooth step
    def wheelEvent(self, event) -> None:
        if not self._has_image:
            return
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_by(1.12 ** steps)
        event.accept()

    def sizeHint(self) -> QSize:
        return QSize(900, 700)


# ---------------------------------------------------------------------------
#  Main window
# ---------------------------------------------------------------------------

class ImageEditorShell(QMainWindow):

    image_loaded = pyqtSignal(str)
    adjustments_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumen v2")
        self.resize(1200, 800)
        self.setMinimumSize(850, 580)

        self.slider_rows: dict[str, SliderRow] = {}
        self.source_image: QImage | None = None

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_canvas_area(), 1)
        root.addWidget(self._build_control_panel(), 0)
        self.setCentralWidget(central)

        self.statusBar().setSizeGripEnabled(True)
        self.statusBar().showMessage("No image loaded")

    # ---------------- canvas side ----------------------------------------
    def _build_canvas_area(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.image_canvas = ImageCanvas()
        self.image_canvas.zoom_changed.connect(self._on_zoom_changed)

        # thin viewport toolbar
        bar = QWidget()
        bar.setFixedHeight(44)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 6, 14, 6)
        bar_layout.setSpacing(8)

        self.filename_label = QLabel("untitled")
        self.filename_label.setObjectName("StatusText")

        self.zoom_out_button = QPushButton("\u2212")
        self.zoom_in_button = QPushButton("+")
        for button in (self.zoom_out_button, self.zoom_in_button):
            button.setFixedWidth(34)
        self.zoom_level_label = QLabel("100%")
        self.zoom_level_label.setObjectName("ValueBadge")
        self.zoom_level_label.setFixedWidth(60)
        self.fit_button = QPushButton("Fit")
        self.actual_size_button = QPushButton("1:1")

        self.zoom_out_button.clicked.connect(
            lambda: self.image_canvas.zoom_by(1 / 1.25))
        self.zoom_in_button.clicked.connect(
            lambda: self.image_canvas.zoom_by(1.25))
        self.fit_button.clicked.connect(self.image_canvas.fit_to_window)
        self.actual_size_button.clicked.connect(
            self.image_canvas.zoom_to_actual_pixels)

        bar_layout.addWidget(self.filename_label)
        bar_layout.addStretch(1)
        for widget in (self.zoom_out_button, self.zoom_level_label,
                       self.zoom_in_button, self.fit_button,
                       self.actual_size_button):
            bar_layout.addWidget(widget)

        layout.addWidget(bar)
        separator = QFrame()
        separator.setObjectName("Separator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        layout.addWidget(self.image_canvas, 1)
        return container

    # ---------------- control panel --------------------------------------
    def _build_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("ControlPanel")
        panel.setFixedWidth(348)

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(14, 14, 14, 18)
        column.setSpacing(12)

        column.addLayout(self._build_file_row())
        column.addWidget(self._build_scope_section())
        column.addWidget(self._build_quick_tools_section())
        column.addWidget(self._build_tonal_section())
        column.addWidget(self._build_rgb_section())
        column.addWidget(self._build_presets_section())
        column.addWidget(self._build_lut_section())
        column.addWidget(self._build_markup_section())
        column.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                   QSizePolicy.Policy.Expanding))

        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 10, 14, 14)
        footer.setSpacing(8)
        self.reset_all_button = QPushButton("Reset All Adjustments")
        self.reset_all_button.clicked.connect(self.reset_all_adjustments)
        footer.addWidget(self.reset_all_button)
        outer.addLayout(footer)
        return panel

    def _build_file_row(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.load_image_button = QPushButton("Load Image")
        self.load_image_button.setObjectName("AccentButton")
        self.save_image_button = QPushButton("Save Image")
        self.load_image_button.clicked.connect(self.load_image)
        self.save_image_button.clicked.connect(self.save_image)
        row.addWidget(self.load_image_button, 1)
        row.addWidget(self.save_image_button, 1)
        return row

    def _build_scope_section(self):
        section = CollapsibleSection("RGB Parade Scope")
        self.rgb_parade_scope = RGBParadeScope()
        section.add_widget(self.rgb_parade_scope)
        return section

    def _build_quick_tools_section(self):
        section = CollapsibleSection("Quick Tools")
        grid = QGridLayout()
        grid.setSpacing(8)

        self.crop_tool_toggle = QPushButton("Crop Tool")
        self.white_balance_eyedropper_toggle = QPushButton("WB Eyedropper")
        for button in (self.crop_tool_toggle,
                       self.white_balance_eyedropper_toggle):
            button.setObjectName("ToggleButton")
            button.setCheckable(True)

        self.crop_tool_toggle.toggled.connect(self.on_crop_tool_toggled)
        self.white_balance_eyedropper_toggle.toggled.connect(
            self.on_white_balance_eyedropper_toggled)

        grid.addWidget(self.crop_tool_toggle, 0, 0)
        grid.addWidget(self.white_balance_eyedropper_toggle, 0, 1)
        section.add_layout(grid)
        section.add_widget(QLabel("Choose a ratio, drag on the photo, then Apply."))
        self.crop_ratio_combo = QComboBox()
        self.crop_ratio_combo.addItems(["Freeform", "Original", "1:1", "4:3", "16:9"])
        section.add_widget(self.crop_ratio_combo)
        crop_actions = QHBoxLayout()
        self.crop_apply_button = QPushButton("Apply Crop")
        self.crop_reset_button = QPushButton("Reset Crop")
        self.crop_apply_button.setEnabled(False)
        self.crop_apply_button.clicked.connect(self.apply_crop)
        self.crop_reset_button.clicked.connect(self.reset_crop)
        crop_actions.addWidget(self.crop_apply_button)
        crop_actions.addWidget(self.crop_reset_button)
        section.add_layout(crop_actions)
        return section

    def _build_tonal_section(self):
        section = CollapsibleSection("Tonal Adjustments")
        for key, caption in (
            ("brightness", "Brightness"),
            ("exposure", "Exposure"),
            ("contrast", "Contrast"),
            ("saturation", "Saturation"),
            ("highlights", "Highlights"),
            ("shadows", "Shadows"),
        ):
            section.add_widget(self._make_slider_row(key, caption, -100, 100, 0))
        return section

    def _build_rgb_section(self):
        section = CollapsibleSection("RGB Channels")
        for key, caption, object_name in (
            ("red", "Red", "RedSlider"),
            ("green", "Green", "GreenSlider"),
            ("blue", "Blue", "BlueSlider"),
        ):
            section.add_widget(self._make_slider_row(
                key, caption, -100, 100, 0, slider_object_name=object_name))
        self.clear_sample_button = QPushButton("Clear WB Sample")
        self.clear_sample_button.clicked.connect(self.clear_white_balance_sample)
        section.add_widget(self.clear_sample_button)
        return section

    def _build_presets_section(self):
        section = CollapsibleSection("Custom Presets")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["— No preset —"])
        self.preset_combo.currentTextChanged.connect(self.apply_preset)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.save_preset_button = QPushButton("Save Current as Preset")
        self.delete_preset_button = QPushButton("Delete")
        self.delete_preset_button.setFixedWidth(84)
        self.save_preset_button.clicked.connect(self.save_current_as_preset)
        self.delete_preset_button.clicked.connect(self.delete_selected_preset)
        row.addWidget(self.save_preset_button, 1)
        row.addWidget(self.delete_preset_button, 0)

        section.add_widget(self.preset_combo)
        section.add_layout(row)
        return section

    def _build_lut_section(self):
        section = CollapsibleSection("LUT")
        self.load_lut_button = QPushButton("Load .cube LUT")
        self.load_lut_button.clicked.connect(self.load_lut_file)
        self.clear_lut_button = QPushButton("Clear LUT")
        self.clear_lut_button.clicked.connect(self.clear_lut)
        self.loaded_lut_label = QLabel("No LUT loaded")
        self.loaded_lut_label.setObjectName("StatusText")
        section.add_widget(self.load_lut_button)
        section.add_widget(self.clear_lut_button)
        section.add_widget(self.loaded_lut_label)
        section.add_widget(self._make_slider_row(
            "lut_intensity", "LUT Intensity", 0, 100, 100,
            suffix="%", signed=False))
        return section

    def _build_markup_section(self):
        section = CollapsibleSection("Text & Drawing Markup",
                                     expanded=False)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.add_text_toggle = QPushButton("Add Text")
        self.draw_pen_tool_toggle = QPushButton("Draw / Pen")
        self.eraser_tool_toggle = QPushButton("Eraser")
        for button in (self.add_text_toggle, self.draw_pen_tool_toggle,
                       self.eraser_tool_toggle):
            button.setObjectName("ToggleButton")
            button.setCheckable(True)
        self.add_text_toggle.toggled.connect(self.on_add_text_toggled)
        self.draw_pen_tool_toggle.toggled.connect(
            self.on_draw_pen_tool_toggled)
        self.eraser_tool_toggle.toggled.connect(self.on_eraser_tool_toggled)
        grid.addWidget(self.add_text_toggle, 0, 0)
        grid.addWidget(self.draw_pen_tool_toggle, 0, 1)
        grid.addWidget(self.eraser_tool_toggle, 1, 0)
        self.clear_markup_button = QPushButton("Clear Markup")
        self.clear_markup_button.clicked.connect(self.clear_markup)
        grid.addWidget(self.clear_markup_button, 1, 1)
        section.add_layout(grid)

        self.markup_text_input = QLineEdit()
        self.markup_text_input.setPlaceholderText("Type overlay text…")
        self.markup_text_input.textChanged.connect(self.on_markup_text_changed)
        section.add_widget(self.markup_text_input)

        section.add_widget(self._make_slider_row(
            "font_size", "Font Size", 8, 240, 48,
            suffix=" px", signed=False))
        section.add_widget(self._make_slider_row(
            "pen_size", "Pen Size", 1, 30, 4,
            suffix=" px", signed=False))
        self.pen_color_combo = QComboBox()
        self.pen_color_combo.addItems(["Red", "White", "Black"])
        self.pen_color_combo.currentTextChanged.connect(self._update_pen_style)
        section.add_widget(self.pen_color_combo)
        return section

    def _make_slider_row(self, key, caption, minimum, maximum, baseline,
                         slider_object_name=None, suffix="",
                         signed=True) -> SliderRow:
        row = SliderRow(key, caption, minimum, maximum, baseline,
                        slider_object_name=slider_object_name,
                        suffix=suffix, signed=signed)
        row.value_changed.connect(self.on_adjustment_changed)
        self.slider_rows[key] = row
        return row

    # ---------------- state ----------------------------------------------
    def current_adjustments(self) -> dict:
        """Full adjustment state — the single source of truth for both the
        preview pipeline and preset serialisation."""
        return {key: row.value() for key, row in self.slider_rows.items()}

    def reset_all_adjustments(self) -> None:
        for row in self.slider_rows.values():
            row.reset()
        self.refresh_preview()

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_level_label.setText(f"{scale * 100:.0f}%")

    # ---------------- live wiring ----------------------------------------
    def on_adjustment_changed(self, key: str, value: int) -> None:
        """Called on every slider move. Badges already updated themselves;
        here we only kick the preview. Note this path must NEVER call
        fit_to_window()."""
        self.adjustments_changed.emit(self.current_adjustments())
        self.refresh_preview()

    def refresh_preview(self) -> None:
        """PLACEHOLDER: run `self.source_image` through the adjustment
        pipeline and push the result via `ImageCanvas.set_pixmap()`.

        Anti-reset contract: set_pixmap() only. No resetTransform(),
        no fitInView(), no fit_to_window() — the user's zoom and pan are
        sacred during live editing.
        """
        if self.source_image is None:
            return
        # processed = pipeline.apply(self.source_image, self.current_adjustments())
        # self.image_canvas.set_pixmap(QPixmap.fromImage(processed))
        # self.rgb_parade_scope.update_parade(processed)

    # ---------------- placeholders: file IO -------------------------------
    def load_image(self) -> None:
        """PLACEHOLDER: QFileDialog for JPG/PNG, decode into
        `self.source_image`, then:
            self.image_canvas.set_pixmap(pixmap)
            self.image_canvas.fit_to_window()   # ONLY legal call site
            self.rgb_parade_scope.update_parade(image)
        """

    def save_image(self) -> None:
        """PLACEHOLDER: render adjustments at full resolution and write out
        via QFileDialog.getSaveFileName()."""

    # ---------------- placeholders: tools --------------------------------
    def on_crop_tool_toggled(self, checked: bool) -> None:
        """PLACEHOLDER: show/hide the crop rubber-band overlay on the canvas."""

    def on_white_balance_eyedropper_toggled(self, checked: bool) -> None:
        """PLACEHOLDER: arm sampling mode; on canvas click, read the pixel and
        solve neutral RGB gains, then write them into the RGB sliders."""

    def on_add_text_toggled(self, checked: bool) -> None:
        """PLACEHOLDER: place a draggable text item using
        `self.markup_text_input.text()` and the Font Size slider."""

    def on_draw_pen_tool_toggled(self, checked: bool) -> None:
        """PLACEHOLDER: enter freehand draw mode. Remember to swap the canvas
        DragMode away from ScrollHandDrag while the pen is active, and restore
        it on untoggle."""

    def on_markup_text_changed(self, text: str) -> None:
        """PLACEHOLDER: live-update the selected text overlay item."""

    # ---------------- placeholders: presets / LUT -------------------------
    def save_current_as_preset(self) -> None:
        """PLACEHOLDER — Preset architecture requirements (do not shortcut):

        1. The serialised preset must capture *every* adjustment, not just the
           basic trio. That means brightness, exposure, contrast, SATURATION,
           HIGHLIGHTS, SHADOWS, the red/green/blue channel offsets, the
           WHITE BALANCE result (sampled neutral gains / temp-tint), and the
           LUT intensity value. Drive it off `current_adjustments()` so new
           sliders are picked up automatically rather than hand-listing keys.

        2. LUT files must be *copied*, never referenced in place. On save,
           copy the loaded .cube / .lut file into a local relative directory
           (e.g. `.presets/luts/<preset-name>.cube`) and store only that
           relative path in the preset JSON. If the user later moves, renames,
           or deletes the original file, the preset must still resolve.
           Relative paths also keep the preset folder portable between
           machines — never persist absolute paths.

        3. Write presets as JSON to `.presets/<name>.json` with a schema
           version field so future slider additions can be migrated.
        """

    def delete_selected_preset(self) -> None:
        """PLACEHOLDER: remove the preset JSON and its copied LUT in
        `.presets/luts/` if no other preset references it, then refresh the
        combo box."""

    def apply_preset(self, preset_name: str) -> None:
        """PLACEHOLDER: load the preset JSON, set every slider via
        `blockSignals()` to avoid N preview rebuilds, resolve the relative
        LUT path, then call `refresh_preview()` once."""

    def load_lut_file(self) -> None:
        """PLACEHOLDER: QFileDialog for .cube/.lut, parse into a 3D LUT, update
        `self.loaded_lut_label`, then `refresh_preview()`."""


class RenderSignals(QObject):
    finished = pyqtSignal(int, object, object)
    failed = pyqtSignal(int, str)


class PreviewTask(QRunnable):
    def __init__(self, generation, image, state, lut):
        super().__init__()
        self.generation, self.image, self.state, self.lut = generation, image, state, lut
        self.signals = RenderSignals()

    def run(self):
        try:
            bounds = crop_bounds(self.image, self.state.get("crop"))
            preview = render(self.image, self.state, self.lut, max_side=2048)
            self.signals.finished.emit(self.generation, preview, bounds)
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc))


class ExportSignals(QObject):
    done = pyqtSignal(str, str)


class ExportTask(QRunnable):
    def __init__(self, image, state, lut, path):
        super().__init__()
        self.image, self.state, self.lut, self.path = image, state, lut, path
        self.signals = ExportSignals()

    def run(self):
        try:
            result = render(self.image, self.state, self.lut)
            bounds = crop_bounds(self.image, self.state.get("crop"))
            if Path(self.path).suffix.lower() in (".jpg", ".jpeg") and result.mode == "RGBA":
                background = Image.new("RGB", result.size, "white")
                background.paste(result, mask=result.getchannel("A"))
                result = background
            qimage = ImageEditorWindow.to_qimage(result)
            if self.state.get("texts"):
                painter = QPainter(qimage)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                for item in self.state["texts"]:
                    font = QFont("Segoe UI")
                    font.setPixelSize(item["size"])
                    painter.setFont(font)
                    x, y = item["x"] - bounds[0], item["y"] - bounds[1]
                    baseline = y + QFontMetricsF(font).ascent()
                    painter.setPen(QColor(0, 0, 0, 180))
                    painter.drawText(QPointF(x + 2, baseline + 2), item["text"])
                    painter.setPen(QColor("white"))
                    painter.drawText(QPointF(x, baseline), item["text"])
                painter.end()
            if Path(self.path).suffix.lower() in (".jpg", ".jpeg"):
                qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)
            fmt = "PNG" if Path(self.path).suffix.lower() == ".png" else "JPG"
            if not qimage.save(self.path, fmt, -1 if fmt == "PNG" else 92):
                raise OSError("Could not write the edited image.")
            self.signals.done.emit(self.path, "")
        except Exception as exc:
            self.signals.done.emit(self.path, str(exc))


class ImageEditorWindow(ImageEditorShell):
    """Backend for Claude's v2 UI. Images and markup use original-image coordinates."""

    def __init__(self):
        super().__init__()
        self.source_image: Image.Image | None = None
        self.source_path: str | None = None
        self.state = self._default_state()
        self.lut = None
        self._preview_scale = 1.0
        self._selected_crop = None
        self._render_generation = 0
        self._render_running = False
        self._current_task = None
        self._export_task = None
        self._text_items = []
        self._tool_changing = False
        self._slider_drag = False
        self.undo_stack, self.redo_stack = [], []
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._dispatch_preview)
        self.image_canvas.point_picked.connect(self.pick_neutral)
        self.image_canvas.selection_finished.connect(self.crop_selected)
        self.image_canvas.stroke_finished.connect(self.add_stroke)
        self.image_canvas.erase_requested.connect(self.erase_at)
        self.image_canvas.text_requested.connect(self.add_text_at)
        self.image_canvas.markup_moved.connect(self._sync_text_positions)
        self.slider_rows["pen_size"].value_changed.connect(self._update_pen_style)
        self._update_pen_style()
        for row in self.slider_rows.values():
            row.slider.sliderPressed.connect(self._slider_pressed)
            row.slider.sliderReleased.connect(self._slider_released)
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        # Keep the new layout intact: the two compact buttons live in its toolbar.
        toolbar = self.filename_label.parentWidget().layout()
        toolbar.insertWidget(2, self.undo_button)
        toolbar.insertWidget(3, self.redo_button)
        for sequence, action in (("Ctrl+O", self.load_image), ("Ctrl+S", self.save_image),
                                 ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo),
                                 ("Ctrl+Shift+Z", self.redo)):
            QShortcut(QKeySequence(sequence), self).activated.connect(action)
        self._load_presets()

    @staticmethod
    def to_qimage(image: Image.Image) -> QImage:
        image = image.convert("RGBA" if image.mode == "RGBA" else "RGB")
        data = image.tobytes()
        fmt = QImage.Format.Format_RGBA8888 if image.mode == "RGBA" else QImage.Format.Format_RGB888
        return QImage(data, image.width, image.height, image.width * len(image.getbands()), fmt).copy()

    @staticmethod
    def _default_state():
        return {"red": 0, "green": 0, "blue": 0, "saturation": 0,
                "brightness": 0, "exposure": 0, "contrast": 0,
                "highlights": 0, "shadows": 0, "neutral_gains": [1.0, 1.0, 1.0],
                "crop": None, "strokes": [], "texts": [],
                "lut_path": None, "lut_intensity": 100}

    @staticmethod
    def _app_dir():
        path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _history(self):
        self._sync_text_positions()
        self.undo_stack.append(copy.deepcopy(self.state))
        self.undo_stack = self.undo_stack[-40:]
        self.redo_stack.clear()
        self.undo_button.setEnabled(True)
        self.redo_button.setEnabled(False)

    def _slider_pressed(self):
        self._history()
        self._slider_drag = True

    def _slider_released(self):
        self._slider_drag = False

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.state))
            self._restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.state))
            self._restore(self.redo_stack.pop())

    def _restore(self, state):
        self.state = copy.deepcopy(state)
        self.lut = load_cube(state["lut_path"]) if state.get("lut_path") and Path(state["lut_path"]).exists() else None
        self.loaded_lut_label.setText(Path(state["lut_path"]).name if self.lut else "No LUT loaded")
        for key, row in self.slider_rows.items():
            if key in ("red", "green", "blue"):
                gain = self.state["neutral_gains"][("red", "green", "blue").index(key)]
                value = round(((1 + self.state[key] / 100) * gain - 1) * 100)
            elif key == "exposure":
                value = round(self.state["exposure"] / 2)
            else:
                value = self.state.get(key, row.baseline)
            row.set_value_silently(value)
        self._refresh_text_items()
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))
        self.refresh_preview()

    def on_adjustment_changed(self, key: str, value: int) -> None:
        if not self._slider_drag:
            self._history()
        if key in ("red", "green", "blue"):
            gain = self.state["neutral_gains"][("red", "green", "blue").index(key)]
            self.state[key] = max(-100, min(100, round(((1 + value / 100) / gain - 1) * 100)))
        elif key == "exposure":
            self.state[key] = value * 2  # ±100 on the v2 slider remains ±2 EV.
        elif key not in ("font_size", "pen_size"):
            self.state[key] = value
        if key == "font_size" and self._text_items:
            index = self._selected_text_index()
            self.state["texts"][index]["size"] = value
            self._refresh_text_items()
        if key == "pen_size":
            self._update_pen_style()
        self.adjustments_changed.emit(self.current_adjustments())
        if key not in ("font_size", "pen_size"):
            self.refresh_preview()

    def reset_all_adjustments(self) -> None:
        self._history()
        for key, row in self.slider_rows.items():
            row.set_value_silently(row.baseline)
            if key not in ("font_size", "pen_size", "lut_intensity"):
                self.state[key] = 0
        self.state["neutral_gains"] = [1.0, 1.0, 1.0]
        self.state["lut_intensity"] = 100
        self.state["lut_path"] = None
        self.lut = None
        self.loaded_lut_label.setText("No LUT loaded")
        self.refresh_preview()

    def refresh_preview(self) -> None:
        if self.source_image is not None:
            self._render_generation += 1
            self.preview_timer.start(65)

    def _dispatch_preview(self):
        if self.source_image is None or self._render_running:
            return
        self._render_running = True
        task = PreviewTask(self._render_generation, self.source_image,
                           copy.deepcopy(self.state), self.lut)
        task.signals.finished.connect(self._preview_finished)
        task.signals.failed.connect(self._preview_failed)
        self._current_task = task
        self.pool.start(task)

    def _preview_finished(self, generation, image, bounds):
        self._render_running = False
        self._current_task = None
        if generation != self._render_generation:
            self._dispatch_preview()
            return
        self._preview_scale = image.width / (bounds[2] - bounds[0])
        self.image_canvas.set_pixmap(QPixmap.fromImage(self.to_qimage(image)))
        self.rgb_parade_scope.update_parade(image)
        self._refresh_text_items()

    def _preview_failed(self, generation, message):
        self._render_running = False
        self._current_task = None
        if generation == self._render_generation:
            QMessageBox.warning(self, "Preview error", message)
        else:
            self._dispatch_preview()

    def load_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open image", "", "Images (*.jpg *.jpeg *.png)")
        if not path:
            return
        try:
            image = load_photo(path)
            self.source_image = image
            self.source_path = path
            self.state = self._default_state()
            self.lut = None
            self._selected_crop = None
            self.undo_stack.clear()
            self.redo_stack.clear()
            self._restore(self.state)
            preview = render(image, self.state, None, max_side=2048)
            self._preview_scale = preview.width / image.width
            self.image_canvas.set_pixmap(QPixmap.fromImage(self.to_qimage(preview)))
            self.image_canvas.fit_to_window()
            self.rgb_parade_scope.update_parade(preview)
            self.filename_label.setText(Path(path).name)
            self.statusBar().showMessage(f"Loaded {Path(path).name} ({image.width} × {image.height})")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Could not open image", str(exc))

    def save_image(self) -> None:
        if self.source_image is None:
            return
        self._sync_text_positions()
        suggested = str(Path(self.source_path).with_name(Path(self.source_path).stem + "-edited.png"))
        path, _ = QFileDialog.getSaveFileName(self, "Export edited image", suggested,
                                               "PNG image (*.png);;JPEG image (*.jpg)")
        if not path:
            return
        if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg"):
            path += ".png"
        if Path(path).resolve() == Path(self.source_path).resolve():
            QMessageBox.warning(self, "Choose another filename", "Save an edited copy to preserve the original.")
            return
        self.statusBar().showMessage("Exporting full-resolution image…")
        self.save_image_button.setEnabled(False)
        task = ExportTask(self.source_image, copy.deepcopy(self.state), self.lut, path)
        task.signals.done.connect(self._export_finished)
        self._export_task = task
        self.pool.start(task)

    def _export_finished(self, path, error):
        self._export_task = None
        self.save_image_button.setEnabled(True)
        if error:
            QMessageBox.critical(self, "Export failed", error)
        else:
            self.statusBar().showMessage(f"Saved {Path(path).name}")

    def _activate_tool(self, button, mode):
        if button.isChecked() and self.source_image is None:
            button.setChecked(False)
            return
        if button.isChecked():
            for other in (self.crop_tool_toggle, self.white_balance_eyedropper_toggle,
                          self.add_text_toggle, self.draw_pen_tool_toggle,
                          self.eraser_tool_toggle):
                if other is not button and other.isChecked():
                    other.blockSignals(True)
                    other.setChecked(False)
                    other.blockSignals(False)
            self.image_canvas.set_mode(mode)
        elif self.image_canvas.mode == mode:
            self.image_canvas.set_mode("pan")

    def on_crop_tool_toggled(self, checked: bool) -> None:
        self._selected_crop = None
        self.crop_apply_button.setEnabled(False)
        if checked:
            self.image_canvas.selection_item.hide()
        self._activate_tool(self.crop_tool_toggle, "crop")
        if checked:
            self.statusBar().showMessage("Drag on the photo, then click Apply Crop.")

    def crop_selected(self, rect):
        self._selected_crop = rect
        self.crop_apply_button.setEnabled(rect.width() >= 5 and rect.height() >= 5)

    def apply_crop(self):
        if self.source_image is None or self._selected_crop is None:
            return
        left, top, right, bottom = crop_bounds(self.source_image, self.state["crop"])
        r = self._selected_crop
        bounds = (max(left, left + r.left() / self._preview_scale),
                  max(top, top + r.top() / self._preview_scale),
                  min(right, left + r.right() / self._preview_scale),
                  min(bottom, top + r.bottom() / self._preview_scale))
        choice = self.crop_ratio_combo.currentText()
        ratios = {"Original": (right - left) / (bottom - top),
                  "1:1": 1, "4:3": 4 / 3, "16:9": 16 / 9}
        if choice in ratios:
            target = ratios[choice]
            x0, y0, x1, y1 = bounds
            width, height = x1 - x0, y1 - y0
            if width / height > target:
                trim = (width - height * target) / 2
                x0, x1 = x0 + trim, x1 - trim
            else:
                trim = (height - width / target) / 2
                y0, y1 = y0 + trim, y1 - trim
            bounds = (x0, y0, x1, y1)
        exact = {"1:1": (1, 1), "4:3": (4, 3), "16:9": (16, 9)}
        if choice in exact:
            a, b = exact[choice]
            unit = max(1, min(int((bounds[2] - bounds[0]) / a),
                              int((bounds[3] - bounds[1]) / b)))
            width, height = a * unit, b * unit
            cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
            x0 = max(left, min(right - width, round(cx - width / 2)))
            y0 = max(top, min(bottom - height, round(cy - height / 2)))
            bounds = (x0, y0, x0 + width, y0 + height)
        if bounds[2] - bounds[0] < 2 or bounds[3] - bounds[1] < 2:
            return
        self._history()
        self.state["crop"] = bounds
        self.crop_tool_toggle.setChecked(False)
        self._selected_crop = None
        self.crop_apply_button.setEnabled(False)
        self.refresh_preview()

    def reset_crop(self):
        if self.state["crop"] is not None:
            self._history()
            self.state["crop"] = None
            self.refresh_preview()
        self.crop_tool_toggle.setChecked(False)
        self.image_canvas.set_mode("pan")
        self._selected_crop = None
        self.crop_apply_button.setEnabled(False)

    def on_white_balance_eyedropper_toggled(self, checked: bool) -> None:
        self._activate_tool(self.white_balance_eyedropper_toggle, "pick")
        if checked:
            self.statusBar().showMessage("Click a white or neutral gray area with detail.")

    def pick_neutral(self, x, y):
        if self.source_image is None:
            return
        left, top, _, _ = crop_bounds(self.source_image, self.state["crop"])
        try:
            gains = neutral_gains(self.source_image,
                                  left + x / self._preview_scale,
                                  top + y / self._preview_scale)
        except ValueError as exc:
            QMessageBox.information(self, "Choose another area", str(exc))
            return
        self._history()
        self.state["neutral_gains"] = gains
        self._sync_rgb_sliders()
        self.white_balance_eyedropper_toggle.setChecked(False)
        self.refresh_preview()

    def _sync_rgb_sliders(self):
        for index, key in enumerate(("red", "green", "blue")):
            gain = self.state["neutral_gains"][index]
            combined = (1 + self.state[key] / 100) * gain
            self.slider_rows[key].set_value_silently(
                max(-100, min(100, round((combined - 1) * 100))))

    def clear_white_balance_sample(self):
        if all(abs(gain - 1) < 1e-6 for gain in self.state["neutral_gains"]):
            return
        self._history()
        self.state["neutral_gains"] = [1.0, 1.0, 1.0]
        self._sync_rgb_sliders()
        self.refresh_preview()

    def on_draw_pen_tool_toggled(self, checked: bool) -> None:
        self._activate_tool(self.draw_pen_tool_toggle, "pen")

    def _update_pen_style(self, *_):
        self.image_canvas.pen_width = self.slider_rows["pen_size"].value()
        self.image_canvas.pen_color = QColor({"Red": "#f16a6a", "White": "white",
                                              "Black": "black"}[self.pen_color_combo.currentText()])

    def add_stroke(self, points):
        if not points or self.source_image is None:
            return
        left, top, _, _ = crop_bounds(self.source_image, self.state["crop"])
        self._history()
        self.state["strokes"].append({
            "points": [[left + x / self._preview_scale, top + y / self._preview_scale]
                       for x, y in points],
            "width": self.slider_rows["pen_size"].value() / self._preview_scale,
            "color": {"Red": "#f16a6a", "White": "white", "Black": "black"}[
                self.pen_color_combo.currentText()],
        })
        self.refresh_preview()

    def on_add_text_toggled(self, checked: bool) -> None:
        self._activate_tool(self.add_text_toggle, "text")
        if checked:
            self.statusBar().showMessage("Type text, then click the photo to place it. Drag to move.")

    def _selected_text_index(self):
        for index, item in enumerate(self._text_items):
            if item.isSelected():
                return index
        return len(self._text_items) - 1

    def _sync_text_positions(self):
        if self.source_image is None or not self._text_items:
            return
        left, top, _, _ = crop_bounds(self.source_image, self.state["crop"])
        for index, item in enumerate(self._text_items):
            if index < len(self.state["texts"]):
                self.state["texts"][index]["x"] = left + item.x() / self._preview_scale
                self.state["texts"][index]["y"] = top + item.y() / self._preview_scale

    def _refresh_text_items(self):
        if self.source_image is None:
            return
        left, top, right, bottom = crop_bounds(self.source_image, self.state["crop"])
        scene = self.image_canvas._scene
        while len(self._text_items) > len(self.state["texts"]):
            item = self._text_items.pop()
            scene.removeItem(item)
        while len(self._text_items) < len(self.state["texts"]):
            item = QGraphicsTextItem()
            item.setDefaultTextColor(QColor("white"))
            item.setZValue(4)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            scene.addItem(item)
            self._text_items.append(item)
        for item, data in zip(self._text_items, self.state["texts"]):
            font = QFont("Segoe UI")
            font.setPixelSize(max(1, round(data["size"] * self._preview_scale)))
            item.setFont(font)
            item.setPlainText(data["text"])
            item.setPos((data["x"] - left) * self._preview_scale,
                        (data["y"] - top) * self._preview_scale)
            item.setVisible(left <= data["x"] < right and top <= data["y"] < bottom)

    def add_text_at(self, x, y):
        content = self.markup_text_input.text().strip()
        if not content or self.source_image is None:
            self.statusBar().showMessage("Type text before placing it on the photo.")
            return
        left, top, _, _ = crop_bounds(self.source_image, self.state["crop"])
        self._history()
        self.state["texts"].append({"text": content, "x": left + x / self._preview_scale,
                                    "y": top + y / self._preview_scale,
                                    "size": self.slider_rows["font_size"].value()})
        self._refresh_text_items()
        self._text_items[-1].setSelected(True)

    def on_markup_text_changed(self, text: str) -> None:
        if self.state["texts"] and self._text_items:
            index = self._selected_text_index()
            if self.state["texts"][index]["text"] != text:
                self._history()
                self.state["texts"][index]["text"] = text
                self._refresh_text_items()

    def on_eraser_tool_toggled(self, checked: bool) -> None:
        self._activate_tool(self.eraser_tool_toggle, "erase")
        if checked:
            self.statusBar().showMessage("Click a pen stroke or text item to erase it.")

    @staticmethod
    def _distance_to_segment(x, y, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        fraction = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) /
                              (dx * dx + dy * dy))) if dx or dy else 0
        return math.hypot(x - (ax + fraction * dx), y - (ay + fraction * dy))

    def erase_at(self, x, y):
        for index in range(len(self._text_items) - 1, -1, -1):
            if self._text_items[index].isVisible() and self._text_items[index].sceneBoundingRect().contains(x, y):
                self._history()
                del self.state["texts"][index]
                self._refresh_text_items()
                return
        if self.source_image is None:
            return
        left, top, _, _ = crop_bounds(self.source_image, self.state["crop"])
        nearest = (float("inf"), None)
        for index, stroke in enumerate(self.state["strokes"]):
            points = [((px - left) * self._preview_scale, (py - top) * self._preview_scale)
                      for px, py in stroke["points"]]
            segments = list(zip(points, points[1:])) or [(points[0], points[0])]
            distance = min(self._distance_to_segment(x, y, *a, *b) for a, b in segments)
            if distance < max(10, stroke["width"] * self._preview_scale / 2 + 6) and distance < nearest[0]:
                nearest = (distance, index)
        if nearest[1] is not None:
            self._history()
            del self.state["strokes"][nearest[1]]
            self.refresh_preview()

    def clear_markup(self):
        if self.state["strokes"] or self.state["texts"]:
            self._history()
            self.state["strokes"] = []
            self.state["texts"] = []
            self._refresh_text_items()
            self.refresh_preview()

    def load_lut_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load 3D .cube LUT", "", "3D LUT (*.cube)")
        if not path:
            return
        try:
            lut = load_cube(path)
            store = self._app_dir() / "luts"
            store.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
            saved = store / f"{Path(path).stem}-{digest}.cube"
            if Path(path).resolve() != saved.resolve():
                shutil.copyfile(path, saved)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "LUT could not be loaded", str(exc))
            return
        self._history()
        self.state["lut_path"] = str(saved)
        self.lut = lut
        self.loaded_lut_label.setText(Path(path).name)
        self.refresh_preview()

    def clear_lut(self):
        if self.state["lut_path"]:
            self._history()
            self.state["lut_path"] = None
            self.lut = None
            self.loaded_lut_label.setText("No LUT loaded")
            self.refresh_preview()

    def _preset_root(self):
        root = self._app_dir() / ".presets"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _preset_id(name):
        return hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:20]

    def _write_preset(self, name, adjustments, gains, lut_path):
        root = self._preset_root()
        relative_lut = None
        if lut_path:
            target = root / "luts" / f"{self._preset_id(name)}.cube"
            target.parent.mkdir(parents=True, exist_ok=True)
            if Path(lut_path).resolve() != target.resolve():
                shutil.copyfile(lut_path, target)
            relative_lut = str(target.relative_to(root)).replace("\\", "/")
        payload = {"schema_version": 2, "name": name,
                   "adjustments": adjustments,
                   "white_balance": {"gains": list(gains)},
                   "lut": {"relative_path": relative_lut} if relative_lut else None}
        destination = root / f"{self._preset_id(name)}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(destination)
        return payload

    def _load_presets(self):
        root = self._preset_root()
        self.presets = {}
        for path in root.glob("*.json"):
            try:
                preset = json.loads(path.read_text(encoding="utf-8"))
                if preset.get("schema_version") == 2 and preset.get("name"):
                    self.presets[preset["name"]] = preset
            except (OSError, ValueError, AttributeError):
                continue
        if not self.presets:
            self._migrate_v1_presets()
        current = self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("— No preset —")
        self.preset_combo.addItems(sorted(self.presets, key=str.casefold))
        self.preset_combo.setCurrentText(current if current in self.presets else "— No preset —")
        self.preset_combo.blockSignals(False)

    def _migrate_v1_presets(self):
        previous = self._app_dir() / "presets.json"
        if not previous.exists():
            return
        try:
            entries = json.loads(previous.read_text(encoding="utf-8"))
            for name, values in entries.items():
                if not isinstance(values, dict):
                    continue
                adjustments = {key: row.baseline for key, row in self.slider_rows.items()}
                gains = values.get("neutral_gains", [1, 1, 1])
                for key in adjustments:
                    if key in ("red", "green", "blue"):
                        i = ("red", "green", "blue").index(key)
                        adjustments[key] = max(-100, min(100, round(
                            ((1 + values.get(key, 0) / 100) * gains[i] - 1) * 100)))
                    elif key == "exposure":
                        adjustments[key] = round(values.get(key, 0) / 2)
                    elif key in values:
                        adjustments[key] = values[key]
                lut_path = values.get("lut_path")
                payload = self._write_preset(name, adjustments, gains,
                                             lut_path if lut_path and Path(lut_path).exists() else None)
                self.presets[name] = payload
        except (OSError, ValueError, TypeError, AttributeError, IndexError):
            self.statusBar().showMessage("Could not import an older preset; v1 presets remain available in their original file.")

    def save_current_as_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save color preset", "Preset name:")
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.presets and QMessageBox.question(
                self, "Replace preset", f'Replace "{name}"?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.presets[name] = self._write_preset(
                name, self.current_adjustments(), self.state["neutral_gains"],
                self.state["lut_path"])
            self._load_presets()
            self.preset_combo.setCurrentText(name)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Preset not saved", str(exc))

    def delete_selected_preset(self) -> None:
        name = self.preset_combo.currentText()
        if name not in self.presets:
            return
        if QMessageBox.question(self, "Delete preset", f'Delete "{name}"?') != QMessageBox.StandardButton.Yes:
            return
        payload = self.presets[name]
        try:
            (self._preset_root() / f"{self._preset_id(name)}.json").unlink()
            relative = (payload.get("lut") or {}).get("relative_path")
            if relative and not any(
                    (other.get("lut") or {}).get("relative_path") == relative
                    for other_name, other in self.presets.items() if other_name != name):
                (self._preset_root() / relative).unlink(missing_ok=True)
            del self.presets[name]
            self._load_presets()
        except OSError as exc:
            QMessageBox.critical(self, "Preset not deleted", str(exc))

    def apply_preset(self, preset_name: str) -> None:
        if preset_name not in getattr(self, "presets", {}):
            return
        preset = self.presets[preset_name]
        values = preset.get("adjustments", {})
        gains = preset.get("white_balance", {}).get("gains", [1, 1, 1])
        relative = (preset.get("lut") or {}).get("relative_path")
        path = self._preset_root() / relative if relative else None
        try:
            lut = load_cube(str(path)) if path else None
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Preset LUT unavailable", str(exc))
            return
        self._history()
        self.state["neutral_gains"] = list(gains)
        for key, row in self.slider_rows.items():
            value = max(row.slider.minimum(), min(row.slider.maximum(), int(values.get(key, row.baseline))))
            row.set_value_silently(value)
            if key in ("red", "green", "blue"):
                gain = gains[("red", "green", "blue").index(key)]
                self.state[key] = max(-100, min(100, round(((1 + value / 100) / gain - 1) * 100)))
            elif key == "exposure":
                self.state[key] = value * 2
            elif key not in ("font_size", "pen_size"):
                self.state[key] = value
        self.state["lut_path"] = str(path) if path else None
        self.lut = lut
        self.loaded_lut_label.setText(path.name if path else "No LUT loaded")
        self._update_pen_style()
        self.refresh_preview()


def main() -> int:
    def report_exception(exception_type, exception, tb):
        startup_stage("Uncaught exception")
        if _STARTUP_LOG is not None:
            traceback.print_exception(exception_type, exception, tb, file=_STARTUP_LOG)
        sys.__excepthook__(exception_type, exception, tb)

    sys.excepthook = report_exception
    startup_stage("Creating Qt application")
    app = QApplication(sys.argv)
    app.setApplicationName("Lumen")
    app.setOrganizationName("Lumen")
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    startup_stage("Building main window")
    window = ImageEditorWindow()
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        window.resize(min(window.width(), available.width()),
                      min(window.height(), available.height()))
        window.move(available.center() - window.rect().center())
        startup_stage(f"Primary screen {available.width()}x{available.height()}, "
                      f"window {window.width()}x{window.height()} at "
                      f"{window.x()},{window.y()}")
    startup_stage("Showing main window")
    window.show()
    window.raise_()
    window.activateWindow()
    def first_event():
        startup_stage("Qt event loop responding")
        if _STARTUP_LOG is not None:
            faulthandler.cancel_dump_traceback_later()

    QTimer.singleShot(0, first_event)
    def inspect_window():
        startup_stage(f"Window visible={window.isVisible()} "
                      f"minimized={window.isMinimized()} "
                      f"active={window.isActiveWindow()} "
                      f"geometry={window.geometry().getRect()}")
        current_screen = window.screen()
        if current_screen is not None:
            try:
                snapshot = current_screen.grabWindow(int(window.winId()))
                if snapshot.isNull():
                    startup_stage("Window capture was empty")
                else:
                    snapshot_path = Path(tempfile.gettempdir()) / "Lumen-window.png"
                    snapshot.save(str(snapshot_path), "PNG")
                    sample = snapshot.toImage().scaled(80, 60)
                    dark = sum(max(sample.pixelColor(x, y).red(),
                                   sample.pixelColor(x, y).green(),
                                   sample.pixelColor(x, y).blue()) < 130
                               for y in range(sample.height()) for x in range(sample.width()))
                    startup_stage(f"Window capture {snapshot.width()}x{snapshot.height()}, "
                                  f"dark pixels {dark / 4800:.0%}; saved Lumen-window.png")
            except Exception as exc:
                startup_stage(f"Window capture failed: {type(exc).__name__}: {exc}")

    QTimer.singleShot(2000, inspect_window)
    startup_stage("Starting Qt event loop")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
