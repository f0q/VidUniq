"""Конфигурация бота из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Config:
    bot_token: str = ""
    allowed_users: set[int] = field(default_factory=set)
    admin_users: set[int] = field(default_factory=set)
    bot_api_url: str = ""                 # пусто → облачный api.telegram.org
    local_mode: bool = False              # True → Bot API сервер на этой же машине, файлы читаем с диска
    work_dir: str = "/data"
    max_parallel: int = 1
    max_variants: int = 5
    max_file_mb: int = 2000
    progress_interval: float = 3.0
    bot_api_files_dir: str = ""           # каталог файлов локального Bot API (для очистки его кеша)
    file_cache_ttl_min: int = 60          # sweeper: удалять файлы сервера старше N минут (0 — выключить)

    @classmethod
    def from_env(cls) -> "Config":
        def ids(name: str) -> set[int]:
            out = set()
            for part in os.environ.get(name, "").replace(";", ",").split(","):
                part = part.strip()
                if part.lstrip("-").isdigit():
                    out.add(int(part))
            return out

        api_url = os.environ.get("BOT_API_URL", "").strip().rstrip("/")
        return cls(
            bot_token=os.environ.get("BOT_TOKEN", "").strip(),
            allowed_users=ids("ALLOWED_USERS"),
            admin_users=ids("ADMIN_USERS"),
            bot_api_url=api_url,
            local_mode=_env_bool("LOCAL_MODE", bool(api_url)),
            work_dir=os.environ.get("WORK_DIR", "/data").strip() or "/data",
            max_parallel=max(1, _env_int("MAX_PARALLEL", 1)),
            max_variants=max(1, min(10, _env_int("MAX_VARIANTS", 5))),
            max_file_mb=max(1, _env_int("MAX_FILE_MB", 2000 if api_url else 20)),
            progress_interval=max(1.0, float(os.environ.get("PROGRESS_INTERVAL", "3") or 3)),
            bot_api_files_dir=os.environ.get("BOT_API_FILES_DIR", "").strip().rstrip("/"),
            file_cache_ttl_min=max(0, _env_int("FILE_CACHE_TTL_MIN", 60)),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.bot_token or ":" not in self.bot_token:
            errors.append("BOT_TOKEN не задан (получите у @BotFather)")
        if not self.allowed_users:
            errors.append("ALLOWED_USERS пуст — бот никого не пустит. Укажите Telegram ID через запятую")
        return errors

    def is_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_users or user_id in self.admin_users

    @property
    def tmp_dir(self) -> str:
        return os.path.join(self.work_dir, "tmp")

    @property
    def users_dir(self) -> str:
        return os.path.join(self.work_dir, "users")
