@echo off
cd /d "%~dp0"
start "" ".venv-voice\Scripts\pythonw.exe" "launcher\control.py" stop
