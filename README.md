<p align="center"><img src="viduniq/resources/icon.png" width="96"></p>
<h1 align="center">VidUniq</h1>
<p align="center">Уникализатор видео для Reels, TikTok, Shorts, Instagram, VK, Telegram и других соцсетей.<br>
Нативное приложение для macOS (Apple Silicon) — FFmpeg уже внутри, ничего устанавливать не нужно.</p>

> Форк [0xd5f/Video-Uniqueizer](https://github.com/0xd5f/Video-Uniqueizer) с переработанным интерфейсом, исправленной обработкой и готовой сборкой `.dmg`.

## Скачать

**[Releases → VidUniq-x.y.z-arm64.dmg](https://github.com/f0q/Video-Uniqueizer/releases/latest)**

1. Откройте `.dmg` и перетащите **VidUniq** в **Applications**.
2. Приложение не подписано сертификатом Apple Developer (это платная программа), поэтому macOS при первом запуске скажет, что «не удаётся проверить разработчика». Есть два способа открыть:
   - дважды кликнуть **«Снять карантин.command»** в образе диска (после копирования в Applications), либо
   - открыть **Системные настройки → Конфиденциальность и безопасность**, прокрутить вниз и нажать **«Открыть всё равно»**.

   То же самое одной командой в Терминале: `xattr -cr /Applications/VidUniq.app`

## Возможности

- Массовая обработка видео и GIF, перетаскивание файлов **и папок** в любое место окна
- 17 пресетов под соцсети (Reels/TikTok, Shorts, Instagram Post/Story/Portrait/Landscape, VK, Telegram, YouTube, Facebook, Twitter, Snapchat, Pinterest) — **все работают**, с чёрными полями или размытым фоном
- Фильтры: случайный цвет, ч/б, сепия, инверсия, размытие, отражение, пикселизация, VHS, контраст/насыщенность/яркость, тёплый/холодный
- Zoom и скорость — фиксированные или случайные в диапазоне для каждого файла
- Наложение картинки или GIF в 9 позициях
- Очистка метаданных, удаление звука
- Аппаратное кодирование VideoToolbox на Apple Silicon (в несколько раз быстрее), с автоматическим откатом на libx264
- Реальный прогресс по каждому файлу и общий, кнопка «Отмена», ошибки по файлам не прерывают очередь
- Настройки запоминаются между запусками; окно сжимается до 880×520; светлая и тёмная тема macOS

<p align="center"><img src="docs/screenshot.png" width="900"></p>

## Что изменилось по сравнению с оригиналом

| Было | Стало |
|---|---|
| PyQt5, QSS-темы, на macOS выпадающие меню сливались с фоном | PySide6 (Qt 6), нативный стиль, системная тёмная тема |
| Окно нельзя уменьшить по высоте | Панель настроек прокручивается, минимум 880×520 |
| Drag&drop только на список | Drop на всё окно, папки разворачиваются рекурсивно, подсказка при перетаскивании |
| Из 17 форматов реально работал только Reels/TikTok | Все пресеты масштабируют/дополняют кадр; размытый фон для любого |
| Zoom для «Оригинальный» дополнял кадр до 1080×1920 | Zoom кадрирует/дополняет до исходного размера |
| Видео без звуковой дорожки → ошибка ffmpeg | Тихая дорожка добавляется автоматически |
| Прогресс только по числу файлов, отмены нет | Прогресс по времени внутри файла, «Отмена» убивает ffmpeg и удаляет недописанный файл |
| Папка вывода запрашивалась каждый раз | «Рядом с исходником в `uniq/`» или своя папка; настройки сохраняются |
| Нужно ставить Python, зависимости и ffmpeg вручную | `.dmg` со всем внутри |

## Запуск из исходников

Нужен Python ≥ 3.10 и ffmpeg/ffprobe (в `PATH`, например `brew install ffmpeg`, либо в `vendor/ffmpeg/`).

```bash
git clone https://github.com/f0q/Video-Uniqueizer.git && cd Video-Uniqueizer
uv venv && uv pip install -e ".[dev]"     # или: python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
uv run python main.py
```

Тесты (`tests/test_integration.py` прогоняет реальный ffmpeg на синтетических роликах):

```bash
uv run pytest
```

## Сборка `.app` и `.dmg`

```bash
scripts/fetch_ffmpeg.sh    # статические ffmpeg + ffprobe (arm64) → vendor/ffmpeg/
scripts/build_mac.sh       # → dist/VidUniq.app и dist/VidUniq-<версия>-arm64.dmg
```

GitHub Actions (`.github/workflows/build-macos.yml`) собирает DMG на каждый пуш в `main`, а на тег `v*` публикует релиз.

## Структура

```
main.py                    точка входа
viduniq/app.py             QApplication, логирование (~/Library/Logs/VidUniq/app.log)
viduniq/core/constants.py  пресеты, фильтры, позиции наложения
viduniq/core/ffmpeg.py     поиск ffmpeg, probe, сборка команды, запуск с прогрессом
viduniq/core/worker.py     очередь обработки в QThread
viduniq/ui/                главное окно, список файлов, панель настроек
scripts/                   fetch_ffmpeg.sh, make_icns.sh, build_mac.sh
VidUniq.spec               PyInstaller
```

## Лицензия и авторство

Оригинальный проект [Video-Uniqueizer](https://github.com/0xd5f/Video-Uniqueizer) написан [0xd5f](https://github.com/0xd5f) и опубликован без указания лицензии; этот форк распространяется на тех же условиях. В сборку входят статические бинарники [FFmpeg](https://ffmpeg.org) (GPL, сборка [martin-riedl.de](https://ffmpeg.martin-riedl.de)) и [Qt/PySide6](https://www.qt.io) (LGPL).
