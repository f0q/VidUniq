"""Правая панель настроек (в QScrollArea) + сохранение в QSettings."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QRadioButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget, QSizePolicy,
)

from ..core import ffmpeg as ff
from ..core.constants import (
    FILTERS, OUTPUT_PRESETS, OVERLAY_EXTENSIONS, OVERLAY_POSITIONS, SPEED_RANGE, ZOOM_RANGE,
)
from ..core.ffmpeg import JobSettings
from ..core.worker import BatchSettings


class PathLineEdit(QLineEdit):
    """QLineEdit, принимающий drop файла как путь."""

    def __init__(self, extensions: set[str], parent=None):
        super().__init__(parent)
        self._ext = extensions
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in self._ext:
                self.setText(p)
                e.acceptProposedAction()
                return
        e.ignore()


class RangeRow(QWidget):
    """Фикс. значение или диапазон [min..max] — в одну строку."""

    def __init__(self, lo: int, hi: int, default: int, range_default: tuple[int, int], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        self.mode.addItems(["Фикс.", "Случайно"])
        self.value = QSpinBox()
        self.value.setRange(lo, hi)
        self.value.setValue(default)
        self.value.setSuffix(" %")
        self.lo = QSpinBox()
        self.lo.setRange(lo, hi)
        self.lo.setSuffix(" %")
        self.hi = QSpinBox()
        self.hi.setRange(lo, hi)
        self.hi.setSuffix(" %")
        self.lo.setValue(range_default[0])
        self.hi.setValue(range_default[1])
        self.dash = QLabel("–")
        for w in (self.mode, self.value, self.lo, self.dash, self.hi):
            lay.addWidget(w)
        lay.addStretch()
        self.mode.currentIndexChanged.connect(self._update)
        self.lo.valueChanged.connect(lambda v: self.hi.setValue(max(v, self.hi.value())))
        self.hi.valueChanged.connect(lambda v: self.lo.setValue(min(v, self.lo.value())))
        self._update()

    def _update(self):
        rng = self.mode.currentIndex() == 1
        self.value.setVisible(not rng)
        for w in (self.lo, self.dash, self.hi):
            w.setVisible(rng)

    def is_range(self) -> bool:
        return self.mode.currentIndex() == 1

    def result(self) -> tuple[int, tuple[int, int] | None]:
        if self.is_range():
            return self.lo.value(), (self.lo.value(), self.hi.value())
        return self.value.value(), None

    def save(self, s: QSettings, key: str):
        s.setValue(f"{key}/mode", self.mode.currentIndex())
        s.setValue(f"{key}/value", self.value.value())
        s.setValue(f"{key}/lo", self.lo.value())
        s.setValue(f"{key}/hi", self.hi.value())

    def load(self, s: QSettings, key: str):
        self.mode.setCurrentIndex(int(s.value(f"{key}/mode", 0)))
        self.value.setValue(int(s.value(f"{key}/value", self.value.value())))
        self.lo.setValue(int(s.value(f"{key}/lo", self.lo.value())))
        self.hi.setValue(int(s.value(f"{key}/hi", self.hi.value())))


class SettingsPanel(QScrollArea):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        # --- Формат ---
        g = QGroupBox("Формат вывода")
        f = QFormLayout(g)
        f.setContentsMargins(10, 6, 10, 8)
        self.preset = QComboBox()
        for p in OUTPUT_PRESETS:
            self.preset.addItem(p.label, p)
        self.blur_bg = QCheckBox("Размыть фон вместо чёрных полос")
        self.blur_bg.setToolTip("Пустые области кадра заполняются размытой копией видео")
        f.addRow("Пресет:", self.preset)
        f.addRow("", self.blur_bg)
        root.addWidget(g)
        self.preset.currentIndexChanged.connect(self._on_preset)

        # --- Фильтры ---
        g = QGroupBox("Фильтры")
        v = QVBoxLayout(g)
        v.setContentsMargins(10, 6, 10, 8)
        self.filters = QListWidget()
        for name in FILTERS:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.filters.addItem(it)
        self.filters.setMinimumHeight(110)
        self.filters.setMaximumHeight(170)
        self.filters.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        v.addWidget(self.filters)
        row = QHBoxLayout()
        btn_none = QPushButton("Снять все")
        btn_none.clicked.connect(self._uncheck_filters)
        row.addWidget(btn_none)
        row.addStretch()
        v.addLayout(row)
        root.addWidget(g)

        # --- Zoom / Скорость ---
        g = QGroupBox("Изменения кадра")
        f = QFormLayout(g)
        f.setContentsMargins(10, 6, 10, 8)
        self.zoom = RangeRow(*ZOOM_RANGE, 100, (95, 115))
        self.speed = RangeRow(*SPEED_RANGE, 100, (95, 110))
        f.addRow("Zoom:", self.zoom)
        f.addRow("Скорость:", self.speed)
        root.addWidget(g)

        # --- Наложение ---
        g = QGroupBox("Наложение картинки / GIF")
        f = QFormLayout(g)
        f.setContentsMargins(10, 6, 10, 8)
        row = QHBoxLayout()
        self.overlay_path = PathLineEdit(OVERLAY_EXTENSIONS)
        self.overlay_path.setPlaceholderText("PNG, JPG, WEBP, GIF — или перетащите сюда")
        btn_ov = QPushButton("Обзор…")
        btn_ov.clicked.connect(self._pick_overlay)
        btn_ov_clear = QPushButton("✕")
        btn_ov_clear.setFixedWidth(30)
        btn_ov_clear.clicked.connect(self.overlay_path.clear)
        row.addWidget(self.overlay_path, 1)
        row.addWidget(btn_ov)
        row.addWidget(btn_ov_clear)
        self.overlay_pos = QComboBox()
        self.overlay_pos.addItems(list(OVERLAY_POSITIONS))
        self.overlay_pos.setCurrentText("Низ-Право")
        f.addRow("Файл:", row)
        f.addRow("Позиция:", self.overlay_pos)
        root.addWidget(g)

        # --- Опции ---
        g = QGroupBox("Опции")
        v = QVBoxLayout(g)
        v.setContentsMargins(10, 6, 10, 8)
        self.strip_meta = QCheckBox("Очистить метаданные")
        self.strip_meta.setChecked(True)
        self.mute = QCheckBox("Удалить звук")
        self.hw = QCheckBox("Аппаратное кодирование (VideoToolbox)")
        self.hw.setToolTip("Быстрее в несколько раз на Apple Silicon. При ошибке автоматически используется libx264.")
        vt = ff.has_videotoolbox()
        self.hw.setEnabled(vt)
        self.hw.setChecked(vt)
        for w in (self.strip_meta, self.mute, self.hw):
            v.addWidget(w)
        root.addWidget(g)

        # --- Папка вывода ---
        g = QGroupBox("Куда сохранять")
        v = QVBoxLayout(g)
        v.setContentsMargins(10, 6, 10, 8)
        self.out_near = QRadioButton("Рядом с исходником, в подпапку «uniq»")
        self.out_custom = QRadioButton("В папку:")
        self.out_near.setChecked(True)
        row = QHBoxLayout()
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("Выберите папку…")
        btn_out = QPushButton("Обзор…")
        btn_out.clicked.connect(self._pick_out_dir)
        row.addWidget(self.out_custom)
        row.addWidget(self.out_dir, 1)
        row.addWidget(btn_out)
        v.addWidget(self.out_near)
        v.addLayout(row)
        root.addWidget(g)
        self.out_custom.toggled.connect(lambda on: (self.out_dir.setEnabled(on), btn_out.setEnabled(on)))
        self.out_custom.toggled.emit(False)

        root.addStretch()
        self._on_preset()
        # Горизонтальной прокрутки нет — ширина панели не может быть меньше контента.
        self.setMinimumWidth(body.minimumSizeHint().width() + self.frameWidth() * 2 + 2)

    # --- обработчики ---
    def _on_preset(self):
        p = self.preset.currentData()
        self.blur_bg.setEnabled(not p.is_original)

    def _uncheck_filters(self):
        for i in range(self.filters.count()):
            self.filters.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _pick_overlay(self):
        exts = " ".join("*" + e for e in sorted(OVERLAY_EXTENSIONS))
        p, _ = QFileDialog.getOpenFileName(self, "Файл наложения", self.overlay_path.text() or "",
                                           f"Изображения и GIF ({exts});;Все файлы (*)")
        if p:
            self.overlay_path.setText(p)

    def _pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для результатов", self.out_dir.text() or "")
        if d:
            self.out_dir.setText(d)
            self.out_custom.setChecked(True)

    # --- результат ---
    def checked_filters(self) -> list[str]:
        return [self.filters.item(i).text() for i in range(self.filters.count())
                if self.filters.item(i).checkState() == Qt.CheckState.Checked]

    def validate(self) -> str | None:
        if self.out_custom.isChecked() and not self.out_dir.text().strip():
            return "Укажите папку для сохранения или выберите «Рядом с исходником»."
        ov = self.overlay_path.text().strip()
        if ov and not os.path.isfile(ov):
            return f"Файл наложения не найден:\n{ov}"
        return None

    def batch_settings(self) -> BatchSettings:
        zoom, zoom_rng = self.zoom.result()
        speed, speed_rng = self.speed.result()
        job = JobSettings(
            preset=self.preset.currentData(),
            blur_background=self.blur_bg.isChecked() and self.blur_bg.isEnabled(),
            filters=self.checked_filters(),
            zoom=zoom, speed=speed,
            overlay_file=self.overlay_path.text().strip() or None,
            overlay_pos=self.overlay_pos.currentText(),
            mute_audio=self.mute.isChecked(),
            strip_metadata=self.strip_meta.isChecked(),
            hw_encode=self.hw.isChecked() and self.hw.isEnabled(),
        )
        out_dir = self.out_dir.text().strip() if self.out_custom.isChecked() else None
        return BatchSettings(job=job, out_dir=out_dir, zoom_range=zoom_rng, speed_range=speed_rng)

    # --- QSettings ---
    def save(self, s: QSettings):
        s.setValue("preset", self.preset.currentIndex())
        s.setValue("blur_bg", self.blur_bg.isChecked())
        s.setValue("filters", self.checked_filters())
        self.zoom.save(s, "zoom")
        self.speed.save(s, "speed")
        s.setValue("overlay_path", self.overlay_path.text())
        s.setValue("overlay_pos", self.overlay_pos.currentText())
        s.setValue("strip_meta", self.strip_meta.isChecked())
        s.setValue("mute", self.mute.isChecked())
        s.setValue("hw", self.hw.isChecked())
        s.setValue("out_custom", self.out_custom.isChecked())
        s.setValue("out_dir", self.out_dir.text())

    def load(self, s: QSettings):
        def b(key, default):
            v = s.value(key, default)
            return v if isinstance(v, bool) else str(v).lower() == "true"

        self.preset.setCurrentIndex(int(s.value("preset", 0)))
        self.blur_bg.setChecked(b("blur_bg", False))
        chosen = s.value("filters", []) or []
        if isinstance(chosen, str):
            chosen = [chosen]
        for i in range(self.filters.count()):
            it = self.filters.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.text() in chosen else Qt.CheckState.Unchecked)
        self.zoom.load(s, "zoom")
        self.speed.load(s, "speed")
        self.overlay_path.setText(str(s.value("overlay_path", "")))
        self.overlay_pos.setCurrentText(str(s.value("overlay_pos", "Низ-Право")))
        self.strip_meta.setChecked(b("strip_meta", True))
        self.mute.setChecked(b("mute", False))
        if self.hw.isEnabled():
            self.hw.setChecked(b("hw", True))
        self.out_dir.setText(str(s.value("out_dir", "")))
        (self.out_custom if b("out_custom", False) else self.out_near).setChecked(True)
