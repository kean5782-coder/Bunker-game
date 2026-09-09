@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BUNKER GAME SERVER (Port 8008)

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [FIREWALL] Requesting Administrator privileges to manage port 8008...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

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

echo [3/3] Opening port 8008 in Windows Firewall for this game session...
netsh advfirewall firewall delete rule name="Bunker Game 8008" >nul 2>&1
netsh advfirewall firewall add rule name="Bunker Game 8008" dir=in action=allow protocol=TCP localport=8008 >nul 2>&1

"%~dp0.venv\Scripts\python.exe" "%~dp0server\clean_port.py" 8008
start "" "http://localhost:8008"

"%~dp0.venv\Scripts\python.exe" -m uvicorn server.app:app --host 0.0.0.0 --port 8008 --reload

echo.
echo ====================================================================
echo   SERVER STOPPED. CLOSING PORT 8008 IN WINDOWS FIREWALL...
echo ====================================================================
netsh advfirewall firewall delete rule name="Bunker Game 8008" >nul 2>&1
echo [OK] Port 8008 is now closed in Windows Firewall.
echo.
pause
