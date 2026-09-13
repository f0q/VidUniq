"""Режимы уникализации: случайные малозаметные изменения кадра/звука/метаданных для каждого файла."""
from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Strength(str, Enum):
    OFF = "off"          # ручные zoom/скорость/фильтры
    SOFT = "soft"
    MEDIUM = "medium"
    STRONG = "strong"

    @property
    def label(self) -> str:
        return STRENGTH_LABELS[self]

    @classmethod
    def parse(cls, v: str | None, default: "Strength" = None) -> "Strength":
        try:
            return cls(str(v).lower())
        except ValueError:
            return default or cls.MEDIUM


STRENGTH_LABELS = {
    Strength.OFF: "Выкл (ручная)",
    Strength.SOFT: "Мягкая",
    Strength.MEDIUM: "Средняя",
    Strength.STRONG: "Сильная",
}

STRENGTH_HINTS = {
    Strength.OFF: "Применяются только заданные вручную zoom, скорость и фильтры.",
    Strength.SOFT: "Почти незаметно: zoom 1–4%, скорость ±2%, поворот до 0.4°, обрезка 0.1–0.4 с, цвет ±2–3%, тон звука ±1%.",
    Strength.MEDIUM: "Малозаметно: zoom 3–8%, скорость ±4%, поворот до 1°, обрезка до 0.8 с, цвет ±4–6%, лёгкий шум, fps, тон ±2%.",
    Strength.STRONG: "Заметно при сравнении: zoom 5–12%, скорость ±7%, поворот до 2°, обрезка до 1.5 с, цвет ±8–10%, шум, виньетка, тон ±3%.",
}

# Диапазоны для каждого режима. Все значения выбираются случайно для каждого файла.
PROFILES: dict[Strength, dict] = {
    Strength.SOFT: dict(
        zoom=(101, 104), speed=(98, 102), rotate=(0.0, 0.4), trim=(0.1, 0.4),
        bright=(-0.02, 0.02), contrast=(0.97, 1.03), sat=(0.97, 1.03), gamma=(0.97, 1.03), hue=(-1.5, 1.5),
        noise=(0, 3), vignette=(0.0, 0.0), sharpen=(0.0, 0.2), fps=None,
        pitch=(0.99, 1.01), gain=(-1.0, 1.0), eq=(-1.0, 1.0), crf=(22, 25), gop=(48, 120),
    ),
    Strength.MEDIUM: dict(
        zoom=(103, 108), speed=(96, 104), rotate=(0.3, 1.0), trim=(0.3, 0.8),
        bright=(-0.04, 0.04), contrast=(0.95, 1.05), sat=(0.94, 1.06), gamma=(0.95, 1.05), hue=(-3.0, 3.0),
        noise=(3, 7), vignette=(0.0, 0.15), sharpen=(0.1, 0.4), fps=[24.0, 25.0, 29.97, 30.0],
        pitch=(0.98, 1.02), gain=(-2.0, 2.0), eq=(-2.0, 2.0), crf=(21, 26), gop=(48, 150),
    ),
    Strength.STRONG: dict(
        zoom=(105, 112), speed=(93, 107), rotate=(0.8, 2.0), trim=(0.5, 1.5),
        bright=(-0.06, 0.06), contrast=(0.92, 1.08), sat=(0.90, 1.10), gamma=(0.93, 1.07), hue=(-5.0, 5.0),
        noise=(6, 12), vignette=(0.1, 0.3), sharpen=(0.2, 0.6), fps=[24.0, 25.0, 29.97, 30.0],
        pitch=(0.97, 1.03), gain=(-3.0, 3.0), eq=(-3.0, 3.0), crf=(20, 27), gop=(40, 150),
    ),
}

# Правдоподобные значения тегов контейнера (ffmpeg сам пишет «Lavf/Lavc <версия>» — это его отпечаток).
VIDEO_ENCODERS = [
    "Lavc60.31.102 libx264", "Lavc61.3.100 libx264", "Lavc61.19.100 libx264", "H.264", "AVC Coding",
    "x264 core 164 r3108", "HandBrake 1.8.2 2024082400", "CapCut", "InShot", "VN Video Editor",
    "Apple H.264", "JVT/AVC Coding", "Google", "Instagram", "TikTok",
]
VIDEO_HANDLERS = [
    "VideoHandler", "Core Media Video", "ISO Media file produced by Google Inc.", "L-SMASH Video Handler",
    "Mainconcept Video Media Handler", "Apple Video Media Handler",
]
AUDIO_HANDLERS = [
    "SoundHandler", "Core Media Audio", "ISO Media file produced by Google Inc.", "L-SMASH Audio Handler",
    "Mainconcept MP4 Sound Media Handler", "Apple Sound Media Handler",
]
BRANDS = ["isom", "mp42"]


