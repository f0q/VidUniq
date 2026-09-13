"""Фоновая обработка очереди файлов для GUI (QThread поверх core.batch)."""
from __future__ import annotations

import logging
import os
import random
import threading
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QThread, Signal

from . import ffmpeg as ff
from .batch import process_file
from .ffmpeg import JobSettings

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
            out_dir = self.settings.out_dir or os.path.join(os.path.dirname(src), "uniq")
            try:
                out_path = process_file(
                    src, out_dir, self.settings.job,
                    zoom_range=self.settings.zoom_range, speed_range=self.settings.speed_range,
                    on_progress=lambda frac, i=idx: self.file_progress.emit(i, frac),
                    cancel=self._cancel, rng=self._rng, ffmpeg_bin=ffmpeg_bin,
                )
                summary.done.append(out_path)
                summary.out_dirs.add(out_dir)
                self.file_done.emit(idx, out_path)
            except ff.Cancelled:
                summary.cancelled = True
                self.file_failed.emit(idx, "Отменено")
                break
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                log.exception("Ошибка при обработке %s", src)
                summary.failed[src] = msg
                self.file_failed.emit(idx, msg)
        self.batch_finished.emit(summary)
