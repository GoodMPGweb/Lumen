"""
Lumen — lightweight single-window image editor UI (PyQt6, Windows 11 Fluent-inspired).

Run:  pip install -r requirements.txt  &&  python image_editor_ui.py
"""
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from processing import crop_bounds, load_cube, load_photo, neutral_gains, parade, render

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QTimer, QStandardPaths, QPointF, QObject, QRunnable, QThreadPool
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap,
                         QImage, QPainterPath, QShortcut, QKeySequence)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsPathItem, QGraphicsTextItem, QGraphicsScene, QGraphicsDropShadowEffect,
    QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget, QFileDialog, QMessageBox,
    QInputDialog, QGraphicsItem,
)

ACCENT = "#0067C0"

STYLESHEET = f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; color: #1B1B1B; }}
QMainWindow, #rootWidget {{ background: #F3F3F3; }}
#canvasView {{ background: #E9E9E9; border: none; border-top-right-radius: 8px; }}
#controlPanel {{ background: #F9F9F9; border-left: 1px solid #E5E5E5; }}
#panelScroll, #panelScroll > QWidget > QWidget {{ background: transparent; border: none; }}
#topBar {{ background: #F3F3F3; }}
#appTitle {{ font-weight: 600; }}
#zoomLabel {{ color: #5F5F5F; }}

QFrame#sectionCard {{ background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 8px; }}
QLabel#sectionTitle {{ font-weight: 600; font-size: 10pt; }}
QLabel#valueLabel {{ color: #5F5F5F; min-width: 34px; }}
QLabel#channelLabel {{ min-width: 46px; }}

