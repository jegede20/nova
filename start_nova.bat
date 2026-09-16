@echo off
REM Starts Nova with its window open.
cd /d "%~dp0"
if not exist .venv (
    echo Nova is not set up yet. Run setup_nova.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
start "" pythonw run_nova.py
