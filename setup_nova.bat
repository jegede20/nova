@echo off
REM One-shot setup for Nova on Windows.
echo Setting up Nova...
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat

echo Installing core requirements...
pip install -q --upgrade pip
pip install -q -r requirements.txt || goto :err

echo Installing recommended extras (voice, browser, notifications)...
pip install -q faster-whisper sounddevice uiautomation win11toast send2trash keyring
pip install -q playwright && playwright install chromium

echo.
echo Done. Start Nova with:
echo     .venv\Scripts\activate
echo     python run_nova.py
goto :eof

:err
echo.
echo Setup failed. Make sure Python 3.10+ is installed and on your PATH.
exit /b 1
