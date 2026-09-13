"""Inline-клавиатуры настроек. callback_data ≤ 64 байт."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..core.constants import FILTERS, OUTPUT_PRESETS, OVERLAY_POSITIONS
from ..core.uniq import STRENGTH_HINTS, Strength
from .store import SPEED_CHOICES, ZOOM_CHOICES, UserPrefs

FILTER_NAMES = list(FILTERS)
POS_NAMES = list(OVERLAY_POSITIONS)
PRESETS_PER_PAGE = 6


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu(p: UserPrefs) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(_btn(f"🎲 Уникализация: {p.strength_enum.label}", "um"))
    b.row(_btn(f"📐 Формат: {p.preset.name}", "pp:0"))
    if not p.preset.is_original:
        b.row(_btn(f"{'✅' if p.blur_bg else '☐'} Размытый фон вместо полос", "pb"))
    b.row(_btn(f"🎨 Фильтры ({len(p.filters)})", "fm:0"))
    if p.strength_enum == Strength.OFF:
        b.row(_btn(f"🔍 Zoom: {p.zoom_label()}", "zm"), _btn(f"⏩ Скорость: {p.speed_label()}", "sm"))
    b.row(_btn(f"🖼 Наложение: {'есть' if p.overlay_path else 'нет'}", "om"))
    b.row(_btn(f"{'🔇' if p.mute else '🔊'} Звук: {'удалить' if p.mute else 'оставить'}", "t:mute"),
          _btn(f"{'🧹' if p.strip_metadata else '📋'} Метаданные: {'подменить' if p.strip_metadata else 'оставить'}", "t:meta"))
    b.row(_btn(f"🔁 Вариантов: {p.variants}", "vm"))
    b.row(_btn("✖ Закрыть", "close"))
    return b.as_markup()


STRENGTH_ORDER = [Strength.SOFT, Strength.MEDIUM, Strength.STRONG, Strength.OFF]


def strength_menu(p: UserPrefs) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for st in STRENGTH_ORDER:
        mark = "✅ " if st == p.strength_enum else ""
        b.row(_btn(f"{mark}{st.label}", f"u:{st.value}"))
    b.row(_btn(f"{'✅' if p.mirror else '☐'} Зеркалить (случайно 50/50)", "t:mirror"))
    if p.strength_enum != Strength.OFF:
        b.row(_btn(f"{'✅' if p.touch_audio else '☐'} Слегка менять звук (тон/громкость)", "t:audio"))
    b.row(_btn("« Назад", "m"))
    return b.as_markup()


def strength_text(p: UserPrefs) -> str:
    st = p.strength_enum
    return f"🎲 <b>Уникализация: {st.label}</b>\n\n{STRENGTH_HINTS[st]}\n\nКаждый файл получает свой случайный набор значений."


def presets_menu(p: UserPrefs, page: int) -> InlineKeyboardMarkup:
    pages = (len(OUTPUT_PRESETS) + PRESETS_PER_PAGE - 1) // PRESETS_PER_PAGE
    page = max(0, min(page, pages - 1))
    b = InlineKeyboardBuilder()
    for pr in OUTPUT_PRESETS[page * PRESETS_PER_PAGE:(page + 1) * PRESETS_PER_PAGE]:
        mark = "✅ " if pr.slug == p.preset_slug else ""
        b.row(_btn(f"{mark}{pr.label}", f"p:{pr.slug}"))
    nav = []
    if page > 0:
        nav.append(_btn("◀", f"pp:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        nav.append(_btn("▶", f"pp:{page + 1}"))
    b.row(*nav)
    b.row(_btn("« Назад", "m"))
    return b.as_markup()


def filters_menu(p: UserPrefs, page: int, per_page: int = 8) -> InlineKeyboardMarkup:
    pages = (len(FILTER_NAMES) + per_page - 1) // per_page
    page = max(0, min(page, pages - 1))
    b = InlineKeyboardBuilder()
    start = page * per_page
    for i, name in enumerate(FILTER_NAMES[start:start + per_page], start=start):
        b.row(_btn(f"{'✅' if name in p.filters else '☐'} {name}", f"f:{i}:{page}"))
    nav = []
    if page > 0:
        nav.append(_btn("◀", f"fm:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        nav.append(_btn("▶", f"fm:{page + 1}"))
    b.row(*nav)
    b.row(_btn("Снять все", "fc"), _btn("« Назад", "m"))
    return b.as_markup()


def _choices_menu(choices: dict, current_label: str, prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    items = list(choices)
    for i in range(0, len(items), 2):
        row = []
        for j, label in enumerate(items[i:i + 2]):
            mark = "✅ " if label == current_label else ""
            row.append(_btn(f"{mark}{label}", f"{prefix}:{i + j}"))
        b.row(*row)
    b.row(_btn("« Назад", "m"))
    return b.as_markup()


def zoom_menu(p: UserPrefs) -> InlineKeyboardMarkup:
    return _choices_menu(ZOOM_CHOICES, p.zoom_label(), "z")


def speed_menu(p: UserPrefs) -> InlineKeyboardMarkup:
    return _choices_menu(SPEED_CHOICES, p.speed_label(), "s")


def overlay_menu(p: UserPrefs) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if p.overlay_path:
        grid = [
            ["↖", "↑", "↗"],
            ["←", "•", "→"],
            ["↙", "↓", "↘"],
        ]
        for r in range(3):
            row = []
            for c in range(3):
                idx = r * 3 + c
                name = POS_NAMES[idx]
                mark = "✅" if name == p.overlay_pos else grid[r][c]
                row.append(_btn(mark, f"o:{idx}"))
            b.row(*row)
        b.row(_btn("🗑 Убрать наложение", "od"))
    b.row(_btn("« Назад", "m"))
    return b.as_markup()


def variants_menu(p: UserPrefs, max_variants: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(*[_btn(f"{'✅ ' if n == p.variants else ''}{n}", f"v:{n}") for n in range(1, max_variants + 1)])
    b.row(_btn("« Назад", "m"))
    return b.as_markup()


def cancel_kb(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("■ Отменить", f"x:{task_id}")]])
