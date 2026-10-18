@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "from PySide6 import QtCore; import webview; assert QtCore.__version__ == '6.8.3'" 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
start "" /d "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
if errorlevel 1 goto fail
exit /b 0
:fail
echo Launch failed. Please share the error above.
pause
exit /b 1
