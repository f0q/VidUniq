"""Точка входа: логирование, QApplication, главное окно."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def log_dir() -> str:
    if sys.platform == "darwin":
        d = os.path.expanduser("~/Library/Logs/VidUniq")
    elif sys.platform.startswith("win"):
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VidUniq", "logs")
    else:
        d = os.path.expanduser("~/.local/state/viduniq")
    os.makedirs(d, exist_ok=True)
    return d


def log_path() -> str:
    return os.path.join(log_dir(), "app.log")


def setup_logging():
    handlers: list[logging.Handler] = [RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=2, encoding="utf-8")]
    if sys.stdout and not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def selftest() -> int:
    """`VidUniq --selftest`: проверка бандла без GUI (используется в сборке и CI)."""
    from . import __version__
    from .core import ffmpeg as ff
    print(f"VidUniq {__version__}")
    for tool in ("ffmpeg", "ffprobe"):
        p = ff.locate(tool)
        print(f"{tool}: {p or 'НЕ НАЙДЕН'}")
        if not p:
            return 1
    print("videotoolbox:", ff.has_videotoolbox())
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--version" in sys.argv:
        from . import __version__
        print(__version__)
        return 0
    setup_logging()
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    from . import APP_NAME, __version__
    from .ui.main_window import MainWindow

    QCoreApplication.setOrganizationName("f0q")
    QCoreApplication.setOrganizationDomain("f0q.github.io")
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    logging.info("%s %s запущен", APP_NAME, __version__)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
