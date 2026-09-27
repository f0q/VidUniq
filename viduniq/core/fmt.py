"""Форматирование для отчётов (без Qt и aiogram)."""
from __future__ import annotations


def human_size(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("Б", "КБ") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def size_delta(size_in: int, size_out: int) -> str:
    """«9.8 МБ (было 12.4 МБ, −21%)»"""
    text = human_size(size_out)
    if size_in > 0 and size_out > 0:
        pct = (size_out - size_in) / size_in * 100
        sign = "+" if pct >= 0 else "−"
        text += f" (было {human_size(size_in)}, {sign}{abs(pct):.0f}%)"
    return text


def duration_text(seconds: float) -> str:
    s = int(round(max(0.0, seconds)))
    return f"{s // 60}:{s % 60:02d}"
