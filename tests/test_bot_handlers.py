"""Хендлеры через Dispatcher с фейковой сессией Bot API (без сети)."""
import asyncio
import datetime as dt
import os
import subprocess

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import (AnswerCallbackQuery, EditMessageText, GetFile, SendMessage, SendVideo,
                             TelegramMethod)
from aiogram.types import (CallbackQuery, Chat, Document, File, Message, Update, User, Video)

from viduniq.bot.config import Config
from viduniq.bot.handlers import Ctx, build_router
from viduniq.bot.queue import ProcessingQueue
from viduniq.bot.store import PrefsStore
from viduniq.core import ffmpeg as ff

ALLOWED = User(id=100, is_bot=False, first_name="Ok")
STRANGER = User(id=200, is_bot=False, first_name="No")
CHAT = Chat(id=100, type="private")


class FakeSession(BaseSession):
    """Записывает вызовы API и отдаёт правдоподобные ответы."""

    def __init__(self, src_file: str = ""):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.msg_id = 1000
        self.src_file = src_file

    async def close(self):
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendVideo)):
            self.msg_id += 1
            return Message.model_validate(
                dict(message_id=self.msg_id, date=dt.datetime.now(), chat=CHAT,
                     text=getattr(method, "text", None) or getattr(method, "caption", None)),
                context={"bot": bot},
            )
        if isinstance(method, EditMessageText):
            return True
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_size=os.path.getsize(self.src_file),
                        file_path=self.src_file)
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        with open(self.src_file, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk


@pytest.fixture
def env(tmp_path):
    cfg = Config(bot_token="1:x", allowed_users={ALLOWED.id}, work_dir=str(tmp_path), progress_interval=1.0,
                 max_file_mb=100)
    os.makedirs(cfg.tmp_dir, exist_ok=True)
    os.makedirs(cfg.users_dir, exist_ok=True)
    store = PrefsStore(cfg.users_dir)
    queue = ProcessingQueue(cfg.tmp_dir, progress_interval=0.3)
    ctx = Ctx(cfg, store, queue)
    session = FakeSession()
    bot = Bot("1:x", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    ctx.bot = bot
    dp = Dispatcher()
    dp.include_router(build_router(ctx))
    return dp, bot, session, ctx


def _msg(user, text=None, **kw) -> Update:
    m = Message(message_id=1, date=dt.datetime.now(), chat=CHAT, from_user=user, text=text, **kw)
    return Update(update_id=1, message=m)


def _cb(user, data: str, msg_id=50) -> Update:
    m = Message(message_id=msg_id, date=dt.datetime.now(), chat=CHAT, text="menu")
    c = CallbackQuery(id="1", from_user=user, chat_instance="ci", data=data, message=m)
    return Update(update_id=2, callback_query=c)


def _texts(session, cls):
    return [c for c in session.calls if isinstance(c, cls)]


async def test_stranger_is_rejected_with_id(env):
    dp, bot, session, ctx = env
    await dp.feed_update(bot, _msg(STRANGER, "/start"))
    sent = _texts(session, SendMessage)
    assert len(sent) == 1 and "Доступ закрыт" in sent[0].text and "200" in sent[0].text


async def test_start_and_settings_menu(env):
    dp, bot, session, ctx = env
    await dp.feed_update(bot, _msg(ALLOWED, "/start"))
    sent = _texts(session, SendMessage)
    assert len(sent) == 2 and "VidUniq" in sent[0].text and sent[1].reply_markup is not None


async def test_callbacks_change_prefs(env):
    dp, bot, session, ctx = env
    await dp.feed_update(bot, _cb(ALLOWED, "u:strong"))
    await dp.feed_update(bot, _cb(ALLOWED, "t:mirror"))
    assert ctx.store.get(ALLOWED.id).strength == "strong" and ctx.store.get(ALLOWED.id).mirror is True
    await dp.feed_update(bot, _cb(ALLOWED, "u:off"))
    session.calls.clear()
    await dp.feed_update(bot, _cb(ALLOWED, "p:reels"))
    await dp.feed_update(bot, _cb(ALLOWED, "f:1:0"))          # второй фильтр
    await dp.feed_update(bot, _cb(ALLOWED, "z:2"))            # 90–110%
    await dp.feed_update(bot, _cb(ALLOWED, "t:mute"))
    await dp.feed_update(bot, _cb(ALLOWED, "v:3"))
    p = ctx.store.get(ALLOWED.id)
    assert p.preset_slug == "reels" and len(p.filters) == 1 and p.zoom_range == (90, 110)
    assert p.mute is True and p.variants == 3
    assert len(_texts(session, EditMessageText)) == 5
    assert all(c.callback_query_id == "1" for c in _texts(session, AnswerCallbackQuery))


async def test_bad_document_is_explained(env):
    dp, bot, session, ctx = env
    doc = Document(file_id="d", file_unique_id="du", file_name="notes.txt", mime_type="text/plain", file_size=10)
    await dp.feed_update(bot, _msg(ALLOWED, document=doc))
    sent = _texts(session, SendMessage)
    assert sent and "Не понял формат" in sent[-1].text


async def test_too_big_file(env):
    dp, bot, session, ctx = env
    v = Video(file_id="v", file_unique_id="vu", width=10, height=10, duration=1, file_size=101 * 1024 * 1024)
    await dp.feed_update(bot, _msg(ALLOWED, video=v))
    assert "слишком большой" in _texts(session, SendMessage)[-1].text


@pytest.mark.skipif(ff.locate("ffmpeg") is None, reason="ffmpeg не найден")
async def test_video_end_to_end(env, tmp_path):
    dp, bot, session, ctx = env
    src = tmp_path / "src.mp4"
    subprocess.run([ff.require("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    session.src_file = str(src)
    ctx.store.save(ALLOWED.id, ctx.store.get(ALLOWED.id).__class__(preset_slug="tg_post", variants=2))
    ctx.queue.start()
    v = Video(file_id="v", file_unique_id="vu", width=320, height=240, duration=2, file_size=src.stat().st_size,
              file_name="clip.mp4")
    await dp.feed_update(bot, _msg(ALLOWED, video=v))
    # ждём завершения задачи
    for _ in range(300):
        await asyncio.sleep(0.1)
        if not ctx.queue.running and not ctx.queue.pending:
            break
    await asyncio.sleep(0.3)
    await ctx.queue.stop()
    videos = _texts(session, SendVideo)
    assert len(videos) == 2 and videos[0].width == 1280 and videos[0].height == 720
    assert "Вариант 1/2" in videos[0].caption and "Telegram Post" in videos[0].caption
    assert "режим: средняя" in videos[0].caption and "отличие" in videos[0].caption
    edits = _texts(session, EditMessageText)
    assert any("✅" in e.text and "Готово: 2 из 2" in e.text for e in edits)
    assert not os.listdir(ctx.cfg.tmp_dir)           # всё убрано


async def test_cancel_command_without_tasks(env):
    dp, bot, session, ctx = env
    await dp.feed_update(bot, _msg(ALLOWED, "/cancel"))
    assert "нет активных" in _texts(session, SendMessage)[-1].text
    await dp.feed_update(bot, _msg(ALLOWED, "/queue"))
    assert "пуста" in _texts(session, SendMessage)[-1].text


@pytest.mark.skipif(ff.locate("ffmpeg") is None, reason="ffmpeg не найден")
async def test_local_mode_moves_file_from_bot_api_cache(env, tmp_path):
    """В local-режиме исходник забирается с диска сервера (move), кеш сервера не остаётся."""
    dp, bot, session, ctx = env
    ctx.cfg.local_mode = True
    cache = tmp_path / "botapi" / "videos"
    cache.mkdir(parents=True)
    src = cache / "file_1.mp4"
    subprocess.run([ff.require("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    session.src_file = str(src)
    ctx.queue.start()
    v = Video(file_id="v", file_unique_id="vu", width=160, height=120, duration=1, file_size=src.stat().st_size)
    await dp.feed_update(bot, _msg(ALLOWED, video=v))
    for _ in range(200):
        await asyncio.sleep(0.1)
        if not ctx.queue.running and not ctx.queue.pending:
            break
    await asyncio.sleep(0.3)
    await ctx.queue.stop()
    assert not src.exists()                          # кеш сервера освобождён
    assert not os.listdir(ctx.cfg.tmp_dir)           # наш tmp пуст
    assert len(_texts(session, SendVideo)) == 1


def test_sweep_dir(tmp_path):
    from viduniq.bot.queue import sweep_dir
    old = tmp_path / "a" / "b" / "old.bin"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x")
    os.utime(old, (1, 1))
    fresh = tmp_path / "fresh.bin"
    fresh.write_bytes(b"y")
    assert sweep_dir(str(tmp_path), 3600) == 1
    assert fresh.exists() and not old.exists() and not (tmp_path / "a").exists()
    assert sweep_dir(str(tmp_path / "missing"), 1) == 0


async def test_stranger_gets_one_reply_then_silence_and_block(env):
    dp, bot, session, ctx = env
    for i in range(12):
        await dp.feed_update(bot, _msg(STRANGER, f"hi {i}"))
    sent = _texts(session, SendMessage)
    assert len(sent) == 1 and "200" in sent[0].text          # ответили ровно один раз
    assert ctx.access.is_blocked(STRANGER.id)
    await dp.feed_update(bot, _cb(STRANGER, "m"))            # и на кнопки чужого не реагируем
    assert len(session.calls) == 1


async def test_admin_commands_hidden_from_regular_users(env):
    dp, bot, session, ctx = env
    await dp.feed_update(bot, _msg(ALLOWED, "/adduser 555"))
    assert not _texts(session, SendMessage)                  # обычный пользователь — тишина
    assert not ctx.access.is_allowed(555)

    ctx.access.admins.add(ALLOWED.id)
    await dp.feed_update(bot, _msg(ALLOWED, "/adduser 555"))
    assert ctx.access.is_allowed(555) and "добавлен" in _texts(session, SendMessage)[-1].text
    await dp.feed_update(bot, _msg(User(id=555, is_bot=False, first_name="New"), "/id"))
    assert "555" in _texts(session, SendMessage)[-1].text     # новый пользователь пущен
    await dp.feed_update(bot, _msg(ALLOWED, "/listusers"))
    text = _texts(session, SendMessage)[-1].text
    assert "555" in text and "Админы" in text and str(ALLOWED.id) in text
    await dp.feed_update(bot, _msg(ALLOWED, "/deluser 555"))
    assert not ctx.access.is_allowed(555)
    await dp.feed_update(bot, _msg(ALLOWED, "/blockuser 555"))
    assert ctx.access.is_blocked(555)
    await dp.feed_update(bot, _msg(ALLOWED, f"/deluser {ALLOWED.id}"))
    assert "нельзя" in _texts(session, SendMessage)[-1].text
    await dp.feed_update(bot, _msg(ALLOWED, "/adduser abc"))
    assert "Использование" in _texts(session, SendMessage)[-1].text
