"""Поиск ffmpeg, probe, сборка команды и запуск с прогрессом."""
from __future__ import annotations

import json
import logging
import os
import random
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from .constants import (
    FILTERS, OVERLAY_POSITIONS, RANDOM_ANY_FILTER, RANDOM_COLOR_FILTER, Preset,
)
from .uniq import Strength, UniqParams, audio_chain, video_chain

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Поиск бинарников
# ----------------------------------------------------------------------------

def _candidate_dirs() -> list[str]:
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(os.path.join(meipass, "ffmpeg"))
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dirs.append(os.path.join(repo_root, "vendor", "ffmpeg"))
    return dirs


def locate(name: str) -> Optional[str]:
    """Возвращает путь к ffmpeg/ffprobe: бандл → vendor/ → PATH."""
    exe = name + (".exe" if sys.platform.startswith("win") else "")
    for d in _candidate_dirs():
        p = os.path.join(d, exe)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return shutil.which(name)


class FFmpegNotFound(RuntimeError):
    pass


def require(name: str) -> str:
    p = locate(name)
    if not p:
        raise FFmpegNotFound(
            f"Не найден {name}. Установите FFmpeg (brew install ffmpeg) "
            f"или запустите scripts/fetch_ffmpeg.sh"
        )
    return p


_encoders_cache: Optional[set[str]] = None


