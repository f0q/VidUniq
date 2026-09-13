"""Настройки пользователя: JSON-файл на пользователя + преобразование в JobSettings."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from typing import Optional

from ..core.constants import FILTERS, OUTPUT_PRESETS, OVERLAY_POSITIONS, Preset
from ..core.ffmpeg import JobSettings

Range = Optional[tuple[int, int]]

# Готовые варианты для кнопок: подпись → (фикс. значение, диапазон)
ZOOM_CHOICES: dict[str, tuple[int, Range]] = {
    "100%": (100, None),
    "95–105%": (100, (95, 105)),
    "90–110%": (100, (90, 110)),
    "80–120%": (100, (80, 120)),
    "110%": (110, None),
    "120%": (120, None),
}
SPEED_CHOICES: dict[str, tuple[int, Range]] = {
    "100%": (100, None),
    "97–103%": (100, (97, 103)),
    "95–105%": (100, (95, 105)),
    "90–110%": (100, (90, 110)),
    "105%": (105, None),
    "110%": (110, None),
}


def preset_by_slug(slug: str) -> Preset:
    for p in OUTPUT_PRESETS:
        if p.slug == slug:
            return p
    return OUTPUT_PRESETS[0]


@dataclass
class UserPrefs:
    preset_slug: str = "uniq"
    blur_bg: bool = True
    filters: list[str] = field(default_factory=list)
    zoom: int = 100
    zoom_range: Range = (95, 105)
    speed: int = 100
    speed_range: Range = (97, 103)
    mute: bool = False
    strip_metadata: bool = True
    overlay_path: Optional[str] = None       # локальный путь к сохранённой картинке/GIF
    overlay_pos: str = "Низ-Право"
    variants: int = 1

    @property
    def preset(self) -> Preset:
        return preset_by_slug(self.preset_slug)

    def zoom_label(self) -> str:
        return f"{self.zoom_range[0]}–{self.zoom_range[1]}%" if self.zoom_range else f"{self.zoom}%"

    def speed_label(self) -> str:
        return f"{self.speed_range[0]}–{self.speed_range[1]}%" if self.speed_range else f"{self.speed}%"

    def to_job(self) -> JobSettings:
        overlay = self.overlay_path if self.overlay_path and os.path.exists(self.overlay_path) else None
        return JobSettings(
            preset=self.preset,
            blur_background=self.blur_bg and not self.preset.is_original,
            filters=[f for f in self.filters if f in FILTERS],
            zoom=self.zoom, speed=self.speed,
            overlay_file=overlay,
            overlay_pos=self.overlay_pos if self.overlay_pos in OVERLAY_POSITIONS else "Низ-Право",
            mute_audio=self.mute,
            strip_metadata=self.strip_metadata,
            hw_encode=False,
        )

    def summary(self) -> str:
        p = self.preset
        lines = [
            f"📐 Формат: <b>{p.label}</b>" + (" · размытый фон" if self.blur_bg and not p.is_original else ""),
            f"🎨 Фильтры: <b>{', '.join(self.filters) if self.filters else 'нет'}</b>",
            f"🔍 Zoom: <b>{self.zoom_label()}</b> · ⏩ Скорость: <b>{self.speed_label()}</b>",
            f"🖼 Наложение: <b>{'есть · ' + self.overlay_pos if self.overlay_path else 'нет'}</b>",
            f"🔇 Звук: <b>{'удалить' if self.mute else 'оставить'}</b> · 🧹 Метаданные: <b>{'очистить' if self.strip_metadata else 'оставить'}</b>",
            f"🔁 Вариантов на файл: <b>{self.variants}</b>",
        ]
        return "\n".join(lines)

    # --- сериализация ---
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UserPrefs":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in d.items() if k in known}
        for key in ("zoom_range", "speed_range"):
            v = clean.get(key)
            clean[key] = (int(v[0]), int(v[1])) if isinstance(v, (list, tuple)) and len(v) == 2 else None
        if "filters" in clean and not isinstance(clean["filters"], list):
            clean["filters"] = []
        return cls(**clean)


class PrefsStore:
    def __init__(self, users_dir: str):
        self.dir = users_dir
        os.makedirs(self.dir, exist_ok=True)
        self._cache: dict[int, UserPrefs] = {}
        self._lock = threading.Lock()

    def _path(self, user_id: int) -> str:
        return os.path.join(self.dir, f"{user_id}.json")

    def get(self, user_id: int) -> UserPrefs:
        with self._lock:
            if user_id in self._cache:
                return self._cache[user_id]
            prefs = UserPrefs()
            try:
                with open(self._path(user_id), encoding="utf-8") as f:
                    prefs = UserPrefs.from_dict(json.load(f))
            except (OSError, ValueError, TypeError):
                pass
            self._cache[user_id] = prefs
            return prefs

    def save(self, user_id: int, prefs: UserPrefs) -> None:
        with self._lock:
            self._cache[user_id] = prefs
            tmp = self._path(user_id) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(prefs.to_dict(), f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path(user_id))

    def reset(self, user_id: int) -> UserPrefs:
        prefs = self.get(user_id)
        old_overlay = prefs.overlay_path
        fresh = UserPrefs()
        self.save(user_id, fresh)
        if old_overlay and os.path.exists(old_overlay):
            try:
                os.remove(old_overlay)
            except OSError:
                pass
        return fresh
