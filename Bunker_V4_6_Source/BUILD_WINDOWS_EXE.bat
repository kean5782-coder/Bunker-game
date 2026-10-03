@echo off
setlocal
cd /d "%~dp0"
where go >nul 2>&1
if errorlevel 1 (
  echo Go is required to rebuild the executable. The player does not need Go.
  pause
  exit /b 1
)
set GOOS=windows
set GOARCH=amd64
set CGO_ENABLED=0
cd launcher
go build -trimpath -ldflags="-s -w -H=windowsgui" -o ..\Bunker.exe .
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo Built: %~dp0Bunker.exe
pause
