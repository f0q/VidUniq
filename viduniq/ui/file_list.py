"""Список файлов с состоянием, прогрессом и фоновым probe."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QListWidget, QListWidgetItem, QMenu, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem,
)

from ..core import ffmpeg as ff
from ..core.constants import VALID_INPUT_EXTENSIONS
from ..core.ffmpeg import MediaInfo

log = logging.getLogger(__name__)

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"
STATUS_ICON = {PENDING: "", RUNNING: "⏳", DONE: "✅", FAILED: "❌"}


@dataclass
class FileEntry:
    path: str
    info: Optional[MediaInfo] = None
    probe_error: str = ""
    status: str = PENDING
    progress: float = 0.0
    message: str = ""
    out_path: str = ""
    size_bytes: int = field(default=0)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def subtitle(self) -> str:
        parts = []
        if self.info and self.info.width:
            parts.append(f"{self.info.width}×{self.info.height}")
            parts.append(self.info.duration_text)
        elif self.probe_error:
            parts.append("не удалось прочитать")
        else:
            parts.append("…")
        if self.size_bytes:
            parts.append(human_size(self.size_bytes))
        if self.status == FAILED and self.message:
            parts.append(self.message.splitlines()[0][:60])
        elif self.status == DONE and self.out_path:
            parts.append("→ " + os.path.basename(self.out_path))
        return "  ·  ".join(parts)


def human_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def is_supported_input(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in VALID_INPUT_EXTENSIONS


def collect_inputs(paths: list[str]) -> list[str]:
    """Разворачивает папки (рекурсивно) в список поддерживаемых файлов."""
    out: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for name in sorted(files):
                    fp = os.path.join(root, name)
                    if is_supported_input(fp):
                        out.append(fp)
        elif is_supported_input(p):
            out.append(p)
    return out


# ----------------------------------------------------------------------------
# Фоновый probe
# ----------------------------------------------------------------------------

class _ProbeSignals(QObject):
    done = Signal(str, object, str)  # path, MediaInfo|None, error


class _ProbeTask(QRunnable):
    def __init__(self, path: str, signals: _ProbeSignals):
        super().__init__()
        self.path = path
        self.signals = signals

    def run(self):
        try:
            info, err = ff.probe(self.path), ""
        except Exception as e:  # noqa: BLE001
            info, err = None, str(e)
        try:
            self.signals.done.emit(self.path, info, err)
        except RuntimeError:
            pass  # окно уже закрыто


# ----------------------------------------------------------------------------
# Делегат
# ----------------------------------------------------------------------------

ROLE_ENTRY = Qt.ItemDataRole.UserRole + 1


class FileDelegate(QStyledItemDelegate):
    ROW_H = 48

    def sizeHint(self, option, index) -> QSize:
        return QSize(120, self.ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        entry: FileEntry = index.data(ROLE_ENTRY)
        if entry is None:
            return super().paint(painter, option, index)
        painter.save()
        pal = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, pal.color(QPalette.ColorRole.Highlight))
            fg = pal.color(QPalette.ColorRole.HighlightedText)
        else:
            fg = pal.color(QPalette.ColorRole.Text)
        sub = QColor(fg)
        sub.setAlphaF(0.65)

        r = option.rect.adjusted(10, 6, -10, -6)
        icon = STATUS_ICON[entry.status]
        icon_w = 26 if icon else 0
        text_rect = QRect(r.left(), r.top(), r.width() - icon_w, r.height())

        f_main = QFont(option.font)
        f_main.setBold(True)
        fm_main = QFontMetrics(f_main)
        painter.setFont(f_main)
        painter.setPen(fg)
        painter.drawText(QRect(text_rect.left(), text_rect.top(), text_rect.width(), fm_main.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm_main.elidedText(entry.name, Qt.TextElideMode.ElideMiddle, text_rect.width()))

        f_sub = QFont(option.font)
        f_sub.setPointSizeF(max(9.0, option.font.pointSizeF() - 2))
        fm_sub = QFontMetrics(f_sub)
        painter.setFont(f_sub)
        painter.setPen(sub if entry.status != FAILED else QColor("#d64545"))
        sub_top = text_rect.top() + fm_main.height() + 1
        if entry.status == RUNNING:
            bar_w = int(text_rect.width() * 0.45)
            bar = QRect(text_rect.left(), sub_top + fm_sub.height() // 2 - 3, bar_w, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            track = QColor(fg)
            track.setAlphaF(0.15)
            painter.setBrush(track)
            painter.drawRoundedRect(bar, 3, 3)
            painter.setBrush(pal.color(QPalette.ColorRole.Highlight) if not selected else pal.color(QPalette.ColorRole.HighlightedText))
            painter.drawRoundedRect(QRect(bar.left(), bar.top(), int(bar_w * entry.progress), 6), 3, 3)
            painter.setPen(sub)
            painter.drawText(QRect(bar.right() + 8, sub_top, text_rect.width() - bar_w - 8, fm_sub.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{int(entry.progress * 100)}%")
        else:
            painter.drawText(QRect(text_rect.left(), sub_top, text_rect.width(), fm_sub.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             fm_sub.elidedText(entry.subtitle(), Qt.TextElideMode.ElideRight, text_rect.width()))

        if icon:
            painter.setFont(option.font)
            painter.setPen(fg)
            painter.drawText(QRect(r.right() - icon_w, r.top(), icon_w, r.height()),
                             Qt.AlignmentFlag.AlignCenter, icon)

        painter.setPen(QPen(QColor(fg.red(), fg.green(), fg.blue(), 25)))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()


# ----------------------------------------------------------------------------
# Виджет списка
# ----------------------------------------------------------------------------

class FileListWidget(QListWidget):
    files_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setItemDelegate(FileDelegate(self))
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlternatingRowColors(False)
        self.setAcceptDrops(False)  # drop обрабатывает главное окно (вся его площадь)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self._pool = QThreadPool.globalInstance()
        self._probe_signals = _ProbeSignals()
        self._probe_signals.done.connect(self._on_probed)
        self._by_path: dict[str, QListWidgetItem] = {}
        self.setFrameShape(QListWidget.Shape.NoFrame)

    # --- данные ---
    def entries(self) -> list[FileEntry]:
        return [self.item(i).data(ROLE_ENTRY) for i in range(self.count())]

    def paths(self) -> list[str]:
        return [e.path for e in self.entries()]

    def add_paths(self, paths: list[str]) -> int:
        added = 0
        for p in collect_inputs(paths):
            p = os.path.abspath(p)
            if p in self._by_path:
                continue
            entry = FileEntry(path=p)
            try:
                entry.size_bytes = os.path.getsize(p)
            except OSError:
                pass
            item = QListWidgetItem()
            item.setData(ROLE_ENTRY, entry)
            item.setToolTip(p)
            self.addItem(item)
            self._by_path[p] = item
            self._pool.start(_ProbeTask(p, self._probe_signals))
            added += 1
        if added:
            self.files_changed.emit()
        return added

    def remove_selected(self):
        for item in self.selectedItems():
            entry: FileEntry = item.data(ROLE_ENTRY)
            self._by_path.pop(entry.path, None)
            self.takeItem(self.row(item))
        self.files_changed.emit()

    def clear_all(self):
        self.clear()
        self._by_path.clear()
        self.files_changed.emit()

    def reset_statuses(self):
        for i in range(self.count()):
            e: FileEntry = self.item(i).data(ROLE_ENTRY)
            e.status, e.progress, e.message, e.out_path = PENDING, 0.0, "", ""
        self.viewport().update()

    def set_status(self, idx: int, status: str, message: str = "", out_path: str = "", progress: Optional[float] = None):
        item = self.item(idx)
        if item is None:
            return
        e: FileEntry = item.data(ROLE_ENTRY)
        e.status = status
        if message:
            e.message = message
        if out_path:
            e.out_path = out_path
        if progress is not None:
            e.progress = progress
        if status == DONE:
            e.progress = 1.0
        item.setToolTip(f"{e.path}\n\n{e.message}" if e.message else e.path)
        self.update(self.indexFromItem(item))
        if status == RUNNING:
            self.scrollToItem(item)

    def set_progress(self, idx: int, frac: float):
        item = self.item(idx)
        if item is None:
            return
        e: FileEntry = item.data(ROLE_ENTRY)
        e.progress = frac
        self.update(self.indexFromItem(item))

    def _on_probed(self, path: str, info, err: str):
        item = self._by_path.get(path)
        if item is None:
            return
        e: FileEntry = item.data(ROLE_ENTRY)
        e.info, e.probe_error = info, err
        self.update(self.indexFromItem(item))

    # --- события ---
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected()
            return
        super().keyPressEvent(event)

    def _context_menu(self, pos):
        menu = QMenu(self)
        act_del = menu.addAction("Удалить выбранные")
        act_reveal = menu.addAction("Показать в Finder")
        menu.addSeparator()
        act_clear = menu.addAction("Очистить список")
        act_del.setEnabled(bool(self.selectedItems()))
        act_reveal.setEnabled(len(self.selectedItems()) == 1)
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen == act_del:
            self.remove_selected()
        elif chosen == act_clear:
            self.clear_all()
        elif chosen == act_reveal:
            from .main_window import reveal_in_file_manager
            e: FileEntry = self.selectedItems()[0].data(ROLE_ENTRY)
            reveal_in_file_manager(e.out_path if e.status == DONE and e.out_path else e.path)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            p = QPainter(self.viewport())
            c = self.palette().color(QPalette.ColorRole.Text)
            c.setAlphaF(0.45)
            p.setPen(c)
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() + 3)
            p.setFont(f)
            r = self.viewport().rect().adjusted(20, 20, -20, -20)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       "Перетащите видео, GIF или папки сюда\n\nили нажмите «Добавить файлы»")
            p.end()
