"""Пресеты форматов, фильтры и прочие константы. Единый источник данных для UI и ffmpeg."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Preset:
    name: str
    width: Optional[int]
    height: Optional[int]
    slug: str

    @property
    def is_original(self) -> bool:
        return self.width is None

    @property
    def label(self) -> str:
        if self.is_original:
            return self.name
        return f"{self.name} ({self.width}x{self.height})"


OUTPUT_PRESETS: list[Preset] = [
    Preset("Оригинальный", None, None, "uniq"),
    Preset("Reels/TikTok", 1080, 1920, "reels"),
    Preset("YouTube Shorts", 1080, 1920, "shorts"),
    Preset("Instagram Story", 1080, 1920, "ig_story"),
    Preset("Instagram Post", 1080, 1080, "ig_post"),
    Preset("Instagram Landscape", 1920, 1080, "ig_land"),
    Preset("Instagram Portrait", 1080, 1350, "ig_portrait"),
    Preset("VK Clip", 1080, 1920, "vk_clip"),
    Preset("Telegram Story", 1080, 1920, "tg_story"),
    Preset("Telegram Post", 1280, 720, "tg_post"),
    Preset("YouTube", 1920, 1080, "youtube"),
    Preset("YouTube Vertical", 1080, 1920, "yt_vertical"),
    Preset("Facebook Story", 1080, 1920, "fb_story"),
    Preset("Facebook Post", 1200, 630, "fb_post"),
    Preset("Twitter Post", 1600, 900, "tw_post"),
    Preset("Twitter Portrait", 1080, 1350, "tw_portrait"),
    Preset("Snapchat", 1080, 1920, "snapchat"),
    Preset("Pinterest", 1000, 1500, "pinterest"),
]


def preset_by_label(label: str) -> Preset:
    for p in OUTPUT_PRESETS:
        if p.label == label or p.name == label:
            return p
    return OUTPUT_PRESETS[0]


RANDOM_COLOR_FILTER = "Случ. цвет (яркость/контраст/...)"
RANDOM_ANY_FILTER = "Случайный фильтр"

# Шаблон случайного цвета форматируется значениями br/ct/sat/hue.
FILTERS: dict[str, str] = {
    RANDOM_COLOR_FILTER: "eq=brightness={br:.3f}:contrast={ct:.3f}:saturation={sat:.3f},hue=h={hue:.2f}",
    "Черно-белое": "hue=s=0",
    "Сепия": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0",
    "Инверсия": "negate",
    "Размытие (легкое)": "gblur=sigma=2",
    "Размытие (сильное)": "gblur=sigma=10",
    "Отразить по горизонтали": "hflip",
    "Отразить по вертикали": "vflip",
    "Пикселизация": "scale=iw/10:ih/10,scale=iw*10:ih*10:flags=neighbor",
    "VHS (шум, сдвиг)": "chromashift=cbh=1:cbv=1,noise=alls=20:allf=t+u",
    "Повыш. контрастность": "eq=contrast=1.5",
    "Пониж. контрастность": "eq=contrast=0.7",
    "Повыш. насыщенность": "eq=saturation=1.5",
    "Пониж. насыщенность": "eq=saturation=0.5",
    "Повыш. яркость": "eq=brightness=0.15",
    "Пониж. яркость": "eq=brightness=-0.15",
    "Холодный фильтр": "curves=b='0/0 0.4/0.5 1/1':g='0/0 0.4/0.4 1/1'",
    "Теплый фильтр": "curves=r='0/0 0.4/0.5 1/1':g='0/0 0.6/0.6 1/1'",
    RANDOM_ANY_FILTER: "",
}

OVERLAY_MARGIN = 20

OVERLAY_POSITIONS: dict[str, str] = {
    "Верх-Лево": f"x={OVERLAY_MARGIN}:y={OVERLAY_MARGIN}",
    "Верх-Центр": f"x=(W-w)/2:y={OVERLAY_MARGIN}",
    "Верх-Право": f"x=W-w-{OVERLAY_MARGIN}:y={OVERLAY_MARGIN}",
    "Середина-Лево": f"x={OVERLAY_MARGIN}:y=(H-h)/2",
    "Середина-Центр": "x=(W-w)/2:y=(H-h)/2",
    "Середина-Право": f"x=W-w-{OVERLAY_MARGIN}:y=(H-h)/2",
    "Низ-Лево": f"x={OVERLAY_MARGIN}:y=H-h-{OVERLAY_MARGIN}",
    "Низ-Центр": f"x=(W-w)/2:y=H-h-{OVERLAY_MARGIN}",
    "Низ-Право": f"x=W-w-{OVERLAY_MARGIN}:y=H-h-{OVERLAY_MARGIN}",
}

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v", ".webm", ".mpg", ".mpeg", ".3gp"}
GIF_EXTENSIONS = {".gif"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
OVERLAY_EXTENSIONS = GIF_EXTENSIONS | IMAGE_EXTENSIONS
VALID_INPUT_EXTENSIONS = VIDEO_EXTENSIONS | GIF_EXTENSIONS

ZOOM_RANGE = (50, 300)
SPEED_RANGE = (50, 200)