def available_encoders() -> set[str]:
    global _encoders_cache
    if _encoders_cache is None:
        _encoders_cache = set()
        try:
            out = subprocess.run(
                [require("ffmpeg"), "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15,
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith("V"):
                    _encoders_cache.add(parts[1])
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось получить список кодеков: %s", e)
    return _encoders_cache


def has_videotoolbox() -> bool:
    return sys.platform == "darwin" and "h264_videotoolbox" in available_encoders()


# ----------------------------------------------------------------------------
# Probe
# ----------------------------------------------------------------------------

@dataclass
class MediaInfo:
    width: int = 0
    height: int = 0
    duration: float = 0.0
    has_audio: bool = False
    is_gif: bool = False
    fps: float = 30.0

    @property
    def duration_text(self) -> str:
        s = int(round(self.duration))
        return f"{s // 60}:{s % 60:02d}"


def probe(path: str) -> MediaInfo:
    cmd = [
        require("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe: {res.stderr.strip()[-500:]}")
    data = json.loads(res.stdout or "{}")
    info = MediaInfo(is_gif=path.lower().endswith(".gif"))
    fmt = data.get("format", {})
    try:
        info.duration = float(fmt.get("duration") or 0)
    except ValueError:
        info.duration = 0.0
    for st in data.get("streams", []):
        ctype = st.get("codec_type")
        if ctype == "video" and info.width == 0:
            w, h = int(st.get("width") or 0), int(st.get("height") or 0)
            rot = 0
            for sd in st.get("side_data_list", []) or []:
                if "rotation" in sd:
                    try:
                        rot = int(float(sd["rotation"]))
                    except (TypeError, ValueError):
                        rot = 0
            if abs(rot) % 180 == 90:
                w, h = h, w
            info.width, info.height = w, h
            if not info.duration:
                try:
                    info.duration = float(st.get("duration") or 0)
                except ValueError:
                    pass
            fr = st.get("avg_frame_rate") or st.get("r_frame_rate") or "30/1"
            try:
                num, den = fr.split("/")
                if float(den) > 0:
                    info.fps = float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                pass
        elif ctype == "audio":
            info.has_audio = True
    return info


# ----------------------------------------------------------------------------
# Настройки задачи и сборка команды
# ----------------------------------------------------------------------------

@dataclass
class JobSettings:
    preset: Preset
    blur_background: bool = False
    filters: list[str] = field(default_factory=list)
    zoom: int = 100
    speed: int = 100
    overlay_file: Optional[str] = None
    overlay_pos: str = "Середина-Центр"
    mute_audio: bool = False
    strip_metadata: bool = True
    hw_encode: bool = False
    # Уникализация: режим и его опции; `uniq` — конкретные значения для файла (заполняет process_file)
    strength: Strength = Strength.OFF
    mirror_mode: str = "never"          # never | random | always
    touch_audio: bool = True
    uniq: Optional[UniqParams] = None


def _even(v: int) -> int:
    return max(2, v - (v % 2))


def _atempo_chain(factor: float) -> list[str]:
    """Раскладывает множитель скорости на допустимые atempo (0.5..2.0)."""
    parts = []
    cur = factor
    while cur > 2.0:
        parts.append("atempo=2.0")
        cur /= 2.0
    while cur < 0.5:
        parts.append("atempo=0.5")
        cur /= 0.5
    if abs(cur - 1.0) > 1e-5:
        parts.append(f"atempo={cur:.4f}")
    return parts


def resolve_filters(names: list[str], rng: random.Random) -> list[str]:
    """Превращает имена фильтров в ffmpeg-выражения, раскрывая случайные."""
    out = []
    for name in names:
        if name == RANDOM_ANY_FILTER:
            choices = [k for k, v in FILTERS.items() if v and k != RANDOM_COLOR_FILTER]
            name = rng.choice(choices)
        tmpl = FILTERS.get(name)
        if not tmpl:
            continue
        if name == RANDOM_COLOR_FILTER:
            # Малозаметные сдвиги: раньше было ±0.15 / 0.8–1.2 / 0.8–1.3 / ±5° — картинка заметно менялась
            tmpl = tmpl.format(
                br=rng.uniform(-0.03, 0.03), ct=rng.uniform(0.96, 1.04),
                sat=rng.uniform(0.95, 1.06), hue=rng.uniform(-2, 2),
            )
        out.append(tmpl)
    return out


def _hw_bitrate_kbps(w: int, h: int, fps: float) -> int:
    fps = min(max(fps, 24.0), 60.0)
    return max(1500, int(w * h * fps * 0.1 / 1000))


def build_command(
    ffmpeg_bin: str,
    in_path: str,
    out_path: str,
    info: MediaInfo,
    s: JobSettings,
    rng: Optional[random.Random] = None,
) -> list[str]:
    """Чистая функция: собирает аргументы ffmpeg. Не запускает процесс."""
    rng = rng or random.Random()
    cmd = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]

    u = s.uniq
    zoom_p = u.zoom if u and u.strength != Strength.OFF else s.zoom
    speed_p = u.speed if u and u.strength != Strength.OFF else s.speed

    # --- входы ---
    inputs = 0
    if u and u.trim_start > 0 and info.duration > u.trim_start + 1.0:
        cmd += ["-ss", f"{u.trim_start:.2f}"]
    cmd += ["-i", in_path]
    video_in = f"[{inputs}:v]"
    inputs += 1

    audio_in: Optional[str] = None
    needs_shortest = False
    if s.mute_audio:
        audio_in = None
    elif info.is_gif or not info.has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        audio_in = f"[{inputs}:a]"
        inputs += 1
        needs_shortest = True
    else:
        audio_in = "[0:a]"

    overlay_in: Optional[str] = None
    if s.overlay_file and os.path.exists(s.overlay_file):
        if s.overlay_file.lower().endswith(".gif"):
            cmd += ["-stream_loop", "-1", "-i", s.overlay_file]
        else:
            cmd += ["-loop", "1", "-i", s.overlay_file]
        overlay_in = f"[{inputs}:v]"
        inputs += 1

    # --- целевой размер ---
    if s.preset.is_original:
        tw, th = _even(info.width or 2), _even(info.height or 2)
    else:
        tw, th = s.preset.width, s.preset.height

    parts: list[str] = []
    node = video_in

    # 1. Подгонка под формат
    if not s.preset.is_original:
        if s.blur_background:
            parts.append(
                f"{node}split[fit_a][fit_b];"
                f"[fit_b]scale={tw}:{th}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{th},gblur=sigma=25[bg];"
                f"[fit_a]scale={tw}:{th}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
                f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2[fmt]"
            )
        else:
            parts.append(
                f"{node}scale={tw}:{th}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black[fmt]"
            )
        node = "[fmt]"
    else:
        parts.append(f"{node}scale={tw}:{th}[fmt]")
        node = "[fmt]"

    # 1b. Уникализация кадра (поворот, цвет, шум, виньетка, резкость)
    if u:
        uchain = video_chain(u, tw, th)
        if uchain:
            parts.append(f"{node}{','.join(uchain)}[unq]")
            node = "[unq]"

    # 2. Цветовые фильтры
    chain = resolve_filters(s.filters, rng)
    if chain:
        parts.append(f"{node}{','.join(chain)}[flt]")
        node = "[flt]"

    # 3. Zoom
    z = zoom_p / 100.0
    if abs(z - 1.0) > 1e-5:
        steps = [f"scale=trunc(iw*{z:.4f}/2)*2:trunc(ih*{z:.4f}/2)*2:flags=bicubic"]
        if z > 1.0:
            steps.append(f"crop={tw}:{th}")
        else:
            steps.append(f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black")
        parts.append(f"{node}{','.join(steps)}[zoom]")
        node = "[zoom]"

    # 4. Скорость
    sp = speed_p / 100.0
    if abs(sp - 1.0) > 1e-5:
        parts.append(f"{node}setpts=PTS/{sp:.4f}[spd]")
        node = "[spd]"

    # 4b. Зеркало
    if u and u.mirror:
        parts.append(f"{node}hflip[mir]")
        node = "[mir]"

    # 5. Наложение
    if overlay_in:
        pos = OVERLAY_POSITIONS.get(s.overlay_pos, OVERLAY_POSITIONS["Середина-Центр"])
        parts.append(f"{overlay_in}format=rgba[ovl]")
        parts.append(f"{node}[ovl]overlay={pos}:shortest=1[ovd]")
        node = "[ovd]"

    # 6. Частота кадров
    if u and u.fps:
        parts.append(f"{node}fps={u.fps:g}[fps]")
        node = "[fps]"

    parts.append(f"{node}format=yuv420p[vout]")

    # --- аудио ---
    audio_out: Optional[str] = None
    if audio_in:
        tempo = _atempo_chain(sp) if abs(sp - 1.0) > 1e-5 and not needs_shortest else []
        if u and not needs_shortest:
            tempo += audio_chain(u)
        if tempo:
            parts.append(f"{audio_in}{','.join(tempo)}[aout]")
            audio_out = "[aout]"
        else:
            audio_out = audio_in.strip("[]")   # прямой маппинг потока: -map 1:a, без скобок

    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]"]
    if audio_out:
        cmd += ["-map", audio_out, "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]

    # --- видеокодек ---
    if s.hw_encode:
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", f"{_hw_bitrate_kbps(tw, th, info.fps)}k",
                "-profile:v", "high", "-allow_sw", "1"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(u.crf if u else 24)]
    if u and u.gop:
        cmd += ["-g", str(u.gop)]

    cmd += ["-movflags", "+faststart"]
    if s.strip_metadata:
        # bitexact убирает отпечаток «Lavf/Lavc <версия>» из тегов контейнера
        cmd += ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact"]
        if u:
            for k, v in u.metadata.items():
                if k == "brand":
                    cmd += ["-brand", v]
                elif k.startswith("v:"):
                    cmd += ["-metadata:s:v:0", f"{k[2:]}={v}"]
                elif k.startswith("a:"):
                    if audio_out:
                        cmd += ["-metadata:s:a:0", f"{k[2:]}={v}"]
                else:
                    cmd += ["-metadata", f"{k}={v}"]
    if needs_shortest:
        cmd += ["-shortest"]
    cmd.append(out_path)
    return cmd


def expected_duration(info: MediaInfo, s: JobSettings) -> float:
    u = s.uniq
    speed = u.speed if u and u.strength != Strength.OFF else s.speed
    dur = info.duration
    if u and u.trim_start > 0 and dur > u.trim_start + 1.0:
        dur -= u.trim_start
    sp = speed / 100.0
    return dur / sp if sp > 0 else dur


# ----------------------------------------------------------------------------
# Запуск с прогрессом
# ----------------------------------------------------------------------------

def parse_progress_line(line: str) -> Optional[float]:
    """Возвращает out_time в секундах из строки -progress, либо None."""
    line = line.strip()
    if line.startswith("out_time_us="):
        try:
            return max(0.0, int(line.split("=", 1)[1]) / 1_000_000)
        except ValueError:
            return None
    if line.startswith("out_time_ms="):
        # Исторически ffmpeg пишет здесь микросекунды.
        try:
            return max(0.0, int(line.split("=", 1)[1]) / 1_000_000)
        except ValueError:
            return None
    if line.startswith("out_time="):
        try:
            hh, mm, ss = line.split("=", 1)[1].split(":")
            return max(0.0, int(hh) * 3600 + int(mm) * 60 + float(ss))
        except ValueError:
            return None
    return None


class Cancelled(Exception):
    pass


class FFmpegError(RuntimeError):
    def __init__(self, code: int, tail: str, cmd: list[str]):
        super().__init__(f"ffmpeg завершился с кодом {code}:\n{tail}")
        self.code = code
        self.tail = tail
        self.cmd = cmd


def run_with_progress(
    cmd: list[str],
    total_seconds: float,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel: Optional[threading.Event] = None,
) -> None:
    """Запускает ffmpeg, вызывает on_progress(0..1). Бросает Cancelled / FFmpegError."""
    log.info("ffmpeg: %s", " ".join(cmd))
    popen_kwargs = {}
    if sys.platform.startswith("win"):
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1, **popen_kwargs,
    )
    tail: deque[str] = deque(maxlen=40)

    def _drain_stderr():
        assert proc.stderr is not None
        for ln in proc.stderr:
            ln = ln.rstrip()
            if ln:
                tail.append(ln)
                log.debug("ffmpeg stderr: %s", ln)

    def _watch_cancel():
        if cancel is None:
            return
        while proc.poll() is None:
            if cancel.wait(0.2):
                try:
                    proc.terminate()
                    try:
                        proc.wait(3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except OSError:
                    pass
                return

    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_cancel = threading.Thread(target=_watch_cancel, daemon=True)
    t_err.start()
    t_cancel.start()

    assert proc.stdout is not None
    last = -1.0
    for line in proc.stdout:
        secs = parse_progress_line(line)
        if secs is not None and on_progress and total_seconds > 0:
            frac = min(1.0, secs / total_seconds)
            if frac - last >= 0.005:
                last = frac
                on_progress(frac)
    proc.stdout.close()
    code = proc.wait()
    t_err.join(timeout=2)
    t_cancel.join(timeout=2)

    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if code != 0:
        raise FFmpegError(code, "\n".join(tail), cmd)
    if on_progress:
        on_progress(1.0)
