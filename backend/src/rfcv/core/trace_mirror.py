"""Bản sao trace lên Supabase (PostgREST). SQLite vẫn là nguồn chính; lỗi mạng chỉ làm mất bản sao, không làm hỏng lần chạy."""

from __future__ import annotations

import atexit
import json
import queue
import threading
import urllib.request
from collections.abc import Mapping
from typing import Any

TABLE = "trace_events"
_BATCH = 50
_FLUSH_S = 1.0


class SupabaseMirror:
    def __init__(self, url: str, key: str, *, timeout: float = 10.0) -> None:
        self._endpoint = f"{url.rstrip('/')}/rest/v1/{TABLE}"
        self._headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal,resolution=ignore-duplicates",
        }
        self._timeout = timeout
        self._q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="supabase-mirror", daemon=True)
        self._thread.start()
        atexit.register(self.close)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> SupabaseMirror | None:
        url, key = env.get("SUPABASE_URL", "").strip(), env.get("SUPABASE_KEY", "").strip()
        return cls(url, key) if url and key else None

    def push(self, row: dict[str, Any]) -> None:
        self._q.put(row)

    def close(self) -> None:
        if self._thread.is_alive():
            self._q.put(None)
            self._thread.join(timeout=15)

    def _run(self) -> None:
        batch: list[dict[str, Any]] = []
        while True:
            try:
                item = self._q.get(timeout=_FLUSH_S)
            except queue.Empty:
                item = ...
            if item is None:
                self._send(batch)
                return
            if item is not ...:
                batch.append(item)  # type: ignore[arg-type]
            if batch and (item is ... or len(batch) >= _BATCH):
                self._send(batch)
                batch = []

    def _send(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        req = urllib.request.Request(self._endpoint, json.dumps(batch).encode(), self._headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=self._timeout).close()
        except Exception:
            self.dropped += len(batch)