@dataclass
class UniqParams:
    """Конкретные значения для одного файла (кубики уже брошены)."""
    strength: Strength = Strength.OFF
    zoom: int = 100
    speed: int = 100
    rotate_deg: float = 0.0
    trim_start: float = 0.0
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    hue_deg: float = 0.0
    noise: int = 0
    vignette: float = 0.0
    sharpen: float = 0.0
    fps: Optional[float] = None
    mirror: bool = False
    audio_pitch: float = 1.0
    audio_gain_db: float = 0.0
    audio_eq_db: float = 0.0
    crf: int = 23
    gop: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


def _u(rng: random.Random, lo: float, hi: float) -> float:
    return rng.uniform(lo, hi) if hi > lo else lo


def _signed(rng: random.Random, lo: float, hi: float) -> float:
    """Величина из [lo, hi] со случайным знаком."""
    v = _u(rng, lo, hi)
    return -v if rng.random() < 0.5 else v


def random_metadata(rng: random.Random, now: Optional[dt.datetime] = None) -> dict[str, str]:
    now = now or dt.datetime.now(dt.timezone.utc)
    when = now - dt.timedelta(seconds=rng.randint(3600, 60 * 86400))
    # Ключи: обычный → -metadata; «v:x»/«a:x» → тег потока; «brand» → -brand (major_brand контейнера)
    return {
        "creation_time": when.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "brand": rng.choice(BRANDS).strip(),
        "v:handler_name": rng.choice(VIDEO_HANDLERS),
        "v:encoder": rng.choice(VIDEO_ENCODERS),
        "a:handler_name": rng.choice(AUDIO_HANDLERS),
    }


def roll(strength: Strength, rng: random.Random, *, mirror_mode: str = "never", touch_audio: bool = True,
         source_fps: float = 30.0) -> UniqParams:
    """Бросает кубики по профилю режима."""
    if strength == Strength.OFF:
        return UniqParams(strength=strength, mirror=(mirror_mode == "always" or (mirror_mode == "random" and rng.random() < 0.5)),
                          metadata=random_metadata(rng))
    p = PROFILES[strength]
    fps = None
    if p["fps"]:
        choices = [f for f in p["fps"] if abs(f - source_fps) > 0.5]
        fps = rng.choice(choices) if choices and rng.random() < 0.7 else None
    return UniqParams(
        strength=strength,
        zoom=rng.randint(*p["zoom"]),
        speed=rng.randint(*p["speed"]),
        rotate_deg=round(_signed(rng, *p["rotate"]), 2),
        trim_start=round(_u(rng, *p["trim"]), 2),
        brightness=round(_u(rng, *p["bright"]), 3),
        contrast=round(_u(rng, *p["contrast"]), 3),
        saturation=round(_u(rng, *p["sat"]), 3),
        gamma=round(_u(rng, *p["gamma"]), 3),
        hue_deg=round(_u(rng, *p["hue"]), 2),
        noise=rng.randint(*p["noise"]),
        vignette=round(_u(rng, *p["vignette"]), 3),
        sharpen=round(_u(rng, *p["sharpen"]), 2),
        fps=fps,
        mirror=(mirror_mode == "always" or (mirror_mode == "random" and rng.random() < 0.5)),
        audio_pitch=round(_u(rng, *p["pitch"]), 4) if touch_audio else 1.0,
        audio_gain_db=round(_u(rng, *p["gain"]), 1) if touch_audio else 0.0,
        audio_eq_db=round(_signed(rng, 0.0, p["eq"][1]), 1) if touch_audio else 0.0,
        crf=rng.randint(*p["crf"]),
        gop=rng.randint(*p["gop"]),
        metadata=random_metadata(rng),
    )


def rotation_scale(deg: float, w: int, h: int) -> float:
    """Во сколько раз увеличить кадр w×h, чтобы после поворота на deg не осталось чёрных углов."""
    import math
    a = math.radians(abs(deg))
    ratio = max(w, h) / max(1, min(w, h))
    return math.cos(a) + ratio * math.sin(a)


