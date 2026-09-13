# VidUniq Telegram-бот (Linux-сервер)

Тот же уникализатор, но интерфейс — Telegram: прислали видео или GIF → получили обработанный файл.
Работает на любом Linux-сервере (VPS от 1 vCPU / 1 ГБ), ставится за 5 минут через Docker.

[English below ⬇](#english)

## Что умеет

- Все 17 пресетов форматов, размытый фон, фильтры, zoom/скорость (фиксированные или случайные в диапазоне), наложение картинки/GIF, удаление звука, очистка метаданных — как в macOS-приложении
- **Несколько вариантов из одного видео** (1–5) — каждый со своими случайными параметрами
- Очередь: файлы можно слать подряд; статус обновляется прямо в сообщении (`▓▓▓░░ 45%`), кнопка «Отменить»
- Доступ только для указанных Telegram ID
- Файлы до **2 ГБ** (с локальным Bot API сервером — он входит в `docker-compose`)

Чего нет по сравнению с macOS-версией: выбора папки, drag&drop, аппаратного кодирования (на сервере — libx264).

## Установка через Docker (рекомендуется)

**1. Создайте бота.** В Telegram откройте [@BotFather](https://t.me/BotFather) → `/newbot` → получите токен вида `123456789:AAAA…`.

**2. Узнайте свой Telegram ID.** Напишите [@userinfobot](https://t.me/userinfobot) — или позже вашему боту `/id` (он отвечает даже незнакомцам).

**3. Получите `api_id` и `api_hash`** (для локального Bot API сервера, чтобы принимать файлы больше 20 МБ): [my.telegram.org](https://my.telegram.org) → *API development tools* → создайте приложение с любым названием.

**4. Запустите:**

```bash
git clone https://github.com/f0q/VidUniq.git
cd VidUniq/deploy
cp .env.example .env
nano .env                 # BOT_TOKEN, ALLOWED_USERS, API_ID, API_HASH
docker compose up -d
docker compose logs -f bot   # должно быть: «Бот @имя запущен»
```

Образ `ghcr.io/f0q/viduniq-bot` скачивается готовый (amd64 и arm64). Если хотите собрать сами: `docker compose up -d --build`.

**5. Напишите боту `/start`** и пришлите видео.

> ⚠️ Если этот же токен раньше использовался с облачным Bot API (например, вы тестировали бота без Docker), при первом запуске локальный сервер может ответить `401 Unauthorized`. Один раз выполните
> `curl https://api.telegram.org/bot<ТОКЕН>/logOut` и перезапустите `docker compose restart bot`.

### Обновление

```bash
cd VidUniq/deploy && git pull && docker compose pull && docker compose up -d
```

## Установка без Docker (systemd)

Подходит, если файлы небольшие (облачный Bot API: **20 МБ вход / 50 МБ выход**) и не хочется поднимать локальный сервер. Пошаговые команды — в комментариях файла [`deploy/viduniq-bot.service`](../deploy/viduniq-bot.service). Коротко: `apt install ffmpeg`, venv, `pip install ".[bot]"`, `.env`, `systemctl enable --now viduniq-bot`.

## Команды бота

| Команда | Что делает |
|---|---|
| видео / GIF / файл | поставить в очередь и обработать с текущими настройками |
| картинка (или GIF с подписью `overlay`) | установить наложение |
| `/settings` | формат, фильтры, zoom, скорость, наложение, звук, метаданные, число вариантов |
| `/overlay`, `/overlay_off` | подсказка по наложению / убрать |
| `/cancel` | отменить все мои задачи |
| `/queue` | что сейчас обрабатывается и сколько в очереди |
| `/reset` | сбросить настройки |
| `/id` | показать мой Telegram ID |

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | токен от @BotFather |
| `ALLOWED_USERS` | — | ID пользователей через запятую (обязательно) |
| `API_ID`, `API_HASH` | — | для локального Bot API сервера (только Docker-вариант) |
| `BOT_API_URL` | пусто → облако | адрес локального Bot API (`http://telegram-bot-api:8081` в compose) |
| `LOCAL_MODE` | `1` если задан `BOT_API_URL` | читать файлы с общего диска, а не по HTTP |
| `MAX_PARALLEL` | `1` | сколько ffmpeg одновременно |
| `MAX_VARIANTS` | `5` | максимум вариантов на файл |
| `MAX_FILE_MB` | `2000` / `20` | лимит входного файла (локальный / облачный API) |
| `PROGRESS_INTERVAL` | `3` | как часто обновлять статус, сек |
| `WORK_DIR` | `/data` | настройки пользователей и временные файлы |

## Ограничения и советы

- **Качество исходника.** Если отправить видео «как видео», клиент Telegram пережимает его при загрузке. Для максимального качества отправляйте **как файл** (📎 → Файл).
- **Скорость.** libx264 `veryfast` на 2 vCPU кодирует 1080p примерно в реальном времени: минутный ролик ≈ минута. Очередь последовательная (`MAX_PARALLEL=1`); на многоядерном сервере можно поставить 2–3.
- **Диск.** Исходник и результаты удаляются сразу после отправки ответа. В Docker-варианте бот забирает входящий файл с диска Bot API сервера переносом (копия у сервера не остаётся), а раз в 10 минут sweeper удаляет из каталога сервера всё старше `FILE_CACHE_TTL_MIN` (60 мин) — сам сервер ничего не чистит. Том `bot-data` хранит только настройки и картинки наложения.
- **Безопасность.** Никогда не публикуйте `.env`. Бот отвечает незнакомцам только фразой «доступ закрыт» с их ID.

---

## English

**VidUniq Telegram bot** — the same video uniqueizer with Telegram as the interface. Send a video or GIF, get the processed file back. Runs on any Linux server via Docker.

Setup: create a bot with [@BotFather](https://t.me/BotFather), get your user ID from [@userinfobot](https://t.me/userinfobot), get `api_id`/`api_hash` at [my.telegram.org](https://my.telegram.org) (needed for the bundled local Bot API server, which lifts the file limit to 2 GB), then:

```bash
git clone https://github.com/f0q/VidUniq.git && cd VidUniq/deploy
cp .env.example .env && nano .env      # BOT_TOKEN, ALLOWED_USERS, API_ID, API_HASH
docker compose up -d
```

Commands: send media to process; send an image to set an overlay; `/settings` (preset, filters, zoom, speed, overlay position, audio, metadata, number of variants 1–5), `/cancel`, `/queue`, `/reset`, `/id`.
Only user IDs listed in `ALLOWED_USERS` can use the bot. Tip: send videos **as a file** so Telegram doesn't recompress them. Encoding uses libx264 (~real-time on 2 vCPU).
