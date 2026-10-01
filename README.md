# Lumen v2 image editor

A permanent dark mode photo editor for Windows. Open JPG and PNG images, edit a preview, then export a full resolution copy. The original image remains untouched.

## Get the Windows app

Open the latest successful [Windows build](https://github.com/GoodMPGweb/Lumen/actions/workflows/build-windows.yml), download the **Lumen-Windows** artifact, and extract the whole ZIP. Run `Lumen.exe` with the other extracted files alongside it. No Python installation is needed on the PC. The app is unsigned, so a company device policy may restrict it.

For a single executable, download the **Lumen-OneFile-Windows** artifact and run `Lumen-OneFile.exe`. It extracts its bundled libraries to a temporary folder each time it opens, so startup can take longer than the folder version. Presets and LUT copies remain in the user's application data folder, separate from either executable.

## Controls

- **Tonal Adjustments:** Brightness, Exposure (±2 EV), Contrast, Saturation, Highlights, and Shadows. The zero handles share one center line.
- **RGB Parade Scope:** Live red, green and blue waveforms with white lines at maximum and minimum.
- **RGB Channels:** Adjust channels manually, or click **WB Eyedropper** and then a white or neutral gray area with detail. The RGB sliders show the combined correction. **Clear WB Sample** removes the eyedropper correction while keeping manual edits.
- **Crop:** Select a ratio, click **Crop Tool**, drag on the photo, then **Apply Crop**. **Reset Crop** restores the whole image.
- **Custom Presets:** Save and apply color settings, including all sliders and sampled white balance. Imported `.cube` LUTs are copied into the preset folder, so presets still work when the source file is moved. Existing Lumen v1 presets are imported on first use.
- **LUT:** Load a 3D `.cube` file, adjust its intensity, or clear it. 1D LUTs and other `.lut` dialects are not supported.
- **Text & Drawing Markup:** Expand the section, choose **Add Text**, type text, and click the photo to place it; drag text to move it. **Draw / Pen** draws with a sized red, white or black pen. Choose **Eraser**, then click a text item or pen stroke to remove it. **Clear Markup** removes all markup from the current photo.
- **Zoom:** Mouse wheel, +/−, Fit and 1:1. Slider previews preserve zoom and pan. Fit is an explicit reset of the view. The preview uses a downscaled image; export uses full resolution.
- **Save Image:** Writes a PNG or JPEG copy at full resolution; JPEG quality is 92.

Undo and Redo are available in the top bar. Shortcuts: Ctrl+O opens, Ctrl+S exports, Ctrl+Z undoes, and Ctrl+Y or Ctrl+Shift+Z redoes.

## Source and build

`image_editor.py` is the v2 dark interface and editor. `processing.py` holds image transforms and `.cube` parsing. `image_editor_ui.py` is the earlier v1 interface retained for reference. Preview rendering and full resolution export run in worker threads.

To run from source on Windows, install Python 3.10 or newer, run `py -m pip install -r requirements.txt`, then `py image_editor.py`. `build_windows.bat` packages the executable locally. GitHub Actions builds the Windows artifact after changes to `main`.

Run tests with `py -m unittest discover -s tests -v`; set `QT_QPA_PLATFORM=offscreen` when testing without a display.
