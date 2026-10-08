@echo off
setlocal
rem Always run relative to this Studio folder, even when double-clicked elsewhere.
cd /d "%~dp0"
set "STUDIO_PYTHON=.venv\Scripts\python.exe"
if not exist "%STUDIO_PYTHON%" set "STUDIO_PYTHON=..\..\.venv\Scripts\python.exe"
if not exist "%STUDIO_PYTHON%" (
  echo [ERROR] Python environment was not found.
  echo Create .venv in this tire_distance_studio folder as described in README.md.
  pause
  exit /b 1
)
rem Keep the console open only when startup exits with an error.
"%STUDIO_PYTHON%" app.py
if errorlevel 1 pause
endlocal