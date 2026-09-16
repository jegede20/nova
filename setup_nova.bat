@echo off
REM ============================================================
REM  Nova setup for Windows. Double-click this file to install.
REM ============================================================
title Nova Setup
cd /d "%~dp0"

echo.
echo   ====================================
echo     NOVA - Setup
echo   ====================================
echo.

REM --- 1. Check Python exists and is new enough ---
python --version >nul 2>&1
if errorlevel 1 (
    echo   [X] Python was not found.
    echo.
    echo   Install Python 3.10 or newer from https://python.org/downloads
    echo   IMPORTANT: tick "Add python.exe to PATH" on the first screen.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [1/5] Found Python %PYVER%

python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo   [X] Python %PYVER% is too old. Nova needs 3.10 or newer.
    pause
    exit /b 1
)

REM --- 2. Virtual environment ---
if exist .venv (
    echo   [2/5] Using the existing .venv folder
) else (
    echo   [2/5] Creating a private environment ^(.venv^)...
    python -m venv .venv
    if errorlevel 1 goto :failed
)
call .venv\Scripts\activate.bat

REM --- 3. Dependencies ---
echo   [3/5] Installing packages. This takes 3-10 minutes...
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
if errorlevel 1 goto :failed

REM --- 4. Browser engine for web automation ---
echo   [4/5] Installing the browser engine for web automation...
playwright install chromium
if errorlevel 1 (
    echo   [!] The browser engine failed to install.
    echo       Nova will still work, but web automation will be unavailable.
    echo       You can retry later with:  playwright install chromium
)

REM --- 5. Verify ---
echo   [5/5] Checking the installation...
python -c "import PySide6, httpx, numpy; print('      core OK')"
if errorlevel 1 goto :failed

echo.
echo   ====================================
echo     Setup complete.
echo   ====================================
echo.
echo   Start Nova by double-clicking:  start_nova.bat
echo.
echo   First run checklist:
echo     1. Settings  -^>  paste your AI API key  -^>  Test connection
echo     2. Voice enrollment  -^>  read the 4 phrases aloud
echo     3. Say "Hey Nova, open Downloads"
echo.
pause
exit /b 0

:failed
echo.
echo   [X] Setup failed. Scroll up to see the error.
echo       Common fix: close and reopen this window, then run it again.
echo.
pause
exit /b 1
