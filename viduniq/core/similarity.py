"""Оценка отличия результата от оригинала: dHash по кадрам (без внешних зависимостей)."""
from __future__ import annotations

import subprocess
from typing import Optional

from . import ffmpeg as ff

HASH_W, HASH_H = 9, 8   # dHash: 9×8 серых пикселей → 64 бита


def frame_hashes(path: str, n: int = 12, duration: Optional[float] = None, ffmpeg_bin: Optional[str] = None) -> list[int]:
    """n dHash-ей, равномерно по длительности."""
    ffmpeg_bin = ffmpeg_bin or ff.require("ffmpeg")
    if duration is None:
        duration = ff.probe(path).duration
    if duration <= 0:
        return []
    step = duration / n
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-i", path,
           "-vf", f"fps=1/{step:.6f}:start_time=0,scale={HASH_W}:{HASH_H}:flags=area,format=gray",
           "-frames:v", str(n), "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    frame = HASH_W * HASH_H
    hashes = []
    for i in range(len(raw) // frame):
        px = raw[i * frame:(i + 1) * frame]
        h = 0
        for y in range(HASH_H):
            for x in range(HASH_W - 1):
                h = (h << 1) | (1 if px[y * HASH_W + x] < px[y * HASH_W + x + 1] else 0)
        hashes.append(h)
    return hashes


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def difference(src: str, out: str, n: int = 12, ffmpeg_bin: Optional[str] = None) -> Optional[float]:
    """0.0 — кадры визуально совпадают, 1.0 — ничего общего. None, если посчитать не удалось."""
    try:
        a = frame_hashes(src, n, ffmpeg_bin=ffmpeg_bin)
        b = frame_hashes(out, n, ffmpeg_bin=ffmpeg_bin)
    except Exception:  # noqa: BLE001
        return None
    m = min(len(a), len(b))
    if m == 0:
        return None
    # выравниваем по доле длительности: i-й из n кадров исходника ↔ i-й результата
    return sum(hamming(a[i], b[i]) for i in range(m)) / (64.0 * m)
