# Сборка и проверки V4.6

## Windows EXE

Подготовленные `launcher/payload.zip` и `launcher/vendor.zip` уже включены. Go-лаунчер не использует сторонние Go-модули, WebView2, системный Python или CGO.

На Windows с установленным Go:

```bat
BUILD_WINDOWS_EXE.bat
```

Кросс-компиляция в Linux:

```sh
cd launcher
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags='-s -w -H=windowsgui' -o ../Bunker.exe .
```

Это компиляция EXE, не подтверждение работы Windows-окружения. Установочные компоненты описаны в `bootstrap.go`: CPython 3.13.15 embed amd64, pydantic_core 2.46.4, Pillow 12.3.0, Colorama 0.4.6. Pure-Python пакеты и их точные версии перечислены в `VENDOR_VERSIONS.json`. Их лицензии сохранены внутри vendor.zip.

## Изменение игры

Редактируйте `app/server`, `app/static` и `app/desktop_server.py`. Обновите встроенный архив:

```sh
python build_payloads.py
```

По умолчанию эта команда использует только стандартную библиотеку и не пересоздаёт проверенный vendor.zip. После неё заново соберите EXE. Изменения файлов на диске не попадут в уже выпущенный EXE сами собой.

`python build_payloads.py --rebuild-vendor` разрешён только в окружении, где версии совпадают с VENDOR_VERSIONS.json. Версии старых requirements-файлов из V4.4 не следует считать спецификацией новой EXE-сборки.

## Автоматические тесты

```sh
cd launcher
go test -v ./...
cd ../app
PYTHONPATH=. pytest -q
python tools/verify_information_modes_ui.py --chromium /usr/bin/chromium --output ../test-results/game-ui
```

Последняя команда предназначена для проверочной среды с Python, Playwright и Chromium. Это настоящий интерфейс и игровой движок через явно заданную внутрипроцессную тестовую связку. Политики браузера не изменяются. Она не заменяет тест HTTP/WebSocket.

Для теста настоящего процесса помощника и сервера в Linux:

```sh
cd launcher
go build -o ../bunker-test .
../bunker-test --no-browser --data-root ../test-state --dev-python /absolute/path/to/python
```

В другом терминале из корня исходников:

```sh
python tests/test_live_launcher.py --instance test-state/instance.json --output test-results/live_transport.json
python tests/test_wizard_ui.py --instance test-state/instance.json --output test-results/wizard
```

Интерпретатор теста должен содержать зависимости игры. `--dev-python` запрещён в Windows-EXE и не является пользовательским способом запуска. Тесты запускают и останавливают только указанный тестовый экземпляр. Не направляйте их на действующую пользовательскую партию.

`test_live_launcher.py` использует настоящие TCP/HTTP/WebSocket на loopback. Адреса LAN/VPN/public в этом тесте — примеры для проверки формирования ссылок, а не проверенные внешние машины. `test_wizard_ui.py` загружает реальные ассеты интерфейса через set_content и связывает fetch с тестовым HTTP-клиентом, потому что Chromium в среде подготовки запрещает навигацию на localhost. Сам запрет не обходится и не отключается.

Перед распространением как полностью проверенной Windows-сборки требуется чистая Windows 10/11 x64: запуск GUI и трея, первичная загрузка, импорт нативных wheels, создание комнаты, работа ботов и медиа, подключение второго компьютера, остановка/повторный запуск, экспорт автономного ZIP, перенос ZIP на второй Windows-компьютер без доступа к сайтам загрузки.

## Медиа V4.6

`python tools/verify_media_ui.py` из `app` проверяет Web Audio, местные OGG/MP3, общий микшер, MP4, личные настройки и адаптивный диалог в Chromium. Требуются Playwright и `/usr/bin/chromium`; транспорт файлов в браузер явно подменён локальной тестовой связкой. Это не проверка Windows или внешней сети.

`media_tools/input_v4_5.zip` — резерв оригинальных изображений и видео для воспроизводимой пересборки; он не встраивается в EXE.
