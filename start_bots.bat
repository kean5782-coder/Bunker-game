@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BUNKER GAME - ЗАПУСК БОТОВ

echo ====================================================================
echo                   БУНКЕР: ЗАПУСК ИИ-БОТОВ
echo ====================================================================
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение .venv не найдено!
    echo Сначала запустите start_game.bat для первоначальной настройки.
    echo.
    pause
    exit /b 1
)

set ROOM_CODE=%1
if "%ROOM_CODE%"=="" (
    set /p ROOM_CODE="Введите 4-буквенный код комнаты (например: FBYI): "
)

set BOT_COUNT=%2
if "%BOT_COUNT%"=="" (
    set /p BOT_COUNT="Количество ботов [по умолчанию 5]: "
)
if "%BOT_COUNT%"=="" set BOT_COUNT=5

echo.
echo Запуск %BOT_COUNT% ботов в комнату %ROOM_CODE%...
echo.

"%~dp0.venv\Scripts\python.exe" "%~dp0server\bot_client.py" --room %ROOM_CODE% --count %BOT_COUNT%

pause