QPushButton {{
    background: #FFFFFF; border: 1px solid #E0E0E0; border-bottom-color: #CFCFCF;
    border-radius: 4px; padding: 6px 12px;
}}
QPushButton:hover {{ background: #F6F6F6; }}
QPushButton:pressed {{ background: #F0F0F0; color: #5F5F5F; }}
QPushButton:disabled {{ color: #A0A0A0; background: #F5F5F5; border-color: #E5E5E5; }}
QPushButton#accentButton:disabled {{ background: #C8C8C8; color: #FFFFFF; border-color: #C8C8C8; }}
QPushButton#accentButton {{ background: {ACCENT}; color: #FFFFFF; border: 1px solid #005BAA; }}
QPushButton#accentButton:hover {{ background: #1975C5; }}
QPushButton#accentButton:pressed {{ background: #3183CA; }}
QPushButton#subtleButton {{ background: transparent; border: none; padding: 6px 8px; }}
QPushButton#subtleButton:hover {{ background: rgba(0,0,0,0.05); }}

QComboBox, QLineEdit {{
    background: #FFFFFF; border: 1px solid #E0E0E0; border-bottom: 1px solid #8A8A8A;
    border-radius: 4px; padding: 5px 8px;
}}
QComboBox:focus, QLineEdit:focus {{ border-bottom: 2px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QAbstractItemView {{ background: #FFFFFF; color: #1B1B1B; border: 1px solid #D0D0D0;
    selection-background-color: {ACCENT}; selection-color: #FFFFFF; outline: 0; }}

QSlider::groove:horizontal {{ height: 4px; background: #C4C4C4; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #FFFFFF; border: 5px solid {ACCENT}; width: 8px; height: 8px;
    margin: -7px 0; border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ border-width: 4px; width: 10px; height: 10px; }}
QSlider#redSlider::sub-page:horizontal {{ background: #C42B1C; }}
QSlider#redSlider::handle:horizontal {{ border-color: #C42B1C; }}
QSlider#greenSlider::sub-page:horizontal {{ background: #0F7B0F; }}
QSlider#greenSlider::handle:horizontal {{ border-color: #0F7B0F; }}
QSlider#blueSlider::sub-page:horizontal {{ background: #0067C0; }}
QSlider#blueSlider::handle:horizontal {{ border-color: #0067C0; }}

QCheckBox::indicator {{ width: 36px; height: 18px; border-radius: 9px; border: 1px solid #8A8A8A; background: #FFFFFF; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QScrollBar:vertical {{ width: 6px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #C4C4C4; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


class ImageCanvas(QGraphicsView):
    """Central canvas: wheel = zoom (anchored under cursor), drag = pan."""

    zoom_changed = pyqtSignal(float)
    point_picked = pyqtSignal(float, float)
    stroke_finished = pyqtSignal(object)
    selection_finished = pyqtSignal(object)

    ZOOM_STEP = 1.15
    ZOOM_MIN, ZOOM_MAX = 0.05, 32.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("canvasView")
        self.canvas_scene = QGraphicsScene(self)
        self.image_item = QGraphicsPixmapItem()
        self.image_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.canvas_scene.addItem(self.image_item)
        self.setScene(self.canvas_scene)

        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.current_zoom = 1.0
        self.mode = "pan"
        self.pen_color = QColor("#D12222")
        self.pen_width = 4
        self._start = None
        self._points = []
        self._live_path = None
        self.selection_item = QGraphicsRectItem()
        self.selection_item.setPen(QPen(QColor("#FFFFFF"), 1, Qt.PenStyle.DashLine))
        self.selection_item.setBrush(QColor(0, 103, 192, 35))
        self.selection_item.setZValue(3)
        self.canvas_scene.addItem(self.selection_item)
        self.selection_item.hide()

    def set_pixmap(self, pixmap: QPixmap, fit: bool = False):
        was_empty = self.image_item.pixmap().isNull()
        self.image_item.setPixmap(pixmap)
        self.canvas_scene.setSceneRect(QRectF(pixmap.rect()))
        if fit or was_empty:
            self.fit_to_window()

    def set_mode(self, mode: str):
        self.mode = mode
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if mode == "pan"
                         else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if mode in ("pick", "crop")
                                  else Qt.CursorShape.ArrowCursor)
        if mode != "crop":
            self.selection_item.hide()

    def _image_point(self, event):
        point = self.mapToScene(event.position().toPoint())
        rect = self.image_item.boundingRect()
        return rect, point

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.mode in ("pick", "crop", "pen"):
            rect, point = self._image_point(event)
            if not rect.contains(point):
                return
            if self.mode == "pick":
                self.point_picked.emit(point.x(), point.y())
                self.set_mode("pan")
            elif self.mode == "crop":
                self._start = point
                self.selection_item.setRect(QRectF(point, point))
                self.selection_item.show()
            else:
                self._points = [(point.x(), point.y())]
                path = QPainterPath(point)
                self._live_path = QGraphicsPathItem(path)
                self._live_path.setPen(QPen(self.pen_color, self.pen_width))
                self._live_path.setZValue(4)
                self.canvas_scene.addItem(self._live_path)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is not None and self.mode == "crop":
            rect, point = self._image_point(event)
            point.setX(max(0, min(rect.width(), point.x())))
            point.setY(max(0, min(rect.height(), point.y())))
            self.selection_item.setRect(QRectF(self._start, point).normalized())
            return
        if self._live_path is not None and self.mode == "pen":
            rect, point = self._image_point(event)
            point.setX(max(0, min(rect.width(), point.x())))
            point.setY(max(0, min(rect.height(), point.y())))
            self._points.append((point.x(), point.y()))
            path = self._live_path.path()
            path.lineTo(point)
            self._live_path.setPath(path)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._start is not None:
            self._start = None
            self.selection_finished.emit(self.selection_item.rect())
            return
        if self._live_path is not None:
            self.canvas_scene.removeItem(self._live_path)
            self._live_path = None
            self.stroke_finished.emit(self._points)
            self._points = []
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.angleDelta().y() == 0:
            return super().wheelEvent(event)
        factor = self.ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self.ZOOM_STEP
        new_zoom = self.current_zoom * factor
        if self.ZOOM_MIN <= new_zoom <= self.ZOOM_MAX:
            self.scale(factor, factor)
            self.current_zoom = new_zoom
            self.zoom_changed.emit(self.current_zoom)

    def fit_to_window(self):
        if self.image_item.pixmap().isNull():
            return
        self.fitInView(self.image_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.current_zoom = self.transform().m11()
        self.zoom_changed.emit(self.current_zoom)

    def reset_zoom(self):
        self.resetTransform()
        self.current_zoom = 1.0
        self.zoom_changed.emit(self.current_zoom)


class RGBParadeScope(QWidget):
    """Three side-by-side columns (R | G | B). Feed data via set_parade_data()."""

    CHANNEL_COLORS = (QColor(232, 72, 60, 150), QColor(70, 200, 90, 150), QColor(70, 140, 255, 150))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rgbParadeScope")
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.parade_data = None  # placeholder: per-channel 2D density arrays

    def set_parade_data(self, data):
        """Receive RGB density arrays, with row zero representing the brightest values."""
        self.parade_data = data
        self.parade_images = []
        if data is not None:
            for density, color in zip(data, self.CHANNEL_COLORS):
                height, width = density.shape
                rgba = np.zeros((height, width, 4), dtype=np.uint8)
                rgba[..., 0:3] = (color.red(), color.green(), color.blue())
                rgba[..., 3] = np.uint8(np.clip(density ** 0.65 * 255, 0, 255))
                self.parade_images.append(QImage(rgba.tobytes(), width, height, width * 4,
                                                QImage.Format.Format_RGBA8888).copy())
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1C1C1C"))
        p.drawRoundedRect(r, 6, 6)

        pad, gap = 8, 6
        col_w = (r.width() - pad * 2 - gap * 2) / 3
        top, bottom = r.top() + pad, r.bottom() - pad - 14
        for i, color in enumerate(self.CHANNEL_COLORS):
            x = r.left() + pad + i * (col_w + gap)
            col = QRectF(x, top, col_w, bottom - top)
            p.setBrush(QColor(255, 255, 255, 8))
            p.drawRect(col)
            p.setPen(QPen(QColor(255, 255, 255, 28), 1, Qt.PenStyle.DotLine))
            for q in (0.25, 0.5, 0.75):
                y = col.top() + col.height() * q
                p.drawLine(int(col.left()), int(y), int(col.right()), int(y))
            if self.parade_data is not None:
                p.drawImage(col, self.parade_images[i])
            # Show the waveform limits so values pinned to either edge are clear.
            p.setPen(QPen(QColor(255, 255, 255, 210), 1))
            p.drawLine(int(col.left()), int(col.top()), int(col.right()), int(col.top()))
            p.drawLine(int(col.left()), int(col.bottom()), int(col.right()), int(col.bottom()))
            p.setPen(color.lighter(130))
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(QRectF(x, bottom + 2, col_w, 12), Qt.AlignmentFlag.AlignCenter, "RGB"[i])
            p.setPen(Qt.PenStyle.NoPen)
        if self.parade_data is None:
            p.setPen(QColor(255, 255, 255, 90))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "No image loaded")
        p.end()


class SectionCard(QFrame):
    """Rounded Fluent-style card with a title row and body layout."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sectionCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)
        self.header_layout = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()
        outer.addLayout(self.header_layout)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)


class LabeledSlider(QWidget):
    """Label | slider | value readout. Double-click the readout to reset."""

    value_changed = pyqtSignal(int)

    def __init__(self, label, minimum, maximum, default, slider_name, suffix="", parent=None,
                 formatter=None):
        super().__init__(parent)
        self.default_value, self.suffix = default, suffix
        self.formatter = formatter
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.name_label = QLabel(label)
        self.name_label.setObjectName("channelLabel")
        self.name_label.setFixedWidth(88)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName(slider_name)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(default)
        self.value_label = QLabel()
        self.value_label.setObjectName("valueLabel")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setFixedWidth(64)
        self.value_label.mouseDoubleClickEvent = lambda e: self.reset()
        row.addWidget(self.name_label)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._on_value)
        self._on_value(default)

    def _on_value(self, v):
        self.value_label.setText(self._formatted_value(v))
        self.value_changed.emit(v)

    def _formatted_value(self, v):
        sign = "+" if v > 0 and self.slider.minimum() < 0 else ""
        return self.formatter(v) if self.formatter else f"{sign}{v}{self.suffix}"

    def set_value_silently(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.value_label.setText(self._formatted_value(self.slider.value()))

    def value(self):
        return self.slider.value()

    def reset(self):
        self.slider.setValue(self.default_value)


class ControlPanel(QWidget):
    """Right-side panel. Exposes all controls as attributes + high-level signals."""

    load_image_requested = pyqtSignal()
    save_image_requested = pyqtSignal()
    rgb_channels_changed = pyqtSignal(int, int, int)
    preset_selected = pyqtSignal(str)
    save_preset_requested = pyqtSignal()
    delete_preset_requested = pyqtSignal()
    load_lut_requested = pyqtSignal()
    lut_intensity_changed = pyqtSignal(int)
    text_markup_toggled = pyqtSignal(bool)
    text_font_size_changed = pyqtSignal(int)
    text_content_changed = pyqtSignal(str)
    saturation_changed = pyqtSignal(int)
    tone_changed = pyqtSignal()
    pick_neutral_requested = pyqtSignal()
    reset_neutral_requested = pyqtSignal()
    reset_color_requested = pyqtSignal()
    crop_requested = pyqtSignal()
    crop_apply_requested = pyqtSignal()
    crop_reset_requested = pyqtSignal()
    pen_toggled = pyqtSignal(bool)

    PANEL_WIDTH = 340

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlPanel")
        self.setFixedWidth(self.PANEL_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("panelScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        content = QWidget()
        self.panel_layout = QVBoxLayout(content)
        self.panel_layout.setContentsMargins(14, 14, 14, 14)
        self.panel_layout.setSpacing(10)
        scroll.setWidget(content)

        self._build_file_section()
        self._build_scope_section()
        self._build_tone_section()
        self._build_rgb_section()
        self._build_crop_section()
        self._build_preset_section()
        self._build_lut_section()
        self._build_pen_section()
        self._build_text_section()
        self.panel_layout.addStretch()
        self._connect_signals()

    def _build_file_section(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.load_image_button = QPushButton("Load Image")
        self.save_image_button = QPushButton("Save Image")
        self.save_image_button.setObjectName("accentButton")
        row.addWidget(self.load_image_button, 1)
        row.addWidget(self.save_image_button, 1)
        self.panel_layout.addLayout(row)

    def _build_scope_section(self):
        card = SectionCard("RGB Parade")
        self.parade_live_label = QLabel("Live")
        self.parade_live_label.setObjectName("valueLabel")
        card.header_layout.addWidget(self.parade_live_label)
        self.rgb_parade_scope = RGBParadeScope()
        card.body.addWidget(self.rgb_parade_scope)
        self.panel_layout.addWidget(card)

    def _build_rgb_section(self):
        card = SectionCard("White Balance & Color")
        picker = QHBoxLayout()
        self.pick_neutral_button = QPushButton("Pick Neutral Area")
        self.reset_neutral_button = QPushButton("Clear Sample")
        picker.addWidget(self.pick_neutral_button)
        picker.addWidget(self.reset_neutral_button)
        card.body.addLayout(picker)
        self.reset_rgb_button = QPushButton("Reset")
        self.reset_rgb_button.setObjectName("subtleButton")
        card.header_layout.addWidget(self.reset_rgb_button)
        self.red_channel_slider = LabeledSlider("Red", -100, 100, 0, "redSlider")
        self.green_channel_slider = LabeledSlider("Green", -100, 100, 0, "greenSlider")
        self.blue_channel_slider = LabeledSlider("Blue", -100, 100, 0, "blueSlider")
        for s in (self.red_channel_slider, self.green_channel_slider, self.blue_channel_slider):
            card.body.addWidget(s)
        self.saturation_slider = LabeledSlider("Saturation", -100, 100, 0, "saturationSlider", "%")
        card.body.addWidget(self.saturation_slider)
        self.panel_layout.addWidget(card)

    def _build_tone_section(self):
        card = SectionCard("Light & Tone")
        self.tone_sliders = {}
        for key in ("exposure", "brightness", "contrast", "highlights", "shadows"):
            if key == "exposure":
                slider = LabeledSlider("Exposure", -200, 200, 0, "exposureSlider",
                                       formatter=lambda v: f"{v/100:+.2f} EV")
            else:
                slider = LabeledSlider(key.title(), -100, 100, 0, key + "Slider")
            slider.value_changed.connect(self.tone_changed)
            self.tone_sliders[key] = slider
            card.body.addWidget(slider)
        self.panel_layout.addWidget(card)

    def _build_crop_section(self):
        card = SectionCard("Crop")
        self.crop_help_label = QLabel(
            "Choose a ratio, Select Crop, drag on the photo, then Apply. Reset restores the full image.")
        self.crop_help_label.setWordWrap(True)
        self.crop_help_label.setObjectName("valueLabel")
        card.body.addWidget(self.crop_help_label)
        self.crop_ratio_combo = QComboBox()
        self.crop_ratio_combo.addItems(["Freeform", "Original", "1:1", "4:3", "16:9"])
        card.body.addWidget(self.crop_ratio_combo)
        row = QHBoxLayout()
        self.crop_button = QPushButton("Select Crop")
        self.crop_apply_button = QPushButton("Apply")
        self.crop_reset_button = QPushButton("Reset")
        for button in (self.crop_button, self.crop_apply_button, self.crop_reset_button):
            row.addWidget(button)
        self.crop_apply_button.setEnabled(False)
        card.body.addLayout(row)
        self.panel_layout.addWidget(card)

    def _build_pen_section(self):
        card = SectionCard("Draw Markup")
        self.pen_toggle = QCheckBox("Draw on photo")
        card.body.addWidget(self.pen_toggle)
        self.pen_size_slider = LabeledSlider("Size", 1, 30, 4, "penSizeSlider", " px")
        card.body.addWidget(self.pen_size_slider)
        self.pen_color_combo = QComboBox()
        self.pen_color_combo.addItems(["Red", "White", "Black"])
        card.body.addWidget(self.pen_color_combo)
        self.panel_layout.addWidget(card)

    def _build_preset_section(self):
        card = SectionCard("Custom Presets")
        self.preset_combo = QComboBox()
        self.preset_combo.setPlaceholderText("Select a preset")
        card.body.addWidget(self.preset_combo)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.save_preset_button = QPushButton("Save Current as Preset")
        self.delete_preset_button = QPushButton("Delete Preset")
        row.addWidget(self.save_preset_button, 3)
        row.addWidget(self.delete_preset_button, 2)
        card.body.addLayout(row)
        self.panel_layout.addWidget(card)

    def _build_lut_section(self):
        card = SectionCard("LUT")
        row = QHBoxLayout()
        self.load_lut_button = QPushButton("Load .cube LUT")
        self.clear_lut_button = QPushButton("Clear")
        self.lut_file_label = QLabel("None loaded")
        self.lut_file_label.setObjectName("valueLabel")
        row.addWidget(self.load_lut_button)
        row.addWidget(self.lut_file_label, 1)
        row.addWidget(self.clear_lut_button)
        card.body.addLayout(row)
        self.lut_intensity_slider = LabeledSlider("Intensity", 0, 100, 100, "lutIntensitySlider", "%")
        card.body.addWidget(self.lut_intensity_slider)
        self.panel_layout.addWidget(card)

    def _build_text_section(self):
        card = SectionCard("Text Markup")
        self.add_text_toggle = QCheckBox()
        self.add_text_toggle.setToolTip("Add Text")
        card.header_layout.addWidget(QLabel("Add Text"))
        card.header_layout.addWidget(self.add_text_toggle)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type text to place on image")
        self.font_size_slider = LabeledSlider("Size", 8, 144, 32, "fontSizeSlider", "pt")
        card.body.addWidget(self.text_input)
        card.body.addWidget(self.font_size_slider)
        self.text_controls = (self.text_input, self.font_size_slider)
        for w in self.text_controls:
            w.setEnabled(False)
        self.panel_layout.addWidget(card)

    def _connect_signals(self):
        self.load_image_button.clicked.connect(self.load_image_requested)
        self.save_image_button.clicked.connect(self.save_image_requested)
        for s in (self.red_channel_slider, self.green_channel_slider, self.blue_channel_slider):
            s.value_changed.connect(self._emit_rgb)
        self.reset_rgb_button.clicked.connect(self.reset_color_requested)
        self.saturation_slider.value_changed.connect(self.saturation_changed)
        self.pick_neutral_button.clicked.connect(self.pick_neutral_requested)
        self.reset_neutral_button.clicked.connect(self.reset_neutral_requested)
        self.crop_button.clicked.connect(self.crop_requested)
        self.crop_apply_button.clicked.connect(self.crop_apply_requested)
        self.crop_reset_button.clicked.connect(self.crop_reset_requested)
        self.pen_toggle.toggled.connect(self.pen_toggled)
        self.preset_combo.currentTextChanged.connect(self.preset_selected)
        self.save_preset_button.clicked.connect(self.save_preset_requested)
        self.delete_preset_button.clicked.connect(self.delete_preset_requested)
        self.load_lut_button.clicked.connect(self.load_lut_requested)
        self.lut_intensity_slider.value_changed.connect(self.lut_intensity_changed)
        self.add_text_toggle.toggled.connect(self._on_text_toggle)
        self.font_size_slider.value_changed.connect(self.text_font_size_changed)
        self.text_input.textChanged.connect(self.text_content_changed)

    def _emit_rgb(self, _=None):
        self.rgb_channels_changed.emit(
            self.red_channel_slider.value(), self.green_channel_slider.value(), self.blue_channel_slider.value()
        )

    def _on_text_toggle(self, checked):
        for w in self.text_controls:
            w.setEnabled(checked)
        self.text_markup_toggled.emit(checked)

    def reset_rgb_channels(self):
        for s in (self.red_channel_slider, self.green_channel_slider, self.blue_channel_slider):
            s.reset()


class PreviewSignals(QObject):
    finished = pyqtSignal(int, object, object)
    failed = pyqtSignal(int, str)


class PreviewTask(QRunnable):
    def __init__(self, generation, original, state, lut, full_resolution):
        super().__init__()
        self.generation = generation
        self.original = original
        self.state = state
        self.lut = lut
        self.full_resolution = full_resolution
        self.signals = PreviewSignals()

    def run(self):
        try:
            bounds = crop_bounds(self.original, self.state.get("crop"))
            finished = render(self.original, self.state, self.lut,
                              max_side=None if self.full_resolution else 2400)
            self.signals.finished.emit(self.generation, finished, bounds)
        except (OSError, ValueError) as exc:
            self.signals.failed.emit(self.generation, str(exc))


class ImageEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumen")
        self.resize(1360, 860)
        self.setMinimumSize(900, 600)
        self.original: Image.Image | None = None
        self.source_path: str | None = None
        self.state = self._default_state()
        self.lut = None
        self.presets = {}
        self.undo_stack = []
        self.redo_stack = []
        self._slider_drag = False
        self._preview_scale = 1.0
        self._selected_crop = None
        self._fit_next = False
        self._render_full = False
        self._actual_zoom_next = False
        self._render_generation = 0
        self._render_running = False
        self._preview_pending = False
        self._current_task = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._dispatch_preview)

        root = QWidget()
        root.setObjectName("rootWidget")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.image_canvas = ImageCanvas()
        self.control_panel = ControlPanel()
        body.addWidget(self.image_canvas, 1)
        body.addWidget(self.control_panel)
        root_layout.addLayout(body, 1)

        self._connect_signals()
        for keys, action in (("Ctrl+O", self.load_image), ("Ctrl+S", self.save_image),
                             ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo),
                             ("Ctrl+Shift+Z", self.redo)):
            QShortcut(QKeySequence(keys), self).activated.connect(action)
        self.set_image_loaded(False)
        self.control_panel.delete_preset_button.setEnabled(False)
        self.text_item = QGraphicsTextItem()
        self.text_item.setDefaultTextColor(QColor("white"))
        self.text_item.setZValue(2)
        self.text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(4)
        shadow.setOffset(1, 1)
        self.text_item.setGraphicsEffect(shadow)
        self.image_canvas.canvas_scene.addItem(self.text_item)
        self.text_item.hide()
        self._load_presets()

    def _build_top_bar(self):
        bar = QWidget()
        bar.setObjectName("topBar")
        bar.setFixedHeight(44)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 10, 0)
        row.setSpacing(4)
        self.app_title_label = QLabel("Lumen")
        self.app_title_label.setObjectName("appTitle")
        self.file_name_label = QLabel("—")
        self.file_name_label.setObjectName("zoomLabel")
        row.addWidget(self.app_title_label)
        row.addSpacing(10)
        row.addWidget(self.file_name_label)
        row.addStretch()
        self.zoom_out_button = QPushButton("−")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("zoomLabel")
        self.zoom_label.setFixedWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_in_button = QPushButton("+")
        self.fit_button = QPushButton("Fit")
        self.actual_size_button = QPushButton("1:1")
        self.actual_size_button.setToolTip("Show original pixels at 100%; large photos may take a moment")
        self.toggle_panel_button = QPushButton("Hide Panel")
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        row.addWidget(self.undo_button)
        row.addWidget(self.redo_button)
        for b in (self.zoom_out_button, self.zoom_in_button, self.fit_button,
                  self.actual_size_button, self.toggle_panel_button):
            b.setObjectName("subtleButton")
        for w in (self.zoom_out_button, self.zoom_label, self.zoom_in_button,
                  self.fit_button, self.actual_size_button):
            row.addWidget(w)
        row.addSpacing(12)
        row.addWidget(self.toggle_panel_button)
        return bar

    def _connect_signals(self):
        cp = self.control_panel
        cp.load_image_requested.connect(self.load_image)
        cp.save_image_requested.connect(self.save_image)
        cp.rgb_channels_changed.connect(self.update_rgb_channels)
        cp.preset_selected.connect(self.apply_preset)
        cp.preset_combo.currentIndexChanged.connect(
            lambda i: cp.delete_preset_button.setEnabled(i >= 0))
        cp.save_preset_requested.connect(self.save_current_preset)
        cp.delete_preset_requested.connect(self.delete_preset)
        cp.load_lut_requested.connect(self.load_lut_file)
        cp.lut_intensity_changed.connect(self.update_lut_intensity)
        cp.text_markup_toggled.connect(self.toggle_text_markup)
        cp.text_font_size_changed.connect(self.update_text_font_size)
        cp.text_content_changed.connect(self.update_text_content)
        cp.saturation_changed.connect(self.update_saturation)
        cp.tone_changed.connect(self.update_tone)
        cp.pick_neutral_requested.connect(self.begin_neutral_picker)
        cp.reset_neutral_requested.connect(self.reset_neutral)
        cp.reset_color_requested.connect(self.reset_color)
        cp.crop_requested.connect(self.begin_crop)
        cp.crop_apply_requested.connect(self.apply_crop)
        cp.crop_reset_requested.connect(self.reset_crop)
        cp.pen_toggled.connect(self.toggle_pen)
        cp.pen_size_slider.value_changed.connect(self._update_pen_style)
        cp.pen_color_combo.currentTextChanged.connect(self._update_pen_style)
        cp.clear_lut_button.clicked.connect(self.clear_lut)
        self.image_canvas.point_picked.connect(self.pick_neutral)
        self.image_canvas.selection_finished.connect(self.crop_selected)
        self.image_canvas.stroke_finished.connect(self.add_stroke)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        for slider in (cp.red_channel_slider, cp.green_channel_slider, cp.blue_channel_slider,
                       cp.saturation_slider, cp.lut_intensity_slider, *cp.tone_sliders.values()):
            slider.slider.sliderPressed.connect(self._slider_pressed)
            slider.slider.sliderReleased.connect(self._slider_released)

        self.image_canvas.zoom_changed.connect(lambda z: self.zoom_label.setText(f"{round(z * 100)}%"))
        self.zoom_in_button.clicked.connect(lambda: self._step_zoom(ImageCanvas.ZOOM_STEP))
        self.zoom_out_button.clicked.connect(lambda: self._step_zoom(1 / ImageCanvas.ZOOM_STEP))
        self.fit_button.clicked.connect(self._fit_preview)
        self.actual_size_button.clicked.connect(self._actual_size)
        self.toggle_panel_button.clicked.connect(self.toggle_control_panel)

    def _step_zoom(self, factor):
        c = self.image_canvas
        new_zoom = c.current_zoom * factor
        if not (ImageCanvas.ZOOM_MIN <= new_zoom <= ImageCanvas.ZOOM_MAX):
            return
        c.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        c.scale(factor, factor)
        c.current_zoom = new_zoom
        c.zoom_changed.emit(c.current_zoom)
        c.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def _fit_preview(self):
        if self.original is None:
            return
        self._actual_zoom_next = False
        if self._render_full:
            self._render_full = False
            self._fit_next = True
            self.schedule_preview()
        else:
            self.image_canvas.fit_to_window()

    def _actual_size(self):
        if self.original is None:
            return
        if self._preview_scale < 1 and not self._render_full:
            self._render_full = True
            self._actual_zoom_next = True
            self.schedule_preview()
        else:
            self.image_canvas.reset_zoom()

    # ---- UI state helpers (call these from backend code) -----------------
    def set_image_loaded(self, loaded: bool, file_name: str = ""):
        """Update the title bar and export availability."""
        self.file_name_label.setText(file_name if loaded else "—")
        self.control_panel.save_image_button.setEnabled(loaded)

    def set_lut_file_name(self, file_name: str | None):
        self.control_panel.lut_file_label.setText(file_name or "None loaded")

    def set_preset_names(self, names: list[str]):
        combo = self.control_panel.preset_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        combo.setCurrentIndex(-1)
        combo.blockSignals(False)
        self.control_panel.delete_preset_button.setEnabled(False)

    def toggle_control_panel(self):
        visible = not self.control_panel.isVisible()
        self.control_panel.setVisible(visible)
        self.toggle_panel_button.setText("Hide Panel" if visible else "Show Panel")

    @staticmethod
    def _default_state():
        return {"red": 0, "green": 0, "blue": 0, "saturation": 0,
                "exposure": 0, "brightness": 0, "contrast": 0,
                "highlights": 0, "shadows": 0,
                "neutral_gains": [1.0, 1.0, 1.0], "crop": None, "strokes": [],
                "lut_path": None, "lut_intensity": 100,
                "text_enabled": False, "text_content": "", "text_size": 32}

    @staticmethod
    def _app_dir():
        path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _qimage(image: Image.Image) -> QImage:
        image = image.convert("RGBA" if image.mode == "RGBA" else "RGB")
        data = image.tobytes()
        fmt = QImage.Format.Format_RGBA8888 if image.mode == "RGBA" else QImage.Format.Format_RGB888
        return QImage(data, image.width, image.height, len(image.getbands()) * image.width, fmt).copy()

    def _history(self):
        self.undo_stack.append(copy.deepcopy(self.state))
        self.undo_stack = self.undo_stack[-40:]
        self.redo_stack.clear()
        self.undo_button.setEnabled(True)
        self.redo_button.setEnabled(False)

    def _change(self):
        if not self._slider_drag:
            self._history()

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
        self.state = state
        self.lut = None
        if state.get("lut_path"):
            try:
                self.lut = load_cube(state["lut_path"])
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "LUT unavailable", str(exc))
        self.set_lut_file_name(Path(state["lut_path"]).name if state.get("lut_path") else None)
        cp = self.control_panel
        for key, widget in (("red", cp.red_channel_slider), ("green", cp.green_channel_slider),
                            ("blue", cp.blue_channel_slider), ("saturation", cp.saturation_slider),
                            ("lut_intensity", cp.lut_intensity_slider), ("text_size", cp.font_size_slider),
                            *cp.tone_sliders.items()):
            widget.set_value_silently(state.get(key, self._default_state().get(key, 0)))
        self._sync_rgb_controls()
        cp.add_text_toggle.blockSignals(True)
        cp.add_text_toggle.setChecked(state.get("text_enabled", False))
        cp.add_text_toggle.blockSignals(False)
        cp.text_input.blockSignals(True)
        cp.text_input.setText(state.get("text_content", ""))
        cp.text_input.blockSignals(False)
        for widget in cp.text_controls:
            widget.setEnabled(cp.add_text_toggle.isChecked())
        self._update_text_item()
        self.image_canvas.set_mode("text" if state.get("text_enabled") else "pan")
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))
        self._fit_next = True
        self.schedule_preview()

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open image", "", "Images (*.jpg *.jpeg *.png)")
        if not path:
            return
        try:
            image = load_photo(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Could not open image", str(exc))
            return
        self.original = image
        self.source_path = path
        self._preview_scale = 1.0
        self._render_full = False
        self.image_canvas.set_pixmap(QPixmap())
        self.control_panel.rgb_parade_scope.set_parade_data(None)
        self.state = self._default_state()
        self.lut = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        self._restore(self.state)
        self.set_image_loaded(True, Path(path).name)
        self._fit_next = True
        self.schedule_preview()

    def schedule_preview(self):
        if self.original is not None:
            self._render_generation += 1
            self.preview_timer.start(65)

    def _dispatch_preview(self):
        if self.original is None:
            return
        if self._render_running:
            self._preview_pending = True
            return
        self._render_running = True
        self._preview_pending = False
        task = PreviewTask(self._render_generation, self.original, copy.deepcopy(self.state),
                           self.lut, self._render_full)
        task.signals.finished.connect(self._preview_finished)
        task.signals.failed.connect(self._preview_failed)
        self._current_task = task
        self.pool.start(task)

    def _preview_finished(self, generation, rendered, bounds):
        self._render_running = False
        self._current_task = None
        if generation != self._render_generation:
            self._dispatch_preview()
            return
        try:
            self._preview_scale = rendered.width / (bounds[2] - bounds[0])
            text_x = self.text_item.x() / max(1, self.image_canvas.image_item.pixmap().width())
            text_y = self.text_item.y() / max(1, self.image_canvas.image_item.pixmap().height())
            fit = self._fit_next
            self.image_canvas.set_pixmap(QPixmap.fromImage(self._qimage(rendered)), fit=fit)
            self._fit_next = False
            if self._actual_zoom_next:
                self.image_canvas.reset_zoom()
                self._actual_zoom_next = False
            self._update_text_item()
            if fit:
                self.text_item.setPos(rendered.width * .05, rendered.height * .85)
            else:
                self.text_item.setPos(text_x * rendered.width, text_y * rendered.height)
            self.update_rgb_parade(rendered)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Preview error", str(exc))
        if self._preview_pending:
            self._dispatch_preview()

    def _preview_failed(self, generation, message):
        self._render_running = False
        self._current_task = None
        if generation == self._render_generation:
            QMessageBox.warning(self, "Preview error", message)
        else:
            self._dispatch_preview()

    def update_rgb_parade(self, rendered=None):
        if rendered is not None:
            self.control_panel.rgb_parade_scope.set_parade_data(parade(rendered))

    def _draw_text(self, qimage: QImage):
        if not (self.state["text_enabled"] and self.state["text_content"]):
            return
        scale = qimage.width() / max(1, self.image_canvas.image_item.pixmap().width())
        font = QFont("Segoe UI Semibold")
        font.setPixelSize(max(1, round(self.text_item.font().pixelSize() * scale)))
        x, y = self.text_item.x() * scale, self.text_item.y() * scale
        painter = QPainter(qimage)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(font)
        baseline = y + QFontMetricsF(font).ascent()
        painter.setPen(QColor(0, 0, 0, 170))
        painter.drawText(QPointF(x + 2 * scale, baseline + 2 * scale), self.state["text_content"])
        painter.setPen(QColor("white"))
        painter.drawText(QPointF(x, baseline), self.state["text_content"])
        painter.end()

    def save_image(self):
        if self.original is None:
            return
        suggested = str(Path(self.source_path).with_name(Path(self.source_path).stem + "-edited.png"))
        path, _ = QFileDialog.getSaveFileName(self, "Export edited image", suggested,
                                               "PNG image (*.png);;JPEG image (*.jpg)")
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg"):
            path += ".png"
            suffix = ".png"
        if Path(path).resolve() == Path(self.source_path).resolve():
            QMessageBox.warning(self, "Choose another filename",
                                "Save an edited copy with a different name to keep the original photo.")
            return
        try:
            output = render(self.original, self.state, self.lut)
            if suffix in (".jpg", ".jpeg") and output.mode == "RGBA":
                background = Image.new("RGB", output.size, "white")
                background.paste(output, mask=output.getchannel("A"))
                output = background
            qimage = self._qimage(output)
            self._draw_text(qimage)
            if suffix in (".jpg", ".jpeg"):
                qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)
            if not qimage.save(path, "PNG" if suffix == ".png" else "JPG", 92 if suffix != ".png" else -1):
                raise OSError("The image could not be written to that location.")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def update_rgb_channels(self, red: int, green: int, blue: int):
        displayed = (red, green, blue)
        gains = self.state.get("neutral_gains", [1, 1, 1])
        values = tuple(round(((1 + value / 100) / max(0.01, gain) - 1) * 100)
                       for value, gain in zip(displayed, gains))
        values = tuple(max(-100, min(100, value)) for value in values)
        if values != tuple(self.state[k] for k in ("red", "green", "blue")):
            self._change()
            self.state.update(zip(("red", "green", "blue"), values))
            self.schedule_preview()

    def update_saturation(self, value):
        if value != self.state["saturation"]:
            self._change()
            self.state["saturation"] = value
            self.schedule_preview()

    def update_tone(self):
        values = {key: widget.value() for key, widget in self.control_panel.tone_sliders.items()}
        if any(self.state.get(key) != value for key, value in values.items()):
            self._change()
            self.state.update(values)
            self.schedule_preview()

    def begin_neutral_picker(self):
        if self.original is not None:
            self.control_panel.pen_toggle.setChecked(False)
            self.image_canvas.set_mode("pick")

    def pick_neutral(self, x, y):
        left, top, _, _ = crop_bounds(self.original, self.state["crop"])
        try:
            gains = neutral_gains(self.original, left+x/self._preview_scale, top+y/self._preview_scale)
        except ValueError as exc:
            QMessageBox.information(self, "Choose another area", str(exc))
            return
        self._history()
        self.state["neutral_gains"] = gains
        self._sync_rgb_controls()
        self.schedule_preview()

    def reset_neutral(self):
        if all(abs(gain - 1.0) < 1e-6 for gain in self.state["neutral_gains"]):
            return
        self._history()
        self.state["neutral_gains"] = [1, 1, 1]
        self._sync_rgb_controls()
        self.schedule_preview()

    def _sync_rgb_controls(self):
        """Display the combined manual and sampled RGB correction on the sliders."""
        gains = self.state.get("neutral_gains", [1, 1, 1])
        widgets = (self.control_panel.red_channel_slider,
                   self.control_panel.green_channel_slider,
                   self.control_panel.blue_channel_slider)
        for key, widget, gain in zip(("red", "green", "blue"), widgets, gains):
            combined = (1 + self.state[key] / 100) * gain
            displayed = max(-100, min(100, round((combined - 1) * 100)))
            widget.set_value_silently(displayed)

    def reset_color(self):
        keys = ("red", "green", "blue", "saturation")
        neutral_active = any(abs(gain - 1.0) >= 1e-6 for gain in self.state["neutral_gains"])
        if not neutral_active and all(self.state[key] == 0 for key in keys):
            return
        self._history()
        self.state.update({key: 0 for key in keys})
        self.state["neutral_gains"] = [1, 1, 1]
        widgets = (self.control_panel.red_channel_slider,
                   self.control_panel.green_channel_slider,
                   self.control_panel.blue_channel_slider,
                   self.control_panel.saturation_slider)
        for widget in widgets:
            widget.set_value_silently(0)
        self.schedule_preview()

    def begin_crop(self):
        if self.original is not None:
            self.control_panel.pen_toggle.setChecked(False)
            self._selected_crop = None
            self.control_panel.crop_apply_button.setEnabled(False)
            self.image_canvas.set_mode("crop")

    def crop_selected(self, rect):
        self._selected_crop = rect
        self.control_panel.crop_apply_button.setEnabled(rect.width() >= 5 and rect.height() >= 5)

    def apply_crop(self):
        if self.original is None or self._selected_crop is None:
            return
        left, top, right, bottom = crop_bounds(self.original, self.state["crop"])
        r = self._selected_crop
        bounds = (max(left, left+r.left()/self._preview_scale),
                  max(top, top+r.top()/self._preview_scale),
                  min(right, left+r.right()/self._preview_scale),
                  min(bottom, top+r.bottom()/self._preview_scale))
        selected_ratio = self.control_panel.crop_ratio_combo.currentText()
        ratios = {"Original": (right-left)/(bottom-top), "1:1": 1, "4:3": 4/3, "16:9": 16/9}
        if selected_ratio in ratios:
            target = ratios[selected_ratio]
            x0, y0, x1, y1 = bounds
            width, height = x1-x0, y1-y0
            if width / height > target:
                trim = (width - height*target) / 2
                x0, x1 = x0+trim, x1-trim
            else:
                trim = (height - width/target) / 2
                y0, y1 = y0+trim, y1-trim
            bounds = x0, y0, x1, y1
        exact_ratios = {"1:1": (1, 1), "4:3": (4, 3), "16:9": (16, 9)}
        if selected_ratio in exact_ratios:
            a, b = exact_ratios[selected_ratio]
            unit = max(1, min(int((bounds[2]-bounds[0])/a), int((bounds[3]-bounds[1])/b)))
            width, height = a * unit, b * unit
            center_x = (bounds[0]+bounds[2])/2
            center_y = (bounds[1]+bounds[3])/2
            x0 = max(left, min(right-width, round(center_x-width/2)))
            y0 = max(top, min(bottom-height, round(center_y-height/2)))
            bounds = x0, y0, x0+width, y0+height
        if bounds[2]-bounds[0] < 2 or bounds[3]-bounds[1] < 2:
            return
        self._history()
        self.state["crop"] = bounds
        self.image_canvas.set_mode("pan")
        self._selected_crop = None
        self.control_panel.crop_apply_button.setEnabled(False)
        self._fit_next = True
        self.schedule_preview()

    def reset_crop(self):
        if self.state["crop"] is not None:
            self._history()
            self.state["crop"] = None
            self._fit_next = True
            self.schedule_preview()
        self.image_canvas.set_mode("pan")
        self.control_panel.crop_apply_button.setEnabled(False)

    def toggle_pen(self, enabled):
        if enabled and self.original is None:
            self.control_panel.pen_toggle.setChecked(False)
            return
        self.image_canvas.set_mode("pen" if enabled else "pan")

    def _update_pen_style(self, _=None):
        cp = self.control_panel
        self.image_canvas.pen_color = QColor({"Red": "#D12222", "White": "white",
                                               "Black": "black"}[cp.pen_color_combo.currentText()])
        self.image_canvas.pen_width = cp.pen_size_slider.value()

    def add_stroke(self, points):
        if not points or self.original is None:
            return
        left, top, _, _ = crop_bounds(self.original, self.state["crop"])
        color = {"Red": "#D12222", "White": "white", "Black": "black"}[self.control_panel.pen_color_combo.currentText()]
        self._history()
        self.state["strokes"].append({"points": [[left+x/self._preview_scale, top+y/self._preview_scale]
                                                for x, y in points],
                                      "width": self.control_panel.pen_size_slider.value()/self._preview_scale,
                                      "color": color})
        self.schedule_preview()

    def _preset_file(self):
        return self._app_dir() / "presets.json"

    def _load_presets(self):
        try:
            self.presets = json.loads(self._preset_file().read_text(encoding="utf-8"))
            if not isinstance(self.presets, dict):
                raise ValueError("Invalid presets")
        except FileNotFoundError:
            self.presets = {}
        except (OSError, ValueError):
            self.presets = {}
            QMessageBox.warning(self, "Presets", "Could not read the saved presets.")
        self.set_preset_names(sorted(self.presets, key=str.casefold))

    def _write_presets(self):
        path = self._preset_file()
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.presets, indent=2), encoding="utf-8")
        temp.replace(path)
        self.set_preset_names(sorted(self.presets, key=str.casefold))

    def apply_preset(self, preset_name: str):
        if not preset_name or preset_name not in self.presets:
            return
        defaults = self._default_state()
        color_keys = ("red", "green", "blue", "saturation", "exposure", "brightness",
                      "contrast", "highlights", "shadows", "neutral_gains", "lut_path", "lut_intensity")
        values = {key: copy.deepcopy(self.presets[preset_name].get(key, defaults[key]))
                  for key in color_keys}
        lut = None
        if values.get("lut_path"):
            try:
                lut = load_cube(values["lut_path"])
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Preset LUT unavailable", str(exc))
                return
        self._history()
        self.state.update(copy.deepcopy(values))
        self.lut = lut
        self.set_lut_file_name(Path(values["lut_path"]).name if values.get("lut_path") else None)
        for key, widget in (("red", self.control_panel.red_channel_slider),
                            ("green", self.control_panel.green_channel_slider),
                            ("blue", self.control_panel.blue_channel_slider),
                            ("saturation", self.control_panel.saturation_slider),
                            ("lut_intensity", self.control_panel.lut_intensity_slider),
                            *self.control_panel.tone_sliders.items()):
            widget.set_value_silently(values.get(key, 0))
        self._sync_rgb_controls()
        self.schedule_preview()

    def save_current_preset(self):
        name, okay = QInputDialog.getText(self, "Save color preset", "Preset name:")
        name = name.strip()
        if not okay or not name:
            return
        if name in self.presets and QMessageBox.question(self, "Replace preset",
                f'Replace the existing preset "{name}"?') != QMessageBox.StandardButton.Yes:
            return
        keys = ("red", "green", "blue", "saturation", "exposure", "brightness", "contrast",
                "highlights", "shadows", "neutral_gains", "lut_path", "lut_intensity")
        self.presets[name] = {key: copy.deepcopy(self.state[key]) for key in keys}
        try:
            self._write_presets()
            self.control_panel.preset_combo.setCurrentText(name)
        except OSError as exc:
            QMessageBox.critical(self, "Preset not saved", str(exc))

    def delete_preset(self):
        name = self.control_panel.preset_combo.currentText()
        if not name or name not in self.presets:
            return
        if QMessageBox.question(self, "Delete preset", f'Delete "{name}"?') != QMessageBox.StandardButton.Yes:
            return
        del self.presets[name]
        try:
            self._write_presets()
        except OSError as exc:
            QMessageBox.critical(self, "Preset not deleted", str(exc))

    def load_lut_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load 3D .cube LUT", "", "3D LUT (*.cube)")
        if not path:
            return
        try:
            lut = load_cube(path)
            store = self._app_dir() / "luts"
            store.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
            saved = store / f"{Path(path).stem}-{digest}.cube"
            shutil.copyfile(path, saved)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "LUT could not be loaded", str(exc))
            return
        self._history()
        self.lut = lut
        self.state["lut_path"] = str(saved)
        self.set_lut_file_name(Path(path).name)
        self.schedule_preview()

    def clear_lut(self):
        if self.state["lut_path"]:
            self._history()
            self.state["lut_path"] = None
            self.lut = None
            self.set_lut_file_name(None)
            self.schedule_preview()

    def update_lut_intensity(self, intensity: int):
        if self.state["lut_intensity"] != intensity:
            self._change()
            self.state["lut_intensity"] = intensity
            self.schedule_preview()

    def _update_text_item(self):
        font = QFont("Segoe UI Semibold")
        font.setPixelSize(max(1, round(self.state["text_size"] * 1.333 * self._preview_scale)))
        self.text_item.setFont(font)
        self.text_item.setPlainText(self.state["text_content"])
        self.text_item.setVisible(self.original is not None and self.state["text_enabled"])

    def toggle_text_markup(self, enabled: bool):
        if self.state["text_enabled"] != enabled:
            self._history()
            self.state["text_enabled"] = enabled
        self._update_text_item()
        if enabled:
            self.control_panel.pen_toggle.setChecked(False)
            self.image_canvas.set_mode("text")
        elif self.image_canvas.mode == "text":
            self.image_canvas.set_mode("pan")

    def update_text_font_size(self, size: int):
        if self.state["text_size"] != size:
            self.state["text_size"] = size
            self._update_text_item()

    def update_text_content(self, value: str):
        if self.state["text_content"] != value:
            self.state["text_content"] = value
            self._update_text_item()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Lumen")
    app.setOrganizationName("Lumen")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = ImageEditorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
