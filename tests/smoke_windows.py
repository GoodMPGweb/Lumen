"""Exercise the actual packaged Windows GUI in an interactive CI session."""

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import ImageGrab


def windows_for_app(pid):
    user32 = ctypes.windll.user32
    handles = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def inspect(hwnd, unused):
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        # A one-file bundle has a bootloader parent and a GUI child process.
        if user32.IsWindowVisible(hwnd) and (process_id.value == pid or title.value == "Lumen v2"):
            handles.append(hwnd)
        return True

    user32.EnumWindows(inspect, 0)
    return handles


def main():
    executable = Path(sys.argv[1]).resolve()
    screenshot = Path(sys.argv[2]).resolve()
    with tempfile.TemporaryDirectory() as app_data:
        environment = dict(os.environ, APPDATA=app_data)
        child = subprocess.Popen([str(executable)], cwd=executable.parent, env=environment)
        opened_hwnd = None
        try:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(f"Lumen exited during startup with code {child.returncode}")
                handles = windows_for_app(child.pid)
                if handles:
                    hwnd = handles[0]
                    opened_hwnd = hwnd
                    # Detect a blocked event loop, not just a taskbar button.
                    result = ctypes.c_size_t()
                    responsive = ctypes.windll.user32.SendMessageTimeoutW(
                        hwnd, 0, 0, 0, 2, 2000, ctypes.byref(result))
                    rect = (ctypes.c_long * 4)()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    print(f"Window {hwnd}: bounds {list(rect)}, responsive={bool(responsive)}", flush=True)
                    if responsive and rect[2] - rect[0] > 800:
                        # Allow Qt's first paint event to finish.
                        time.sleep(2)
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        image = ImageGrab.grab(bbox=tuple(rect), all_screens=True)
                        image.save(screenshot)
                        pixels = image.convert("RGB").resize((80, 60))
                        dark = sum(max(pixel) < 130 for pixel in pixels.getdata())
                        fraction = dark / (80 * 60)
                        print(f"Screenshot: {screenshot}, dark pixel fraction={fraction:.2%}", flush=True)
                        if fraction < .45:
                            raise RuntimeError("Packaged Lumen painted a mostly white window")
                        return
                time.sleep(.25)
            raise RuntimeError("Packaged Lumen did not present a responsive window")
        finally:
            if opened_hwnd:
                ctypes.windll.user32.PostMessageW(opened_hwnd, 0x0010, 0, 0)  # WM_CLOSE
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()


if __name__ == "__main__":
    main()
