"""Server-side session store: the GitHub user token never leaves the portal process (not in the cookie)."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass


@dataclass
class SessionData:
    developer_id: str
    github_id: int
    github_login: str
    token: str
    expires: float


class SessionStore:
    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._data: dict[str, SessionData] = {}
        self._lock = threading.Lock()

    def create(self, developer_id: str, github_id: int, login: str, token: str) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._data[sid] = SessionData(developer_id, github_id, login, token, time.time() + self.ttl)
        return sid

    def get(self, sid: str | None) -> SessionData | None:
        if not sid:
            return None
        with self._lock:
            data = self._data.get(sid)
            if data and data.expires < time.time():
                del self._data[sid]
                return None
            return data

    def drop(self, sid: str | None) -> None:
        if sid:
            with self._lock:
                self._data.pop(sid, None)
