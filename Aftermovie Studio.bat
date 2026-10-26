@echo off
rem Aftermovie Studio: double-click to start (first start installs everything).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First start: installing Aftermovie Studio. This takes a while once.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( echo Setup failed - see the messages above. & pause & exit /b 1 )
)
set PYTHONIOENCODING=utf-8
echo Starting the studio at http://127.0.0.1:8765/  (close this window to stop it)
".venv\Scripts\python.exe" tools\studio.py serve
pause
