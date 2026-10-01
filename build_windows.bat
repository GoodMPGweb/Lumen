@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error
python -m PyInstaller --noconfirm --clean --windowed --name Lumen image_editor_ui.py
if errorlevel 1 goto :error
echo.
echo Build complete. Run dist\Lumen\Lumen.exe
pause
exit /b 0
:error
echo Build failed. See the messages above.
pause
exit /b 1
