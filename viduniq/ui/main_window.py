"""Главное окно: список файлов, настройки, нижняя панель прогресса, drag&drop на всё окно."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import QRect, QSettings, QSize, Qt, QUrl
from PySide6.QtGui import (
    QAction, QCloseEvent, QColor, QDesktopServices, QDragEnterEvent, QDragLeaveEvent, QDropEvent,
    QFont, QIcon, QKeySequence, QPainter, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..core import ffmpeg as ff
from ..core.constants import VALID_INPUT_EXTENSIONS
from ..core.worker import BatchSummary, Worker
from .file_list import DONE, FAILED, RUNNING, FileListWidget
from .settings_panel import SettingsPanel


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "viduniq", "resources", name)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", name)


def reveal_in_file_manager(path: str):
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", path] if os.path.isfile(path) else ["explorer", path])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))


class DropOverlay(QWidget):
    """Полупрозрачная подсказка поверх окна во время перетаскивания."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAcceptDrops(False)
        self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hl = self.palette().highlight().color()
        bg = QColor(hl)
        bg.setAlphaF(0.12)
        p.fillRect(self.rect(), bg)
        pen = QPen(hl, 3, Qt.PenStyle.DashLine)
        p.setPen(pen)
        r = self.rect().adjusted(16, 16, -16, -16)
        p.drawRoundedRect(r, 14, 14)
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(hl)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Отпустите файлы или папки")
        p.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        icon = resource_path("icon.png")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.worker: Optional[Worker] = None
        self._summary: Optional[BatchSummary] = None
        self._total = 0
        self._done_count = 0

        self._build_menu()
        self._build_ui()
        self._load_settings()
        self._update_buttons()
        self._check_ffmpeg()

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("Файл")
        a = QAction("Добавить файлы…", self)
        a.setShortcut(QKeySequence.StandardKey.Open)
        a.triggered.connect(self.add_files_dialog)
        m_file.addAction(a)
        a = QAction("Добавить папку…", self)
        a.setShortcut(QKeySequence("Ctrl+Shift+O"))
        a.triggered.connect(self.add_folder_dialog)
        m_file.addAction(a)
        m_file.addSeparator()
        a = QAction("Выход", self)
        a.setMenuRole(QAction.MenuRole.QuitRole)
        a.setShortcut(QKeySequence.StandardKey.Quit)
        a.triggered.connect(self.close)
        m_file.addAction(a)

        m_help = mb.addMenu("Справка")
        a = QAction("Открыть лог", self)
        a.triggered.connect(self._open_log)
        m_help.addAction(a)
        a = QAction("Проект на GitHub", self)
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/f0q/Video-Uniqueizer")))
        m_help.addAction(a)
        a = QAction(f"О программе {APP_NAME}", self)
        a.setMenuRole(QAction.MenuRole.AboutRole)
        a.triggered.connect(self._about)
        m_help.addAction(a)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        # --- левая часть: список ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 8, 6, 8)
        lv.setSpacing(6)
        toolbar = QHBoxLayout()
        self.btn_add = QPushButton("Добавить файлы")
        self.btn_add.clicked.connect(self.add_files_dialog)
        self.btn_folder = QPushButton("Папку")
        self.btn_folder.clicked.connect(self.add_folder_dialog)
        self.btn_remove = QPushButton("Удалить")
        self.btn_remove.clicked.connect(lambda: self.file_list.remove_selected())
        self.btn_clear = QPushButton("Очистить")
        self.btn_clear.clicked.connect(lambda: self.file_list.clear_all())
        for b in (self.btn_add, self.btn_folder, self.btn_remove, self.btn_clear):
            toolbar.addWidget(b)
        toolbar.addStretch()
        self.count_label = QLabel("")
        toolbar.addWidget(self.count_label)
        lv.addLayout(toolbar)
        self.file_list = FileListWidget()
        self.file_list.files_changed.connect(self._update_buttons)
        self.file_list.itemSelectionChanged.connect(self._update_buttons)
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self.file_list)
        lv.addWidget(frame, 1)
        self.splitter.addWidget(left)

        # --- правая часть: настройки ---
        self.settings = SettingsPanel()
        self.splitter.addWidget(self.settings)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([520, 420])

        # --- нижняя панель ---
        bottom = QFrame()
        bottom.setFrameShape(QFrame.Shape.NoFrame)
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(12, 8, 12, 10)
        bl.setSpacing(10)
        prog_col = QVBoxLayout()
        prog_col.setSpacing(2)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        self.status_label = QLabel("Готов к работе")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        prog_col.addWidget(self.progress)
        prog_col.addWidget(self.status_label)
        bl.addLayout(prog_col, 1)
        self.btn_open_out = QPushButton("Открыть папку")
        self.btn_open_out.clicked.connect(self._open_output)
        self.btn_open_out.hide()
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.cancel_processing)
        self.btn_cancel.hide()
        self.btn_start = QPushButton("Обработать")
        self.btn_start.setDefault(True)
        self.btn_start.setMinimumWidth(140)
        self.btn_start.setMinimumHeight(34)
        self.btn_start.clicked.connect(self.start_processing)
        bl.addWidget(self.btn_open_out)
        bl.addWidget(self.btn_cancel)
        bl.addWidget(self.btn_start)
        root.addWidget(bottom)

        self.overlay = DropOverlay(central)
        # Минимальный размер окна — из реальных minimumSizeHint частей, а не с потолка.
        self.setMinimumSize(max(880, self.minimumSizeHint().width()), 520)

    # ------------------------------------------------------------ settings
    def _load_settings(self):
        s = QSettings()
        geo = s.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1040, 640)
        split = s.value("window/splitter")
        if split:
            self.splitter.restoreState(split)
        s.beginGroup("job")
        self.settings.load(s)
        s.endGroup()

    def _save_settings(self):
        s = QSettings()
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/splitter", self.splitter.saveState())
        s.beginGroup("job")
        self.settings.save(s)
        s.endGroup()

    def _check_ffmpeg(self):
        if not ff.locate("ffmpeg") or not ff.locate("ffprobe"):
            self.status_label.setText("⚠️ FFmpeg не найден — обработка недоступна")
            QMessageBox.critical(
                self, "FFmpeg не найден",
                "Не удалось найти ffmpeg/ffprobe.\n\n"
                "Установите: brew install ffmpeg\n"
                "или запустите scripts/fetch_ffmpeg.sh, чтобы положить бинарники в vendor/ffmpeg/.",
            )

    # ------------------------------------------------------------ actions
    def add_files_dialog(self):
        exts = " ".join("*" + e for e in sorted(VALID_INPUT_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите видео или GIF", QSettings().value("last_dir", ""),
            f"Видео и GIF ({exts});;Все файлы (*)",
        )
        if files:
            QSettings().setValue("last_dir", os.path.dirname(files[0]))
            self.file_list.add_paths(files)

    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите папку", QSettings().value("last_dir", ""))
        if d:
            QSettings().setValue("last_dir", d)
            n = self.file_list.add_paths([d])
            if n == 0:
                QMessageBox.information(self, "Пусто", "В папке не найдено поддерживаемых видео или GIF.")

    def _update_buttons(self):
        n = self.file_list.count()
        running = self.worker is not None and self.worker.isRunning()
        self.count_label.setText(f"{n} файл(ов)" if n else "")
        self.btn_start.setEnabled(n > 0 and not running)
        self.btn_remove.setEnabled(bool(self.file_list.selectedItems()) and not running)
        self.btn_clear.setEnabled(n > 0 and not running)
        self.btn_add.setEnabled(not running)
        self.btn_folder.setEnabled(not running)
        self.settings.setEnabled(not running)

    def start_processing(self):
        if self.worker is not None and self.worker.isRunning():
            return
        err = self.settings.validate()
        if err:
            QMessageBox.warning(self, "Проверьте настройки", err)
            return
        paths = self.file_list.paths()
        if not paths:
            return
        self._save_settings()
        self.file_list.reset_statuses()
        self._total = len(paths)
        self._done_count = 0
        self._summary = None
        self.progress.setValue(0)
        self.btn_open_out.hide()
        self.btn_cancel.show()
        self.btn_cancel.setEnabled(True)
        self.status_label.setText("Подготовка…")

        self.worker = Worker(paths, self.settings.batch_settings(), self)
        self.worker.file_started.connect(self._on_file_started)
        self.worker.file_progress.connect(self._on_file_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.file_failed.connect(self._on_file_failed)
        self.worker.batch_finished.connect(self._on_batch_finished)
        self.worker.finished.connect(self._update_buttons)
        self.worker.start()
        self._update_buttons()

    def cancel_processing(self):
        if self.worker is not None and self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.status_label.setText("Останавливаю…")
            self.worker.cancel()

    # ------------------------------------------------------------ worker slots
    def _set_overall(self, idx: int, frac: float):
        overall = (idx + frac) / self._total if self._total else 0
        self.progress.setValue(int(overall * 1000))

    def _on_file_started(self, idx: int):
        self.file_list.set_status(idx, RUNNING, progress=0.0)
        name = os.path.basename(self.file_list.paths()[idx])
        self.status_label.setText(f"{idx + 1}/{self._total} · {name}")
        self._set_overall(idx, 0.0)

    def _on_file_progress(self, idx: int, frac: float):
        self.file_list.set_progress(idx, frac)
        name = os.path.basename(self.file_list.paths()[idx])
        self.status_label.setText(f"{idx + 1}/{self._total} · {name} · {int(frac * 100)}%")
        self._set_overall(idx, frac)

    def _on_file_done(self, idx: int, out_path: str):
        self.file_list.set_status(idx, DONE, out_path=out_path)
        self._done_count += 1
        self._set_overall(idx, 1.0)

    def _on_file_failed(self, idx: int, msg: str):
        self.file_list.set_status(idx, FAILED, message=msg)
        self._set_overall(idx, 1.0)

    def _on_batch_finished(self, summary: BatchSummary):
        self._summary = summary
        self.btn_cancel.hide()
        ok, bad = len(summary.done), len(summary.failed)
        if summary.cancelled:
            self.status_label.setText(f"Отменено · готово {ok}, ошибок {bad}")
            self.progress.setValue(0)
        else:
            self.progress.setValue(1000)
            self.status_label.setText(f"Готово · {ok} успешно" + (f", {bad} с ошибкой" if bad else ""))
        if summary.out_dirs:
            self.btn_open_out.show()
        self._update_buttons()
        if summary.cancelled:
            return
        if bad and not ok:
            first = next(iter(summary.failed.values()))
            QMessageBox.critical(self, "Ошибка", f"Ни один файл не обработан.\n\n{first[-800:]}")
        elif bad:
            QMessageBox.warning(self, "Готово с ошибками",
                                f"Успешно: {ok}\nС ошибкой: {bad}\n\nНаведите на файл со значком ❌, чтобы увидеть причину.")
        else:
            QMessageBox.information(self, "Готово", f"Обработано файлов: {ok}")

    def _open_output(self):
        if self._summary and self._summary.out_dirs:
            for d in sorted(self._summary.out_dirs):
                reveal_in_file_manager(d)

    # ------------------------------------------------------------ misc
    def _open_log(self):
        from ..app import log_path
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_path()))

    def _about(self):
        QMessageBox.about(
            self, f"О программе {APP_NAME}",
            f"<b>{APP_NAME} {__version__}</b><br>"
            "Уникализатор видео для Reels, TikTok, Shorts и других соцсетей.<br><br>"
            "Форк <a href='https://github.com/0xd5f/Video-Uniqueizer'>Video-Uniqueizer</a> от 0xd5f.<br>"
            f"FFmpeg: {ff.locate('ffmpeg') or 'не найден'}",
        )

    # ------------------------------------------------------------ drag & drop
    @staticmethod
    def _local_paths(event) -> list[str]:
        return [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls() and self._local_paths(e) and not (self.worker and self.worker.isRunning()):
            e.acceptProposedAction()
            self.overlay.setGeometry(self.centralWidget().rect())
            self.overlay.raise_()
            self.overlay.show()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, e: QDragLeaveEvent):
        self.overlay.hide()

    def dropEvent(self, e: QDropEvent):
        self.overlay.hide()
        paths = self._local_paths(e)
        if paths:
            e.acceptProposedAction()
            self.file_list.add_paths(paths)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.overlay.isVisible():
            self.overlay.setGeometry(self.centralWidget().rect())

    def closeEvent(self, e: QCloseEvent):
        if self.worker is not None and self.worker.isRunning():
            r = QMessageBox.question(self, "Идёт обработка", "Прервать обработку и выйти?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.worker.cancel()
            self.worker.wait(5000)
        self._save_settings()
        e.accept()
