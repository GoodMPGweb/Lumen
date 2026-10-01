# Lumen image editor

A local Windows image editor built from Claude Design's PyQt6 layout. It opens JPG and PNG photos, keeps the original in memory, and exports edited copies. Images stay on your computer.

## Run on Windows

1. Install Python 3.10 or newer from python.org, with **Add Python to PATH** enabled.
2. Extract this whole folder. Open Command Prompt in the extracted folder.
3. Run `py -m pip install -r requirements.txt`.
4. Run `py image_editor_ui.py`.

To create a Windows executable folder, run `build_windows.bat` on Windows. It creates `dist\Lumen\Lumen.exe`. Keep the rest of the `dist\Lumen` folder alongside that file. This build script produces an unsigned app and has not been run on Windows in this workspace.

## Build without Python on your PC

The included `.github/workflows/build-windows.yml` builds Lumen using a GitHub-hosted Windows computer. Put the contents of this `Lumen` folder at the root of a dedicated GitHub repository. The build starts after a push to `main`, or you can start it from **Actions → Build Lumen for Windows → Run workflow**. When the build finishes, open its run page and download the **Lumen-Windows** artifact. Extract the downloaded ZIP, keep its files together, and run `Lumen.exe`.

The workflow runs the automated checks and builds an unsigned Windows app. Company device policy may restrict an unsigned executable.

## Controls

- **Light & Tone:** Exposure is −2 to +2 EV. Brightness, Contrast, Highlights and Shadows have −100 to +100 controls.
- **White Balance & Color:** Pick Neutral Area, then click a neutral gray or white area that retains detail. The RGB sliders show the combined correction; Clear Sample removes the sampled correction. Reset clears RGB, sample, and saturation adjustments.
- **Crop:** Choose Freeform, Original, 1:1, 4:3 or 16:9, click Select Crop, drag a rectangle on the photo, then click Apply. Reset restores the whole image. A later crop acts on the currently visible crop.
- **LUT:** Load a 3D `.cube` file, adjust intensity, or clear it. A copy goes to the application's local data folder so saved presets survive if the source LUT is moved. 1D LUTs and other `.lut` dialects are not supported.
- **Presets:** Save, apply and delete named color presets. Presets include the tone controls, saturation, RGB channels, neutral sample correction, `.cube` selection and intensity. Crop and markup stay specific to each photo.
- **Markup:** Draw with a sized red, white or black pen. Enable Text Markup, enter text and drag it on the photo.
- **Zoom:** Mouse wheel, +/−, Fit and 1:1. For large images, 1:1 renders the full resolution before showing actual pixels; this can take a moment. Fit returns to the faster preview.
- **Save Image:** Exports a new PNG or JPEG (JPEG quality 92) at full resolution. The suggested filename ends in `-edited.png`.

Undo and Redo are available in the top bar for color settings, crop and pen strokes. Shortcuts: Ctrl+O opens, Ctrl+S exports, Ctrl+Z undoes, and Ctrl+Y or Ctrl+Shift+Z redoes. The source JPG or PNG remains unchanged in memory. Presets and imported LUTs are kept in the Windows application data location for Lumen.

## Implementation notes

`image_editor_ui.py` contains the interface, event wiring and export. `processing.py` contains image transforms, LUT parsing, scope data and file loading. Preview calculation runs in a worker thread so the window remains responsive while adjustments are processing. Exports can take several seconds on large photos and run in the foreground. The RGB parade uses an 8-bit 0–255 scale, appropriate for this JPG/PNG editor.

Run checks with `py -m unittest discover -s tests -v` (set `QT_QPA_PLATFORM=offscreen` for a machine without a display).
