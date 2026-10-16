@echo off
cd /d "%~dp0"
echo Starting JARVIS. Open http://127.0.0.1:8765 in Chrome or Edge.
if exist ".venv-voice\Scripts\python.exe" (
  ".venv-voice\Scripts\python.exe" server.py
) else (
  python server.py
)
pause
