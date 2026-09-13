"""Telegram-слой: команды, медиа, callback-кнопки, статусные сообщения."""
from __future__ import annotations

import asyncio
import html
import logging
import os
import shutil
import time
from dataclasses import replace
from typing import Any, Awaitable, Callable, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message, TelegramObject

from .. import __version__
from ..core import ffmpeg as ff
from ..core.constants import OVERLAY_EXTENSIONS, VALID_INPUT_EXTENSIONS
from ..core.uniq import Strength
from . import keyboards as kb
from .access import AccessStore
from .config import Config
from .queue import ProcessingQueue, Task
from .store import SPEED_CHOICES, ZOOM_CHOICES, PrefsStore

log = logging.getLogger(__name__)

HELP = (
    "<b>VidUniq</b> — уникализатор видео для Reels, TikTok, Shorts и других соцсетей.\n\n"
    "Пришлите видео или GIF — верну обработанную копию с вашими настройками.\n"
    "Несколько файлов можно слать подряд, они встанут в очередь.\n\n"
    "Режим уникализации (мягкая / средняя / сильная) сам подбирает случайные малозаметные изменения "
    "для каждого файла: zoom, скорость, поворот, обрезка начала, цвет, шум, тон звука, метаданные. "
    "В подписи к результату видно, что применилось и насколько кадры отличаются от оригинала.\n\n"
    "<b>Команды</b>\n"
    "/settings — режим уникализации, формат, фильтры, наложение, звук, число вариантов\n"
    "/overlay — как добавить картинку/GIF поверх видео\n"
    "/cancel — отменить мои задачи\n"
    "/queue — что сейчас в очереди\n"
    "/reset — сбросить настройки\n"
    "/id — мой Telegram ID\n\n"
    "💡 Чтобы Telegram не пережимал исходник, отправляйте видео <b>как файл</b> (📎 → Файл)."
)


class Ctx:
    """Общие зависимости хендлеров."""

    def __init__(self, cfg: Config, store: PrefsStore, queue: ProcessingQueue, access: Optional[AccessStore] = None):
        self.cfg = cfg
        self.store = store
        self.queue = queue
        self.access = access or AccessStore(cfg.access_path, cfg.allowed_users, cfg.admin_users)
        self.bot: Bot | None = None
        self._last_edit: dict[str, float] = {}
        self._last_text: dict[str, str] = {}


async def fetch_file(bot: Bot, cfg: Config, file_id: str, dest: str) -> None:
    """Забирает файл в dest. В local-режиме — переносит с диска Bot API сервера, чтобы не оставлять копию."""
    f = await bot.get_file(file_id)
    path = f.file_path or ""
    if cfg.local_mode and os.path.isabs(path) and os.path.isfile(path):
        try:
            os.replace(path, dest)               # один том → мгновенно
        except OSError:
            shutil.copyfile(path, dest)          # разные тома → копия + удаление оригинала
            try:
                os.remove(path)
            except OSError:
                log.warning("Не удалось удалить кеш Bot API: %s", path)
        return
    await bot.download_file(path, destination=dest)


