@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BUNKER GAME SERVER

echo ====================================================================
echo                   BUNKER GAME SERVER STARTUP
echo ====================================================================
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    python -m venv "%~dp0.venv"
)

echo [2/3] Checking dependencies...
"%~dp0.venv\Scripts\pip.exe" install -r "%~dp0requirements.txt" --quiet

echo [3/3] Launching Bunker Server...
"%~dp0.venv\Scripts\python.exe" "%~dp0server\clean_port.py" 64738
start "" "http://localhost:64738"

"%~dp0.venv\Scripts\python.exe" -m uvicorn server.app:app --host 0.0.0.0 --port 64738 --reload


pause