def video_chain(p: UniqParams, w: int, h: int) -> list[str]:
    """Фильтры кадра размером w×h (после подгонки под формат, до пользовательских фильтров).

    Поворот: увеличить → повернуть → обрезать обратно до w×h, чтобы углы не были чёрными.
    """
    import math
    out: list[str] = []
    if abs(p.rotate_deg) > 1e-3:
        s = rotation_scale(p.rotate_deg, w, h)
        out.append(f"scale=trunc(iw*{s:.4f}/2)*2:trunc(ih*{s:.4f}/2)*2:flags=bicubic")
        out.append(f"rotate={math.radians(p.rotate_deg):.5f}:ow=iw:oh=ih:c=black")
        out.append(f"crop={w}:{h}")
    eq = []
    if abs(p.brightness) > 1e-4:
        eq.append(f"brightness={p.brightness:.3f}")
    if abs(p.contrast - 1) > 1e-4:
        eq.append(f"contrast={p.contrast:.3f}")
    if abs(p.saturation - 1) > 1e-4:
        eq.append(f"saturation={p.saturation:.3f}")
    if abs(p.gamma - 1) > 1e-4:
        eq.append(f"gamma={p.gamma:.3f}")
    if eq:
        out.append("eq=" + ":".join(eq))
    if abs(p.hue_deg) > 1e-3:
        out.append(f"hue=h={p.hue_deg:.2f}")
    if p.noise > 0:
        out.append(f"noise=alls={p.noise}:allf=t")
    if p.vignette > 1e-3:
        out.append(f"vignette=angle={p.vignette:.3f}")
    if p.sharpen > 1e-3:
        out.append(f"unsharp=5:5:{p.sharpen:.2f}:5:5:0")
    return out


def audio_chain(p: UniqParams, sample_rate: int = 44100) -> list[str]:
    """Фильтры звука: тон (без изменения темпа), громкость, тембр."""
    out: list[str] = []
    if abs(p.audio_pitch - 1) > 1e-4:
        out.append(f"asetrate={int(sample_rate * p.audio_pitch)}")
        out.append(f"aresample={sample_rate}")
        out.append(f"atempo={1 / p.audio_pitch:.5f}")
    if abs(p.audio_gain_db) > 0.05:
        out.append(f"volume={p.audio_gain_db:+.1f}dB")
    if abs(p.audio_eq_db) > 0.05:
        out.append(f"{'bass' if p.audio_eq_db > 0 else 'treble'}=g={abs(p.audio_eq_db):.1f}")
    return out


def describe(p: UniqParams) -> str:
    parts: list[str] = []
    if p.strength != Strength.OFF:
        parts.append(f"режим: {p.strength.label.lower()}")
    if p.zoom != 100:
        parts.append(f"zoom {p.zoom}%")
    if p.speed != 100:
        parts.append(f"скорость {p.speed}%")
    if abs(p.rotate_deg) > 1e-3:
        parts.append(f"поворот {p.rotate_deg:+.2f}°")
    if p.trim_start > 0:
        parts.append(f"обрезка {p.trim_start:.1f} с")
    color = []
    if abs(p.brightness) > 1e-4:
        color.append(f"яркость {p.brightness * 100:+.0f}%")
    if abs(p.contrast - 1) > 1e-4:
        color.append(f"контраст {(p.contrast - 1) * 100:+.0f}%")
    if abs(p.saturation - 1) > 1e-4:
        color.append(f"насыщ. {(p.saturation - 1) * 100:+.0f}%")
    if abs(p.hue_deg) > 1e-3:
        color.append(f"тон {p.hue_deg:+.1f}°")
    if color:
        parts.append(", ".join(color))
    if p.noise:
        parts.append(f"шум {p.noise}")
    if p.vignette > 1e-3:
        parts.append("виньетка")
    if p.sharpen > 1e-3:
        parts.append("резкость")
    if p.fps:
        parts.append(f"{p.fps:g} fps")
    if p.mirror:
        parts.append("зеркало")
    if abs(p.audio_pitch - 1) > 1e-4 or abs(p.audio_gain_db) > 0.05:
        a = []
        if abs(p.audio_pitch - 1) > 1e-4:
            a.append(f"тон {(p.audio_pitch - 1) * 100:+.1f}%")
        if abs(p.audio_gain_db) > 0.05:
            a.append(f"{p.audio_gain_db:+.1f} дБ")
        parts.append("звук: " + ", ".join(a))
    if p.metadata:
        parts.append("метаданные подменены")
    return " · ".join(parts) if parts else "без изменений"
