@echo off
REM Starts Nova hidden in the system tray (no window).
cd /d "%~dp0"
call .venv\Scripts\activate.bat
start "" pythonw run_nova.py --tray
