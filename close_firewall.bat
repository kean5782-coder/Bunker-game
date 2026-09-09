@echo off
chcp 65001 >nul
title Close Port 8008

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo Closing port 8008 in Windows Firewall...
netsh advfirewall firewall delete rule name="Bunker Game 8008"
echo.
echo [OK] Port 8008 is closed.
echo.
timeout /t 3 >nul