def build_router(ctx: Ctx) -> Router:
    r = Router(name="viduniq")

    # ------------------------------------------------------------ доступ
    async def access_mw(handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                        event: TelegramObject, data: dict[str, Any]):
        user = data.get("event_from_user")
        if user is None:
            return None
        acc = ctx.access
        if acc.is_allowed(user.id):
            acc.touch(user.id, user.username or user.full_name)
            return await handler(event, data)
        # Чужой: отвечаем с ID только на самую первую попытку, дальше — полный игнор;
        # после MAX_STRANGER_ATTEMPTS попыток — постоянная блокировка (даже не считаем).
        if isinstance(event, Message) and acc.stranger_attempt(user.id):
            await event.answer(f"⛔ Доступ закрыт.\nВаш ID: <code>{user.id}</code> — передайте его администратору бота.")
        return None

    r.message.outer_middleware(access_mw)
    r.callback_query.outer_middleware(access_mw)

    # ------------------------------------------------------------ команды
    @r.message(CommandStart())
    @r.message(Command("help"))
    async def cmd_start(m: Message):
        await m.answer(HELP)
        await m.answer("Текущие настройки:\n\n" + ctx.store.get(m.from_user.id).summary(),
                       reply_markup=kb.main_menu(ctx.store.get(m.from_user.id)))

    @r.message(Command("settings"))
    async def cmd_settings(m: Message):
        p = ctx.store.get(m.from_user.id)
        await m.answer("⚙️ <b>Настройки</b>\n\n" + p.summary(), reply_markup=kb.main_menu(p))

    @r.message(Command("id"))
    async def cmd_id(m: Message):
        await m.answer(f"Ваш ID: <code>{m.from_user.id}</code>")

    @r.message(Command("overlay"))
    async def cmd_overlay(m: Message):
        p = ctx.store.get(m.from_user.id)
        state = f"Сейчас: <b>{'есть · ' + p.overlay_pos if p.overlay_path else 'нет'}</b>."
        await m.answer(
            "🖼 Пришлите <b>картинку</b> (PNG/JPG/WEBP, лучше как файл — сохранится прозрачность) "
            "или <b>GIF</b> — она станет наложением поверх видео.\n"
            "Позиция выбирается в /settings → Наложение. Убрать: /overlay_off\n\n" + state
        )

    @r.message(Command("overlay_off"))
    async def cmd_overlay_off(m: Message):
        p = ctx.store.get(m.from_user.id)
        _drop_overlay(p)
        ctx.store.save(m.from_user.id, replace(p, overlay_path=None))
        await m.answer("Наложение убрано.")

    @r.message(Command("reset"))
    async def cmd_reset(m: Message):
        p = ctx.store.reset(m.from_user.id)
        await m.answer("Настройки сброшены.\n\n" + p.summary(), reply_markup=kb.main_menu(p))

    @r.message(Command("cancel"))
    async def cmd_cancel(m: Message):
        n = ctx.queue.cancel_user(m.from_user.id)
        await m.answer(f"Отменено задач: {n}" if n else "У вас нет активных задач.")

    @r.message(Command("queue"))
    async def cmd_queue(m: Message):
        running, pending = ctx.queue.running, ctx.queue.pending
        if not running and not pending:
            await m.answer("Очередь пуста.")
            return
        lines = []
        for t in running:
            mine = " (ваш)" if t.user_id == m.from_user.id else ""
            lines.append(f"⚙️ {html.escape(t.src_name)}{mine} — {int(t.progress * 100)}%")
        for i, t in enumerate(pending, 1):
            mine = " (ваш)" if t.user_id == m.from_user.id else ""
            lines.append(f"{i}. ⏳ {html.escape(t.src_name)}{mine}")
        await m.answer("\n".join(lines))

    # ------------------------------------------------------------ админ (скрытые команды)
    def _admin_only(m: Message) -> bool:
        return ctx.access.is_admin(m.from_user.id)

    def _parse_id(m: Message) -> Optional[int]:
        parts = (m.text or "").split()
        if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
            return int(parts[1])
        return None

    @r.message(Command("adduser"))
    async def cmd_adduser(m: Message):
        if not _admin_only(m):
            return
        uid = _parse_id(m)
        if uid is None:
            await m.answer("Использование: <code>/adduser 123456789</code>")
            return
        added = ctx.access.add(uid)
        await m.answer(f"✅ <code>{uid}</code> добавлен." if added else f"<code>{uid}</code> уже был в списке.")

    @r.message(Command("deluser"))
    async def cmd_deluser(m: Message):
        if not _admin_only(m):
            return
        uid = _parse_id(m)
        if uid is None:
            await m.answer("Использование: <code>/deluser 123456789</code>")
            return
        if ctx.access.is_admin(uid):
            await m.answer("Администратора убрать нельзя (ADMIN_USERS в .env).")
            return
        ctx.queue.cancel_user(uid)
        removed = ctx.access.remove(uid)
        await m.answer(f"🚫 <code>{uid}</code> удалён." if removed else f"<code>{uid}</code> не было в списке.")

    @r.message(Command("blockuser"))
    async def cmd_blockuser(m: Message):
        if not _admin_only(m):
            return
        uid = _parse_id(m)
        if uid is None or ctx.access.is_admin(uid):
            await m.answer("Использование: <code>/blockuser 123456789</code>")
            return
        ctx.queue.cancel_user(uid)
        ctx.access.block(uid)
        await m.answer(f"⛔ <code>{uid}</code> заблокирован навсегда (снять: /adduser).")

    @r.message(Command("listusers"))
    async def cmd_listusers(m: Message):
        if not _admin_only(m):
            return
        snap = ctx.access.snapshot()
        now = time.time()

        def ago(ts: float) -> str:
            if not ts:
                return "не заходил"
            d = int(now - ts)
            if d < 3600:
                return f"{d // 60} мин назад"
            if d < 86400:
                return f"{d // 3600} ч назад"
            return f"{d // 86400} дн назад"

        lines = ["👑 Админы: " + ", ".join(f"<code>{u}</code>" for u in snap["admins"]), "", "✅ Разрешены:"]
        for uid, st in snap["allowed"]:
            name = f" @{html.escape(st.name)}" if st.name and not st.name.startswith("@") and " " not in st.name else (f" {html.escape(st.name)}" if st.name else "")
            lines.append(f"• <code>{uid}</code>{name} — {ago(st.last_seen)}, файлов: {st.files}")
        if not snap["allowed"]:
            lines.append("• (пусто)")
        if snap["blocked"]:
            lines += ["", "⛔ Заблокированы: " + ", ".join(f"<code>{u}</code>" for u in snap["blocked"])]
        if snap["strangers"]:
            lines += ["", "👀 Стучались: " + ", ".join(f"<code>{u}</code> ×{n}" for u, n in snap["strangers"].items())]
        await m.answer("\n".join(lines))

    # ------------------------------------------------------------ медиа
    def _media_of(m: Message):
        """Возвращает (file_obj, filename, size) для видео/GIF или None."""
        if m.video:
            return m.video, m.video.file_name or f"video_{m.video.file_unique_id}.mp4", m.video.file_size
        if m.animation:
            return m.animation, m.animation.file_name or f"anim_{m.animation.file_unique_id}.mp4", m.animation.file_size
        if m.document:
            d = m.document
            name = d.file_name or ""
            ext = os.path.splitext(name)[1].lower()
            mime = (d.mime_type or "").lower()
            if ext in VALID_INPUT_EXTENSIONS or mime.startswith("video/") or mime == "image/gif":
                return d, name or f"file_{d.file_unique_id}.mp4", d.file_size
        return None

    def _image_of(m: Message):
        if m.photo:
            return m.photo[-1], f"overlay_{m.from_user.id}.jpg"
        if m.document:
            d = m.document
            ext = os.path.splitext(d.file_name or "")[1].lower()
            if ext in OVERLAY_EXTENSIONS and ext != ".gif":
                return d, f"overlay_{m.from_user.id}{ext}"
            if (d.mime_type or "").startswith("image/") and (d.mime_type or "") != "image/gif":
                return d, f"overlay_{m.from_user.id}.png"
        return None

    @r.message(F.video | F.animation | F.document)
    async def on_media(m: Message, bot: Bot):
        media = _media_of(m)
        if media is None:
            img = _image_of(m)
            if img is not None:
                await _set_overlay(m, bot, *img)
                return
            await m.answer("Не понял формат. Пришлите видео (mp4/mov/…), GIF или картинку для наложения.")
            return
        file_obj, name, size = media
        # GIF-анимация с caption «overlay» — это наложение, а не входное видео
        if m.animation and (m.caption or "").strip().lower() in ("overlay", "наложение"):
            await _set_overlay(m, bot, file_obj, f"overlay_{m.from_user.id}.gif")
            return
        if size and size > ctx.cfg.max_file_mb * 1024 * 1024:
            await m.answer(f"Файл слишком большой: {size / 1e6:.0f} МБ, лимит {ctx.cfg.max_file_mb} МБ.")
            return
        if ctx.queue.pending_for(m.from_user.id) >= ctx.queue.max_pending_per_user:
            await m.answer(f"У вас уже {ctx.queue.max_pending_per_user} файлов в очереди — дождитесь их.")
            return

        status = await m.reply("⬇️ Получаю файл…")
        ext = os.path.splitext(name)[1].lower() or ".mp4"
        safe_name = os.path.basename(name).replace("/", "_") or f"input{ext}"
        prefs = ctx.store.get(m.from_user.id)
        task = Task(user_id=m.from_user.id, chat_id=m.chat.id, src_path="", src_name=safe_name,
                    prefs=replace(prefs), status_msg_id=status.message_id)
        task.src_path = os.path.join(ctx.cfg.tmp_dir, f"{task.id}_in{ext}")
        try:
            await fetch_file(bot, ctx.cfg, file_obj.file_id, task.src_path)
        except Exception as e:  # noqa: BLE001
            log.exception("download failed")
            await _edit(status, f"❌ Не удалось скачать файл: {html.escape(str(e))[:300]}")
            return
        try:
            pos = ctx.queue.submit(task)
        except RuntimeError as e:
            ctx.queue.cleanup(task)
            await _edit(status, f"❌ {e}")
            return
        await _edit(status, _status_text(task, pos), kb.cancel_kb(task.id))

    @r.message(F.photo)
    async def on_photo(m: Message, bot: Bot):
        img = _image_of(m)
        if img:
            await _set_overlay(m, bot, *img)

    async def _set_overlay(m: Message, bot: Bot, file_obj, filename: str):
        p = ctx.store.get(m.from_user.id)
        _drop_overlay(p)
        dest = os.path.join(ctx.cfg.users_dir, filename)
        try:
            await fetch_file(bot, ctx.cfg, file_obj.file_id, dest)
        except Exception as e:  # noqa: BLE001
            await m.answer(f"❌ Не удалось сохранить картинку: {html.escape(str(e))[:200]}")
            return
        p = replace(p, overlay_path=dest)
        ctx.store.save(m.from_user.id, p)
        await m.answer(f"🖼 Наложение установлено (позиция: {p.overlay_pos}). Изменить позицию или убрать:",
                       reply_markup=kb.overlay_menu(p))

    def _drop_overlay(p):
        if p.overlay_path and os.path.exists(p.overlay_path):
            try:
                os.remove(p.overlay_path)
            except OSError:
                pass

    # ------------------------------------------------------------ callback-кнопки
    @r.callback_query(F.data == "noop")
    async def cb_noop(c: CallbackQuery):
        await c.answer()

    @r.callback_query(F.data == "close")
    async def cb_close(c: CallbackQuery):
        await c.answer()
        try:
            await c.message.delete()
        except TelegramBadRequest:
            pass

    @r.callback_query(F.data.startswith("x:"))
    async def cb_cancel_task(c: CallbackQuery):
        ok = ctx.queue.cancel_task(c.data[2:], c.from_user.id)
        await c.answer("Отменяю…" if ok else "Задача уже завершена")

    @r.callback_query()
    async def cb_settings(c: CallbackQuery):
        uid = c.from_user.id
        p = ctx.store.get(uid)
        data = c.data or ""
        parts = data.split(":")
        key = parts[0]
        text, markup = None, None

        if key == "m":
            text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        elif key == "um":
            text, markup = kb.strength_text(p), kb.strength_menu(p)
        elif key == "u":
            p = replace(p, strength=Strength.parse(parts[1]).value)
            text, markup = kb.strength_text(p), kb.strength_menu(p)
        elif key == "pp":
            text, markup = "📐 <b>Формат вывода</b>", kb.presets_menu(p, int(parts[1]))
        elif key == "p":
            p = replace(p, preset_slug=parts[1])
            text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        elif key == "pb":
            p = replace(p, blur_bg=not p.blur_bg)
            text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        elif key == "fm":
            text, markup = "🎨 <b>Фильтры</b> — можно выбрать несколько", kb.filters_menu(p, int(parts[1]))
        elif key == "f":
            name = kb.FILTER_NAMES[int(parts[1])]
            fl = [f for f in p.filters if f != name] if name in p.filters else p.filters + [name]
            p = replace(p, filters=fl)
            text, markup = "🎨 <b>Фильтры</b> — можно выбрать несколько", kb.filters_menu(p, int(parts[2]))
        elif key == "fc":
            p = replace(p, filters=[])
            text, markup = "🎨 <b>Фильтры</b> — можно выбрать несколько", kb.filters_menu(p, 0)
        elif key == "zm":
            text, markup = "🔍 <b>Zoom</b> — диапазон означает случайное значение для каждого файла", kb.zoom_menu(p)
        elif key == "z":
            val, rng = list(ZOOM_CHOICES.values())[int(parts[1])]
            p = replace(p, zoom=val, zoom_range=rng)
            text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        elif key == "sm":
            text, markup = "⏩ <b>Скорость</b> — диапазон означает случайное значение для каждого файла", kb.speed_menu(p)
        elif key == "s":
            val, rng = list(SPEED_CHOICES.values())[int(parts[1])]
            p = replace(p, speed=val, speed_range=rng)
            text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        elif key == "om":
            text = ("🖼 <b>Наложение</b>\n\nВыберите позицию:" if p.overlay_path
                    else "🖼 <b>Наложение</b>\n\nПришлите картинку (PNG/JPG/WEBP) или GIF с подписью «overlay».")
            markup = kb.overlay_menu(p)
        elif key == "o":
            p = replace(p, overlay_pos=kb.POS_NAMES[int(parts[1])])
            text, markup = "🖼 <b>Наложение</b>\n\nВыберите позицию:", kb.overlay_menu(p)
        elif key == "od":
            _drop_overlay(p)
            p = replace(p, overlay_path=None)
            text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        elif key == "t":
            if parts[1] == "mute":
                p = replace(p, mute=not p.mute)
            elif parts[1] == "meta":
                p = replace(p, strip_metadata=not p.strip_metadata)
            elif parts[1] == "mirror":
                p = replace(p, mirror=not p.mirror)
            elif parts[1] == "audio":
                p = replace(p, touch_audio=not p.touch_audio)
            if parts[1] in ("mirror", "audio"):
                text, markup = kb.strength_text(p), kb.strength_menu(p)
            else:
                text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        elif key == "vm":
            text, markup = ("🔁 <b>Вариантов на файл</b> — каждый со своими случайными zoom/скоростью/цветом",
                            kb.variants_menu(p, ctx.cfg.max_variants))
        elif key == "v":
            p = replace(p, variants=max(1, min(ctx.cfg.max_variants, int(parts[1]))))
            text, markup = "⚙️ <b>Настройки</b>\n\n" + p.summary(), kb.main_menu(p)
        else:
            await c.answer()
            return

        ctx.store.save(uid, p)
        await c.answer()
        try:
            await c.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                raise

    # ------------------------------------------------------------ статусы очереди
    def _status_text(task: Task, pos: int) -> str:
        name = html.escape(task.src_name)
        if pos > 0:
            return f"⏳ <b>{name}</b>\nВ очереди: {pos}-й"
        var = f" · вариант {task.variant}/{task.variants}" if task.variants > 1 else ""
        bar = _bar(task.progress)
        return f"⚙️ <b>{name}</b>\n{bar} {int(task.progress * 100)}%{var}\n{task.prefs.preset.label}"

    async def on_progress(task: Task):
        pos = ctx.queue.position(task)
        await _edit_status(task, _status_text(task, pos), kb.cancel_kb(task.id))

    async def on_done(task: Task):
        bot = ctx.bot
        assert bot is not None
        name = html.escape(task.src_name)
        if task.error:
            icon = "🚫" if task.error == "Отменено" else "❌"
            await _edit_status(task, f"{icon} <b>{name}</b>\n{html.escape(task.error)}", None, force=True)
            return
        await _edit_status(task, f"📤 <b>{name}</b>\nОтправляю результат…", None, force=True)
        sent = 0
        for i, out in enumerate(task.outputs, 1):
            try:
                info = ff.probe(out)
            except Exception:  # noqa: BLE001
                info = ff.MediaInfo()
            desc = task.applied[i - 1] if i - 1 < len(task.applied) else task.prefs.preset.label
            cap = ("✅ " + (f"Вариант {i}/{len(task.outputs)}\n" if len(task.outputs) > 1 else "") + html.escape(desc))[:1000]
            fname = os.path.basename(out)
            try:
                await bot.send_video(
                    task.chat_id, FSInputFile(out, filename=fname), caption=cap,
                    width=info.width or None, height=info.height or None,
                    duration=int(info.duration) or None, supports_streaming=True,
                    request_timeout=600,
                )
                sent += 1
            except Exception as e:  # noqa: BLE001
                log.exception("send_video failed")
                await bot.send_message(task.chat_id, f"❌ Не удалось отправить {html.escape(fname)}: {html.escape(str(e))[:300]}")
        elapsed = time.time() - task.started_at
        ctx.access.touch(task.user_id, files=1)
        await _edit_status(task, f"✅ <b>{name}</b>\nГотово: {sent} из {len(task.outputs)} · {elapsed:.0f} с", None, force=True)

    async def _edit_status(task: Task, text: str, markup, force: bool = False):
        if not task.status_msg_id or ctx.bot is None:
            return
        key = f"{task.chat_id}:{task.status_msg_id}"
        now = time.time()
        if not force and now - ctx._last_edit.get(key, 0) < ctx.cfg.progress_interval - 0.1:
            return
        if ctx._last_text.get(key) == text:
            return
        ctx._last_edit[key] = now
        ctx._last_text[key] = text
        try:
            await ctx.bot.edit_message_text(text, chat_id=task.chat_id, message_id=task.status_msg_id,
                                            reply_markup=markup)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                log.debug("edit_message_text: %s", e)
        except Exception:  # noqa: BLE001
            log.debug("edit_message_text failed", exc_info=True)

    async def _edit(msg: Message, text: str, markup=None):
        try:
            await msg.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            pass

    ctx.queue.on_progress = on_progress
    ctx.queue.on_done = on_done
    return r


def _bar(frac: float, width: int = 12) -> str:
    n = int(round(max(0.0, min(1.0, frac)) * width))
    return "▓" * n + "░" * (width - n)
