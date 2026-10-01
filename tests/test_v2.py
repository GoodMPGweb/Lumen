import os
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from image_editor import ImageEditorWindow, QSS


class V2IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setApplicationName("Lumen")
        cls.app.setOrganizationName("Lumen")
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(QSS)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original_app_dir = ImageEditorWindow._app_dir
        ImageEditorWindow._app_dir = staticmethod(lambda: Path(self.folder.name))
        self.window = ImageEditorWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        ImageEditorWindow._app_dir = staticmethod(self.original_app_dir)
        self.folder.cleanup()

    def wait_preview(self):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            self.app.processEvents()
            if not self.window._render_running and not self.window.preview_timer.isActive():
                return
            time.sleep(.01)
        self.fail("v2 preview did not finish")

    def load(self, suffix="png"):
        path = Path(self.folder.name) / f"original.{suffix}"
        Image.new("RGB", (600, 400), (100, 120, 140)).save(path)
        old = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = lambda *args: (str(path), "")
        try:
            self.window.load_image()
        finally:
            QFileDialog.getOpenFileName = old
        self.wait_preview()
        return path

    def test_dark_ui_slider_alignment_and_zoom_stays_put(self):
        self.load("jpg")
        rows = [self.window.slider_rows[key] for key in
                ("brightness", "highlights", "saturation", "red")]
        self.assertEqual(len({r.slider.mapToGlobal(QPointF(0, 0).toPoint()).x() for r in rows}), 1)
        self.assertEqual(len({r.slider.width() for r in rows}), 1)
        self.window.image_canvas.zoom_by(4)
        canvas = self.window.image_canvas
        canvas.horizontalScrollBar().setValue(60)
        canvas.verticalScrollBar().setValue(40)
        self.app.processEvents()  # Qt settles the view anchor after zooming.
        baseline = (canvas.current_scale(), canvas.horizontalScrollBar().value(),
                    canvas.verticalScrollBar().value())
        for key in ("brightness", "exposure", "contrast", "saturation",
                    "highlights", "shadows", "red", "green", "blue"):
            self.window.slider_rows[key].slider.setValue(25)
        self.wait_preview()
        self.assertEqual(baseline, (canvas.current_scale(), canvas.horizontalScrollBar().value(),
                                    canvas.verticalScrollBar().value()))

    def test_crop_drag_and_markup_eraser_and_export(self):
        self.load()
        w = self.window
        w.crop_tool_toggle.click()
        view = w.image_canvas
        a = view.mapFromScene(QPointF(40, 40))
        b = view.mapFromScene(QPointF(380, 290))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(view.viewport(), b, delay=50)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
        self.assertTrue(w.crop_apply_button.isEnabled())
        w.crop_ratio_combo.setCurrentText("1:1")
        w.crop_apply_button.click()
        self.wait_preview()
        crop = w.state["crop"]
        self.assertEqual(round(crop[2] - crop[0]), round(crop[3] - crop[1]))
        w.crop_reset_button.click()
        self.wait_preview()
        self.assertIsNone(w.state["crop"])
        w.markup_text_input.setText("Example")
        w.add_text_at(80, 70)
        w.add_stroke([(190, 140), (260, 160)])
        self.wait_preview()
        self.assertEqual(len(w.state["texts"]), 1)
        self.assertEqual(len(w.state["strokes"]), 1)
        w.erase_at(84, 74)
        self.assertFalse(w.state["texts"])
        w.erase_at(225, 150)
        self.assertFalse(w.state["strokes"])
        w.markup_text_input.setText("Exported")
        w.add_text_at(80, 70)
        w.add_stroke([(190, 140), (260, 160)])
        output = Path(self.folder.name) / "result.png"
        old = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = lambda *args: (str(output), "")
        try:
            w.save_image()
        finally:
            QFileDialog.getSaveFileName = old
        end = time.monotonic() + 12
        while w._export_task is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(output.exists())
        with Image.open(output) as saved:
            self.assertEqual(saved.size, (600, 400))
            self.assertNotEqual(saved.getpixel((225, 150)), (100, 120, 140))
            self.assertNotEqual(saved.crop((80, 70, 180, 125)).getextrema(),
                                ((100, 100), (120, 120), (140, 140)))

    def test_white_balance_sample_moves_and_clears_sliders(self):
        self.load()
        w = self.window
        w.slider_rows["red"].slider.setValue(10)
        w.pick_neutral(100, 100)
        self.assertNotEqual(w.state["neutral_gains"], [1, 1, 1])
        self.assertGreater(w.slider_rows["red"].value(), 10)
        w.clear_sample_button.click()
        self.assertEqual(w.state["neutral_gains"], [1, 1, 1])
        self.assertEqual(w.slider_rows["red"].value(), 10)

    def test_pen_drag_and_click_eraser(self):
        self.load()
        w = self.window
        canvas = w.image_canvas
        zoom = canvas.current_scale()
        w.draw_pen_tool_toggle.click()
        a = canvas.mapFromScene(QPointF(190, 140))
        b = canvas.mapFromScene(QPointF(260, 160))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(canvas.viewport(), b, delay=50)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=b)
        self.assertEqual(len(w.state["strokes"]), 1)
        self.assertEqual(canvas.current_scale(), zoom)
        w.eraser_tool_toggle.click()
        midpoint = canvas.mapFromScene(QPointF(225, 150))
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=midpoint)
        self.assertEqual(w.state["strokes"], [])

    def test_v1_presets_import_into_v2(self):
        previous = Path(self.folder.name) / "presets.json"
        previous.write_text(json.dumps({"Old look": {
            "brightness": -10, "exposure": 50, "red": 10,
            "neutral_gains": [1.2, 1.0, .9], "saturation": -9,
            "lut_intensity": 100, "lut_path": None,
        }}), encoding="utf-8")
        self.window._load_presets()
        self.assertIn("Old look", self.window.presets)
        self.window.apply_preset("Old look")
        self.assertEqual(self.window.slider_rows["exposure"].value(), 25)
        self.assertEqual(self.window.slider_rows["red"].value(), 32)
        self.assertEqual(self.window.slider_rows["saturation"].value(), -9)

    def test_preset_carries_all_sliders_and_copied_cube(self):
        self.load()
        w = self.window
        for key, value in (("brightness", -10), ("highlights", -8), ("saturation", -9),
                           ("blue", 12), ("lut_intensity", 60), ("pen_size", 7)):
            w.slider_rows[key].slider.setValue(value)
        source = Path(self.folder.name) / "identity.cube"
        rows = [f"{r} {g} {b}" for b in range(2) for g in range(2) for r in range(2)]
        source.write_text("LUT_3D_SIZE 2\n" + "\n".join(rows), encoding="utf-8")
        old_file = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = lambda *args: (str(source), "")
        try:
            w.load_lut_file()
        finally:
            QFileDialog.getOpenFileName = old_file
        imported_lut = Path(w.state["lut_path"])
        before = w.current_adjustments()
        old_name = QInputDialog.getText
        QInputDialog.getText = lambda *args: ("Studio", True)
        try:
            w.save_current_as_preset()
        finally:
            QInputDialog.getText = old_name
        preset = w.presets["Studio"]
        self.assertFalse(Path(preset["lut"]["relative_path"]).is_absolute())
        self.assertTrue((Path(self.folder.name) / ".presets" /
                         preset["lut"]["relative_path"]).exists())
        source.unlink()
        imported_lut.unlink()
        w.reset_all_adjustments()
        w.apply_preset("Studio")
        self.assertEqual(w.current_adjustments(), before)
        self.assertIsNotNone(w.lut)


if __name__ == "__main__":
    unittest.main()
