@echo off
title Agent Bus - Claude + ChatGPT
cd /d "%~dp0"
echo Starting Agent Bus... the monitor will open in your browser.
echo Keep this window open while the agents work. Close it to stop them.
echo.
python agent_bus.py serve --relay --open
echo.
echo Agent Bus stopped.
pause
