@echo off
setlocal
rem Run syntax checks first so annotation-editor and engine errors are also detected.
cd /d "%~dp0"
set "STUDIO_PYTHON=.venv\Scripts\python.exe"
if not exist "%STUDIO_PYTHON%" set "STUDIO_PYTHON=..\..\.venv\Scripts\python.exe"
if not exist "%STUDIO_PYTHON%" (
  echo [ERROR] Python environment was not found.
  echo Create .venv in this tire_distance_studio folder as described in README.md.
  pause
  exit /b 1
)
"%STUDIO_PYTHON%" -m py_compile app.py annotation_editor.py studio_utils.py engine\tire_distance_engine.py
if errorlevel 1 (
  echo [NG] Python syntax check failed.
  pause
  exit /b 1
)
rem Check the bundled engine and required tire model without opening the GUI.
"%STUDIO_PYTHON%" app.py --check
set "STUDIO_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %STUDIO_EXIT%