"""Фоновая обработка очереди файлов."""
from __future__ import annotations

import logging
import os
import random
import threading
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QThread, Signal

from . import ffmpeg as ff
from .ffmpeg import JobSettings, MediaInfo

log = logging.getLogger(__name__)


@dataclass
class BatchSettings:
    job: JobSettings
    out_dir: Optional[str]          # None → рядом с исходником в подпапке uniq/
    zoom_range: Optional[tuple[int, int]] = None
    speed_range: Optional[tuple[int, int]] = None


@dataclass
class BatchSummary:
    done: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    cancelled: bool = False
    out_dirs: set[str] = field(default_factory=set)


def unique_out_path(out_dir: str, name: str, slug: str) -> str:
    base = f"{name}_{slug}"
    p = os.path.join(out_dir, base + ".mp4")
    n = 1
    while os.path.exists(p):
        p = os.path.join(out_dir, f"{base}_{n}.mp4")
        n += 1
    return p


class Worker(QThread):
    file_started = Signal(int)
    file_progress = Signal(int, float)      # idx, 0..1
    file_done = Signal(int, str)            # idx, out_path
    file_failed = Signal(int, str)          # idx, message
    batch_finished = Signal(object)         # BatchSummary

    def __init__(self, files: list[str], settings: BatchSettings, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.settings = settings
        self._cancel = threading.Event()
        self._rng = random.Random()

    def cancel(self):
        self._cancel.set()

    def _pick(self, base: int, rng: Optional[tuple[int, int]]) -> int:
        if rng and rng[1] >= rng[0]:
            return self._rng.randint(rng[0], rng[1])
        return base

    def run(self):
        summary = BatchSummary()
        try:
            ffmpeg_bin = ff.require("ffmpeg")
            ff.require("ffprobe")
        except ff.FFmpegNotFound as e:
            for i in range(len(self.files)):
                self.file_failed.emit(i, str(e))
                summary.failed[self.files[i]] = str(e)
            self.batch_finished.emit(summary)
            return

        for idx, src in enumerate(self.files):
            if self._cancel.is_set():
                summary.cancelled = True
                break
            self.file_started.emit(idx)
            out_path = None
            try:
                out_dir = self.settings.out_dir or os.path.join(os.path.dirname(src), "uniq")
                os.makedirs(out_dir, exist_ok=True)
                info: MediaInfo = ff.probe(src)
                if info.width == 0 or info.height == 0:
                    raise RuntimeError("Не удалось определить размер видео")

                job = JobSettings(**vars(self.settings.job))
                job.zoom = self._pick(job.zoom, self.settings.zoom_range)
                job.speed = self._pick(job.speed, self.settings.speed_range)

                name = os.path.splitext(os.path.basename(src))[0]
                out_path = unique_out_path(out_dir, name, job.preset.slug)
                total = ff.expected_duration(info, job)

                def _prog(frac: float, i=idx):
                    self.file_progress.emit(i, frac)

                cmd = ff.build_command(ffmpeg_bin, src, out_path, info, job, self._rng)
                try:
                    ff.run_with_progress(cmd, total, _prog, self._cancel)
                except ff.FFmpegError as e:
                    if job.hw_encode:
                        log.warning("VideoToolbox не справился, повтор через libx264: %s", e.tail[-200:])
                        job.hw_encode = False
                        cmd = ff.build_command(ffmpeg_bin, src, out_path, info, job, self._rng)
                        ff.run_with_progress(cmd, total, _prog, self._cancel)
                    else:
                        raise
                summary.done.append(out_path)
                summary.out_dirs.add(out_dir)
                self.file_done.emit(idx, out_path)
            except ff.Cancelled:
                self._remove_partial(out_path)
                summary.cancelled = True
                self.file_failed.emit(idx, "Отменено")
                break
            except Exception as e:  # noqa: BLE001
                self._remove_partial(out_path)
                msg = str(e)
                log.exception("Ошибка при обработке %s", src)
                summary.failed[src] = msg
                self.file_failed.emit(idx, msg)
        self.batch_finished.emit(summary)

    @staticmethod
    def _remove_partial(path: Optional[str]):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
