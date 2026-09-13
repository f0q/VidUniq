"""Список доступа: разрешённые/заблокированные пользователи, учёт чужих попыток. JSON на диске."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

MAX_STRANGER_ATTEMPTS = 10


@dataclass
class UserStat:
    last_seen: float = 0.0
    files: int = 0
    added_at: float = 0.0
    name: str = ""


@dataclass
class _State:
    allowed: set[int] = field(default_factory=set)
    blocked: set[int] = field(default_factory=set)
    strangers: dict[int, int] = field(default_factory=dict)   # id → число попыток
    stats: dict[int, UserStat] = field(default_factory=dict)


class AccessStore:
    """base_allowed/admins — из окружения (всегда действуют); allowed — динамический список из файла."""

    def __init__(self, path: str, base_allowed: Iterable[int] = (), admins: Iterable[int] = ()):
        self.path = path
        self.base_allowed = set(base_allowed)
        self.admins = set(admins)
        self._lock = threading.Lock()
        self._s = _State()
        self._load()

    # --- хранение ---
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        self._s.allowed = {int(x) for x in d.get("allowed", [])}
        self._s.blocked = {int(x) for x in d.get("blocked", [])}
        self._s.strangers = {int(k): int(v) for k, v in d.get("strangers", {}).items()}
        self._s.stats = {int(k): UserStat(**v) for k, v in d.get("stats", {}).items()}

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "allowed": sorted(self._s.allowed),
                "blocked": sorted(self._s.blocked),
                "strangers": {str(k): v for k, v in self._s.strangers.items()},
                "stats": {str(k): vars(v) for k, v in self._s.stats.items()},
            }, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # --- запросы ---
    def is_admin(self, uid: int) -> bool:
        return uid in self.admins

    def is_allowed(self, uid: int) -> bool:
        if uid in self.admins:
            return True
        with self._lock:
            return uid not in self._s.blocked and (uid in self.base_allowed or uid in self._s.allowed)

    def is_blocked(self, uid: int) -> bool:
        with self._lock:
            return uid in self._s.blocked

    def stranger_attempt(self, uid: int) -> bool:
        """Регистрирует попытку чужого. True — это первая попытка, можно один раз ответить с ID."""
        with self._lock:
            if uid in self._s.blocked:
                return False
            n = self._s.strangers.get(uid, 0) + 1
            self._s.strangers[uid] = n
            if n >= MAX_STRANGER_ATTEMPTS:
                self._s.blocked.add(uid)
                self._s.strangers.pop(uid, None)
            self._save()
            return n == 1

    def touch(self, uid: int, name: str = "", files: int = 0):
        with self._lock:
            st = self._s.stats.setdefault(uid, UserStat(added_at=time.time()))
            st.last_seen = time.time()
            st.files += files
            if name:
                st.name = name
            if files:
                self._save()

    # --- администрирование ---
    def add(self, uid: int) -> bool:
        """Разрешить (и разблокировать). False — уже был разрешён."""
        with self._lock:
            was = uid in self._s.allowed or uid in self.base_allowed
            self._s.allowed.add(uid)
            self._s.blocked.discard(uid)
            self._s.strangers.pop(uid, None)
            self._s.stats.setdefault(uid, UserStat(added_at=time.time()))
            self._save()
            return not was or uid in self._s.blocked

    def remove(self, uid: int) -> bool:
        with self._lock:
            was = uid in self._s.allowed or uid in self.base_allowed
            self._s.allowed.discard(uid)
            self.base_allowed.discard(uid)
            self._save()
            return was

    def block(self, uid: int):
        with self._lock:
            self._s.blocked.add(uid)
            self._s.allowed.discard(uid)
            self.base_allowed.discard(uid)
            self._save()

    def snapshot(self) -> dict:
        with self._lock:
            allowed = sorted((self.base_allowed | self._s.allowed) - self._s.blocked)
            return {
                "admins": sorted(self.admins),
                "allowed": [(u, self._s.stats.get(u, UserStat())) for u in allowed],
                "blocked": sorted(self._s.blocked),
                "strangers": dict(self._s.strangers),
            }
