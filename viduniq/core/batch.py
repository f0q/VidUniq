"""Обработка одного файла: probe → уникализация/случайные zoom-speed → ffmpeg → откат hw. Без Qt."""
from __future__ import annotations

import logging
import os
import random
import threading
from dataclasses import dataclass, replace
from typing import Callable, Optional

from . import ffmpeg as ff
from .ffmpeg import JobSettings, MediaInfo
from .uniq import Strength, UniqParams, describe, roll

log = logging.getLogger(__name__)

Range = Optional[tuple[int, int]]


@dataclass
class ProcessResult:
    out_path: str
    params: Optional[UniqParams] = None     # что применилось (None — ручной режим без метаданных)
    difference: Optional[float] = None      # 0..1, отличие от оригинала по кадрам

    @property
    def summary(self) -> str:
        text = describe(self.params) if self.params else "ручные настройки"
        if self.difference is not None:
            text += f" · отличие {self.difference * 100:.0f}%"
        return text


def unique_out_path(out_dir: str, name: str, slug: str, ext: str = ".mp4") -> str:
    base = f"{name}_{slug}"
    p = os.path.join(out_dir, base + ext)
    n = 1
    while os.path.exists(p):
        p = os.path.join(out_dir, f"{base}_{n}{ext}")
        n += 1
    return p


def pick(base: int, rng_range: Range, rng: random.Random) -> int:
    if rng_range and rng_range[1] >= rng_range[0]:
        return rng.randint(rng_range[0], rng_range[1])
    return base


def remove_quiet(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def prepare_job(job: JobSettings, zoom_range: Range, speed_range: Range, rng: random.Random,
                info: Optional[MediaInfo] = None) -> JobSettings:
    """Бросает кубики: режим уникализации или ручные диапазоны zoom/speed."""
    if job.uniq is not None:
        return job
    if job.strength != Strength.OFF:
        params = roll(job.strength, rng, mirror_mode=job.mirror_mode, touch_audio=job.touch_audio,
                      source_fps=info.fps if info else 30.0)
        return replace(job, uniq=params)
    job = replace(job, zoom=pick(job.zoom, zoom_range, rng), speed=pick(job.speed, speed_range, rng))
    if job.strip_metadata or job.mirror_mode != "never":
        # ручной режим: только подмена метаданных / зеркало
        params = roll(Strength.OFF, rng, mirror_mode=job.mirror_mode)
        params = replace(params, zoom=job.zoom, speed=job.speed)
        job = replace(job, uniq=params)
    return job


def process_file(
    src: str,
    out_dir: str,
    job: JobSettings,
    zoom_range: Range = None,
    speed_range: Range = None,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel: Optional[threading.Event] = None,
    rng: Optional[random.Random] = None,
    ffmpeg_bin: Optional[str] = None,
    info: Optional[MediaInfo] = None,
    measure: bool = True,
) -> ProcessResult:
    """Обрабатывает src в out_dir. Бросает ff.Cancelled, ff.FFmpegError, RuntimeError (probe)."""
    rng = rng or random.Random()
    ffmpeg_bin = ffmpeg_bin or ff.require("ffmpeg")
    os.makedirs(out_dir, exist_ok=True)
    info = info or ff.probe(src)
    if info.width == 0 or info.height == 0:
        raise RuntimeError("Не удалось определить размер видео")

    job = prepare_job(job, zoom_range, speed_range, rng, info)
    name = os.path.splitext(os.path.basename(src))[0]
    out_path = unique_out_path(out_dir, name, job.preset.slug)
    total = ff.expected_duration(info, job)

    try:
        cmd = ff.build_command(ffmpeg_bin, src, out_path, info, job, rng)
        try:
            ff.run_with_progress(cmd, total, on_progress, cancel)
        except ff.FFmpegError as e:
            if not job.hw_encode:
                raise
            log.warning("Аппаратный кодек не справился, повтор через libx264: %s", e.tail[-200:])
            job = replace(job, hw_encode=False)
            cmd = ff.build_command(ffmpeg_bin, src, out_path, info, job, rng)
            ff.run_with_progress(cmd, total, on_progress, cancel)
    except BaseException:
        remove_quiet(out_path)
        raise

    diff = None
    if measure and not (cancel and cancel.is_set()):
        from .similarity import difference
        diff = difference(src, out_path, ffmpeg_bin=ffmpeg_bin)
    return ProcessResult(out_path=out_path, params=job.uniq, difference=diff)
