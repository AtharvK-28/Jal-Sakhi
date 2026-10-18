@echo off
rem Double-click to start JalSakhi AI. Needs Python 3.10+ (and Node 18+ only if the web UI must be rebuilt).
cd /d "%~dp0"
python run.py %*
if errorlevel 1 pause
