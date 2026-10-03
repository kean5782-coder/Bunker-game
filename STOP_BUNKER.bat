@echo off
setlocal
chcp 65001 >nul
title Остановка Бункера
echo Закрытие сервера и фонового помощника Бункера...
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0STOP_BUNKER.ps1"
set "bunkerExitCode=%errorlevel%"
echo.
if not "%bunkerExitCode%"=="0" echo Не удалось закрыть всё. Подробности выше.
pause
exit /b %bunkerExitCode%
