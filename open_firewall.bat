@echo off
title Открытие порта 64738 в Брандмауэре Windows

echo ================================================================
echo    Настройка Брандмауэра Windows для входящих подключений
echo ================================================================
echo.
echo Запрос прав администратора...

powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoExit', '-Command', 'New-NetFirewallRule -DisplayName \"Bunker Game 64738\" -Direction Inbound -LocalPort 64738 -Protocol TCP -Action Allow; Write-Host \"`n[УСПЕХ] Порт 64738 успешно открыт в Брандмауэре Windows!`nОкно можно закрыть.\" -ForegroundColor Green'"

echo Запрос отправлен. Подтвердите действие в появившемся окне Windows.
timeout /t 3 >nul

