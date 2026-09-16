@echo off
REM Reports what is installed and what is missing.
title Nova - System Check
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python check_setup.py
pause
