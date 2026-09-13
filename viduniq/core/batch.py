"""Обработка одного файла: probe → случайные zoom/speed → ffmpeg → откат hw. Без Qt."""
from __future__ import annotations

import logging
import os
import random
import threading
from dataclasses import replace
from typing import Callable, Optional

from . import ffmpeg as ff
from .ffmpeg import JobSettings, MediaInfo

log = logging.getLogger(__name__)

Range = Optional[tuple[int, int]]


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
) -> str:
    """Обрабатывает src в out_dir, возвращает путь результата.

    Бросает ff.Cancelled, ff.FFmpegError, RuntimeError (probe). Недописанный файл удаляется.
    """
    rng = rng or random.Random()
    ffmpeg_bin = ffmpeg_bin or ff.require("ffmpeg")
    os.makedirs(out_dir, exist_ok=True)
    info = info or ff.probe(src)
    if info.width == 0 or info.height == 0:
        raise RuntimeError("Не удалось определить размер видео")

    job = replace(job, zoom=pick(job.zoom, zoom_range, rng), speed=pick(job.speed, speed_range, rng))
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
    return out_path
