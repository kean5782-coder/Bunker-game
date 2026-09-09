@echo off
chcp 65001 >nul
title Открытие порта 8008 в Брандмауэре Windows

echo ================================================================
echo    Настройка Брандмауэра Windows для входящих подключений
echo ================================================================
echo.
echo Запрос прав администратора...

powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoExit', '-Command', 'New-NetFirewallRule -DisplayName \"Bunker Game 8008\" -Direction Inbound -LocalPort 8008 -Protocol TCP -Action Allow; Write-Host \"`n[УСПЕХ] Порт 8008 успешно открыт в Брандмауэре Windows!`nОкно можно закрыть.\" -ForegroundColor Green'"

echo Запрос отправлен. Подтвердите действие в появившемся окне Windows.
timeout /t 3 >nul
