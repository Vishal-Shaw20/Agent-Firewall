"""
audit_log.py — Decision/audit log for the proxy.

Writes to Redis when it is reachable (SRS Section 6), otherwise falls back
to an append-only JSONL file at logs/audit.jsonl with the same entry format.
"""

import json
import os
import threading

import redis

from settings import LOGS_DIR

REDIS_KEY = "firewall:logs"


class AuditLog:
    def __init__(self, host: str = "localhost", port: int = 6379):
        self._lock  = threading.Lock()
        self._redis = None
        try:
            client = redis.Redis(host=host, port=port, decode_responses=True,
                                 socket_connect_timeout=1)
            client.ping()
            self._redis = client
        except Exception:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._file = LOGS_DIR / "audit.jsonl"

    @property
    def backend(self) -> str:
        return "redis" if self._redis else f"jsonl:{self._file}"

    def write(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        if self._redis:
            self._redis.lpush(REDIS_KEY, line)
            return
        with self._lock, open(self._file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def recent(self, limit: int = 20) -> list[dict]:
        """Newest first, matching Redis LPUSH order."""
        if self._redis:
            return [json.loads(x) for x in self._redis.lrange(REDIS_KEY, 0, limit - 1)]
        if not os.path.exists(self._file):
            return []
        with open(self._file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(x) for x in reversed(lines[-limit:])]


class NullAuditLog:
    """Used by in-process evaluation runs, which keep their own results."""
    backend = "none"
    def write(self, entry: dict) -> None: pass
    def recent(self, limit: int = 20) -> list[dict]: return []
