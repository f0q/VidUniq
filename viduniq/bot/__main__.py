"""Запуск: python -m viduniq.bot  (переменные окружения — см. deploy/.env.example)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from .. import __version__
from ..core import ffmpeg as ff
from .config import Config


def _load_dotenv(path: str = ".env"):
    """Минимальный .env без зависимостей: KEY=VALUE, # комментарии, не перекрывает окружение."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def selftest(cfg: Config) -> int:
    print(f"VidUniq bot {__version__}")
    for tool in ("ffmpeg", "ffprobe"):
        p = ff.locate(tool)
        print(f"{tool}: {p or 'НЕ НАЙДЕН'}")
    errors = cfg.validate()
    print(f"bot_api: {cfg.bot_api_url or 'https://api.telegram.org'} (local_mode={cfg.local_mode})")
    print(f"allowed_users: {sorted(cfg.allowed_users) or '—'}  admin_users: {sorted(cfg.admin_users) or '—'}")
    print(f"work_dir: {cfg.work_dir}  max_parallel={cfg.max_parallel}  max_file_mb={cfg.max_file_mb}")
    for e in errors:
        print("✗", e)
    return 1 if errors or not ff.locate("ffmpeg") or not ff.locate("ffprobe") else 0


async def run(cfg: Config) -> None:
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    from aiogram.types import BotCommand

    from .handlers import Ctx, build_router
    from .queue import ProcessingQueue, sweep_dir
    from .store import PrefsStore

    ff.require("ffmpeg")
    ff.require("ffprobe")
    os.makedirs(cfg.tmp_dir, exist_ok=True)
    os.makedirs(cfg.users_dir, exist_ok=True)

    session = None
    if cfg.bot_api_url:
        session = AiohttpSession(api=TelegramAPIServer.from_base(cfg.bot_api_url, is_local=cfg.local_mode))
    bot = Bot(cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode="HTML"))

    store = PrefsStore(cfg.users_dir)
    queue = ProcessingQueue(cfg.tmp_dir, cfg.max_parallel, cfg.progress_interval)
    queue.purge_stale()
    ctx = Ctx(cfg, store, queue)
    ctx.bot = bot

    dp = Dispatcher()
    dp.include_router(build_router(ctx))

    from aiogram.exceptions import TelegramUnauthorizedError

    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        await bot.session.close()
        raise SystemExit(
            "Telegram отверг BOT_TOKEN (Unauthorized). Проверьте токен от @BotFather. "
            "Если используете локальный Bot API, а токен раньше работал через облако — один раз выполните "
            "curl https://api.telegram.org/bot<ТОКЕН>/logOut и перезапустите бота."
        )
    await bot.set_my_commands([
        BotCommand(command="settings", description="Настройки обработки"),
        BotCommand(command="overlay", description="Картинка/GIF поверх видео"),
        BotCommand(command="cancel", description="Отменить мои задачи"),
        BotCommand(command="queue", description="Очередь"),
        BotCommand(command="reset", description="Сбросить настройки"),
        BotCommand(command="help", description="Помощь"),
    ])
    logging.info("Бот @%s запущен (api=%s, local=%s)", me.username, cfg.bot_api_url or "cloud", cfg.local_mode)
    queue.start()

    async def sweeper():
        # Кеш локального Bot API сервера (он сам ничего не удаляет) + свой tmp после падений.
        ttl = cfg.file_cache_ttl_min * 60
        while True:
            try:
                n = sweep_dir(cfg.tmp_dir, max(ttl, 600), recursive=False)
                if cfg.bot_api_files_dir and ttl > 0:
                    n += sweep_dir(cfg.bot_api_files_dir, ttl)
                if n:
                    logging.info("sweeper: удалено файлов: %d", n)
            except Exception:  # noqa: BLE001
                logging.exception("sweeper упал")
            await asyncio.sleep(600)

    sweep_task = asyncio.create_task(sweeper()) if cfg.file_cache_ttl_min > 0 else None
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        if sweep_task:
            sweep_task.cancel()
        await queue.stop()
        await bot.session.close()


def main() -> int:
    _load_dotenv(os.environ.get("ENV_FILE", ".env"))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    if "--selftest" in sys.argv:
        return selftest(cfg)
    errors = cfg.validate()
    if errors:
        for e in errors:
            logging.error(e)
        return 2
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        if e.code and not isinstance(e.code, int):
            logging.error("%s", e.code)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
