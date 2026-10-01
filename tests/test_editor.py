import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from processing import load_cube, neutral_gains, parade, render
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from image_editor_ui import ImageEditorWindow


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.fromarray(np.array([[[30, 60, 90], [180, 180, 180]],
                                                 [[20, 30, 40], [230, 230, 230]]], dtype=np.uint8))
        self.base = {"red": 0, "green": 0, "blue": 0, "saturation": 0,
                     "neutral_gains": [1, 1, 1], "lut_intensity": 100}

    def test_tone_and_crop(self):
        for key, pixel in (("exposure", (0, 0)), ("brightness", (0, 0)),
                           ("contrast", (0, 0)), ("shadows", (0, 0)),
                           ("highlights", (1, 1))):
            altered = render(self.image, self.base | {key: 50}, None)
            self.assertFalse(np.array_equal(np.asarray(altered)[pixel], np.asarray(self.image)[pixel]), key)
        self.assertEqual(render(self.image, self.base | {"crop": (0, 0, 1, 2)}, None).size, (1, 2))

    def test_cube_identity_and_parade(self):
        rows = []
        for b in range(2):
            for g in range(2):
                for r in range(2):
                    rows.append(f"{r} {g} {b}")
        with tempfile.TemporaryDirectory() as folder:
            cube = Path(folder) / "identity.cube"
            cube.write_text("TITLE \"Identity\"\nLUT_3D_SIZE 2\n" + "\n".join(rows))
            lut = load_cube(str(cube))
            output = render(self.image, self.base, lut)
            np.testing.assert_array_equal(np.asarray(output), np.asarray(self.image))
            traces = parade(output)
            self.assertEqual(len(traces), 3)
            self.assertEqual(traces[0].shape[0], 256)
            self.assertGreater(traces[0].sum(), 0)
            ranged = Path(folder) / "ranged.cube"
            ranged.write_text("LUT_3D_SIZE 2\nDOMAIN_MIN 0.25 0.25 0.25\n"
                              "DOMAIN_MAX 0.75 0.75 0.75\n" + "\n".join(rows))
            mapped = render(Image.new("RGB", (1, 1), (64, 128, 192)), self.base,
                            load_cube(str(ranged)))
            self.assertLessEqual(mapped.getpixel((0, 0))[0], 2)
            self.assertGreater(mapped.getpixel((0, 0))[2], 250)

    def test_neutral_picker(self):
        image = Image.new("RGB", (50, 50), (100, 120, 140))
        gains = neutral_gains(image, 25, 25)
        balanced = np.array([100, 120, 140]) * gains
        self.assertLess(balanced.max() - balanced.min(), .01)


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_zoom_crop_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            os.environ["XDG_DATA_HOME"] = folder
            win = ImageEditorWindow()
            win.original = Image.new("RGB", (120, 80), (90, 120, 140))
            win.source_path = str(Path(folder) / "original.png")
            win.set_image_loaded(True, "original.png")
            win.schedule_preview()
            self._wait(win)
            zoom = win.image_canvas.current_zoom
            win.control_panel.tone_sliders["exposure"].slider.setValue(100)
            self._wait(win)
            self.assertEqual(zoom, win.image_canvas.current_zoom)
            from PyQt6.QtCore import QRectF
            win.control_panel.crop_ratio_combo.setCurrentText("1:1")
            win._selected_crop = QRectF(5, 5, 70, 55)
            win.apply_crop()
            self._wait(win)
            bounds = win.state["crop"]
            self.assertAlmostEqual(bounds[2] - bounds[0], bounds[3] - bounds[1])
            win.control_panel.pen_toggle.setChecked(True)
            win.add_stroke([(10, 10), (20, 20)])
            win.control_panel.add_text_toggle.setChecked(True)
            win.control_panel.text_input.setText("Test")
            output = str(Path(folder) / "export.png")
            original_dialog = QFileDialog.getSaveFileName
            QFileDialog.getSaveFileName = lambda *args: (output, "PNG image (*.png)")
            try:
                win.save_image()
            finally:
                QFileDialog.getSaveFileName = original_dialog
            self.assertTrue(Path(output).exists())
            with Image.open(output) as exported:
                self.assertEqual(exported.size[0], exported.size[1])
            win.close()

    def test_preset_persists_tone_and_color(self):
        with tempfile.TemporaryDirectory() as folder:
            old_dir = ImageEditorWindow._app_dir
            old_dialog = QInputDialog.getText
            ImageEditorWindow._app_dir = staticmethod(lambda: Path(folder))
            QInputDialog.getText = lambda *args: ("Studio", True)
            try:
                win = ImageEditorWindow()
                win.control_panel.tone_sliders["exposure"].slider.setValue(75)
                win.control_panel.tone_sliders["highlights"].slider.setValue(-30)
                win.control_panel.saturation_slider.slider.setValue(20)
                win.save_current_preset()
                self.assertTrue((Path(folder) / "presets.json").exists())
                win.close()
                restored = ImageEditorWindow()
                restored.apply_preset("Studio")
                self.assertEqual(restored.state["exposure"], 75)
                self.assertEqual(restored.state["highlights"], -30)
                self.assertEqual(restored.state["saturation"], 20)
                restored.close()
            finally:
                ImageEditorWindow._app_dir = staticmethod(old_dir)
                QInputDialog.getText = old_dialog

    def test_neutral_sample_updates_rgb_sliders_and_clear_sample(self):
        win = ImageEditorWindow()
        win.original = Image.new("RGB", (60, 60), (100, 120, 140))
        win._preview_scale = 1.0
        win.pick_neutral(30, 30)
        self.assertEqual(win.control_panel.red_channel_slider.value(), 20)
        self.assertEqual(win.control_panel.green_channel_slider.value(), 0)
        self.assertLess(win.control_panel.blue_channel_slider.value(), 0)
        self.assertNotEqual(win.state["neutral_gains"], [1, 1, 1])
        win.control_panel.reset_neutral_button.click()
        self.assertEqual(win.state["neutral_gains"], [1, 1, 1])
        self.assertEqual(win.control_panel.red_channel_slider.value(), 0)
        win.close()

    def test_color_reset_includes_saturation_and_sample(self):
        win = ImageEditorWindow()
        win.control_panel.red_channel_slider.slider.setValue(30)
        win.control_panel.saturation_slider.slider.setValue(45)
        win.state["neutral_gains"] = [1.2, 1.0, 0.8]
        win.control_panel.reset_rgb_button.click()
        self.assertEqual(win.state["red"], 0)
        self.assertEqual(win.state["saturation"], 0)
        self.assertEqual(win.state["neutral_gains"], [1, 1, 1])
        self.assertEqual(win.control_panel.saturation_slider.value(), 0)
        win.close()

    def test_crop_selection_works_with_mouse_drag(self):
        win = ImageEditorWindow()
        win.resize(1200, 800)
        win.original = Image.new("RGB", (400, 300), (90, 120, 140))
        win.schedule_preview()
        win.show()
        self._wait(win)
        win.begin_crop()
        canvas = win.image_canvas
        start = canvas.mapFromScene(QPointF(50, 50))
        end = canvas.mapFromScene(QPointF(250, 200))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end, delay=50)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertTrue(win.control_panel.crop_apply_button.isEnabled())
        win.control_panel.crop_ratio_combo.setCurrentText("1:1")
        win.control_panel.crop_apply_button.click()
        self.assertIsNotNone(win.state["crop"])
        self.assertAlmostEqual(win.state["crop"][2] - win.state["crop"][0],
                               win.state["crop"][3] - win.state["crop"][1])
        win.control_panel.crop_reset_button.click()
        self.assertIsNone(win.state["crop"])
        win.close()

    def test_actual_size_uses_original_pixels(self):
        win = ImageEditorWindow()
        win.original = Image.new("RGB", (2500, 80), (40, 60, 80))
        win.source_path = "/tmp/large.png"
        win.schedule_preview()
        self._wait(win)
        self.assertEqual(win.image_canvas.image_item.pixmap().width(), 2400)
        win._actual_size()
        self._wait(win)
        self.assertEqual(win.image_canvas.image_item.pixmap().width(), 2500)
        self.assertEqual(win.image_canvas.current_zoom, 1.0)
        win.close()

    def _wait(self, win):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            self.app.processEvents()
            if not win._render_running and not win.preview_timer.isActive() and not win.image_canvas.image_item.pixmap().isNull():
                return
            time.sleep(.01)
        self.fail("preview did not finish")


if __name__ == "__main__":
    unittest.main()
