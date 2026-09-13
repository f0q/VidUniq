"""Очередь обработки: asyncio + пул потоков для ffmpeg. Не зависит от aiogram."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from ..core import ffmpeg as ff
from ..core.batch import process_file, remove_quiet
from .store import UserPrefs

log = logging.getLogger(__name__)


@dataclass
class Task:
    user_id: int
    chat_id: int
    src_path: str
    src_name: str
    prefs: UserPrefs
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status_msg_id: Optional[int] = None
    cancel: threading.Event = field(default_factory=threading.Event)
    progress: float = 0.0          # 0..1 внутри текущего варианта
    variant: int = 0               # текущий вариант (1-based) во время работы
    outputs: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)   # описание параметров каждого варианта
    error: Optional[str] = None
    started_at: float = 0.0
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def variants(self) -> int:
        return max(1, self.prefs.variants)


# Колбэки, которые задаёт слой Telegram
OnQueued = Callable[[Task, int], Awaitable[None]]           # task, позиция в очереди
OnProgress = Callable[[Task], Awaitable[None]]
OnDone = Callable[[Task], Awaitable[None]]


class ProcessingQueue:
    def __init__(self, tmp_dir: str, max_parallel: int = 1, progress_interval: float = 3.0,
                 max_pending_per_user: int = 5):
        self.tmp_dir = tmp_dir
        self.max_parallel = max_parallel
        self.progress_interval = progress_interval
        self.max_pending_per_user = max_pending_per_user
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._pending: list[Task] = []
        self._running: dict[str, Task] = {}
        self._workers: list[asyncio.Task] = []
        self.on_progress: Optional[OnProgress] = None
        self.on_done: Optional[OnDone] = None
        self._rng = random.Random()
        os.makedirs(tmp_dir, exist_ok=True)

    # --- жизненный цикл ---
    def start(self):
        for i in range(self.max_parallel):
            self._workers.append(asyncio.create_task(self._worker(i), name=f"viduniq-worker-{i}"))

    async def stop(self):
        for t in self._workers:
            t.cancel()
        for t in list(self._running.values()):
            t.cancel.set()
        await asyncio.gather(*self._workers, return_exceptions=True)

    # --- API ---
    def pending_for(self, user_id: int) -> int:
        return sum(1 for t in self._pending if t.user_id == user_id) + \
            sum(1 for t in self._running.values() if t.user_id == user_id)

    def position(self, task: Task) -> int:
        """1-based позиция в очереди ожидания (0 — уже выполняется)."""
        if task.id in self._running:
            return 0
        try:
            return self._pending.index(task) + 1
        except ValueError:
            return 0

    def submit(self, task: Task) -> int:
        if self.pending_for(task.user_id) >= self.max_pending_per_user:
            raise RuntimeError(f"У вас уже {self.max_pending_per_user} файлов в очереди — дождитесь их.")
        self._pending.append(task)
        self._queue.put_nowait(task)
        return len(self._pending)

    def cancel_user(self, user_id: int) -> int:
        """Отменяет все задачи пользователя (в очереди и выполняющиеся). Возвращает число."""
        n = 0
        for t in list(self._pending):
            if t.user_id == user_id:
                t.cancel.set()
                n += 1
        for t in self._running.values():
            if t.user_id == user_id and not t.cancel.is_set():
                t.cancel.set()
                n += 1
        return n

    def cancel_task(self, task_id: str, user_id: int) -> bool:
        for t in list(self._pending) + list(self._running.values()):
            if t.id == task_id and t.user_id == user_id:
                t.cancel.set()
                return True
        return False

    @property
    def running(self) -> list[Task]:
        return list(self._running.values())

    @property
    def pending(self) -> list[Task]:
        return list(self._pending)

    # --- воркер ---
    async def _worker(self, n: int):
        loop = asyncio.get_running_loop()
        while True:
            task = await self._queue.get()
            try:
                self._pending.remove(task)
            except ValueError:
                pass
            if task.cancel.is_set():
                task.error = "Отменено"
                await self._finish(task)
                continue
            self._running[task.id] = task
            task.started_at = time.time()
            try:
                await self._run_task(loop, task)
            except Exception as e:  # noqa: BLE001
                log.exception("Задача %s упала", task.id)
                task.error = str(e)
            finally:
                self._running.pop(task.id, None)
                await self._finish(task)

    async def _run_task(self, loop: asyncio.AbstractEventLoop, task: Task):
        out_dir = os.path.join(self.tmp_dir, task.id)
        job = task.prefs.to_job()
        for v in range(1, task.variants + 1):
            if task.cancel.is_set():
                task.error = "Отменено"
                break
            task.variant = v
            task.progress = 0.0

            def _prog(frac: float):
                task.progress = frac

            fut = loop.run_in_executor(
                None, lambda: process_file(
                    task.src_path, out_dir, job,
                    zoom_range=task.prefs.zoom_range, speed_range=task.prefs.speed_range,
                    on_progress=_prog, cancel=task.cancel, rng=self._rng,
                ),
            )
            while True:
                done, _ = await asyncio.wait([fut], timeout=self.progress_interval)
                if self.on_progress and not task.cancel.is_set():
                    try:
                        await self.on_progress(task)
                    except Exception:  # noqa: BLE001
                        log.debug("on_progress упал", exc_info=True)
                if done:
                    break
            try:
                res = fut.result()
                task.outputs.append(res.out_path)
                task.applied.append(f"{task.prefs.preset.label} · {res.summary}")
            except ff.Cancelled:
                task.error = "Отменено"
                break
            except ff.FFmpegError as e:
                task.error = f"ffmpeg: {e.tail[-300:] or 'код ' + str(e.code)}"
                break
            except Exception as e:  # noqa: BLE001
                task.error = str(e)
                break

    async def _finish(self, task: Task):
        if self.on_done:
            try:
                await self.on_done(task)
            except Exception:  # noqa: BLE001
                log.exception("on_done упал для %s", task.id)
        self.cleanup(task)
        task.done_event.set()

    def cleanup(self, task: Task):
        remove_quiet(task.src_path)
        shutil.rmtree(os.path.join(self.tmp_dir, task.id), ignore_errors=True)

    def purge_stale(self, max_age_sec: int = 86400):
        """Удаляет мусор в tmp старше суток (после падений)."""
        sweep_dir(self.tmp_dir, max_age_sec, recursive=False)


def sweep_dir(root: str, max_age_sec: float, recursive: bool = True) -> int:
    """Удаляет файлы (и пустые папки) старше max_age_sec. Возвращает число удалённых файлов."""
    if not root or not os.path.isdir(root):
        return 0
    now = time.time()
    removed = 0
    if not recursive:
        for name in os.listdir(root):
            p = os.path.join(root, name)
            try:
                if now - os.path.getmtime(p) > max_age_sec:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                    removed += 1
            except OSError:
                pass
        return removed
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            p = os.path.join(dirpath, name)
            try:
                if now - os.path.getmtime(p) > max_age_sec:
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
        if dirpath != root:
            try:
                os.rmdir(dirpath)          # только если пустая
            except OSError:
                pass
    return removed
