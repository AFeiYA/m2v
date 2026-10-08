"""Durable task journal; interrupted work is never silently regenerated."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path


class _Task(dict):
    def __init__(self, value, save):
        super().__init__(value)
        self._save = save
        self._lock = threading.RLock()

    def update(self, *args, **kwargs):
        with self._lock:
            super().update(*args, **kwargs)
            self._save(dict(self))

    def __setitem__(self, key, value):
        self.update({key: value})


class TaskStore(dict):
    def __init__(self, directory, retention_days=7):
        super().__init__()
        self.directory = directory
        self.retention_seconds = retention_days * 86400
        self.lock = threading.RLock()

    def _path(self, key):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key):
            raise ValueError("Invalid task ID")
        directory = Path(self.directory() if callable(self.directory) else self.directory)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{key}.json"

    def _save(self, key, value):
        path = self._path(key)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                json.dump(value, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def __setitem__(self, key, value):
        with self.lock:
            value = dict(value)
            value.setdefault("created_at", time.time())
            task = _Task(value, lambda data: self._save(key, data))
            self._save(key, value)
            super().__setitem__(key, task)

    def get(self, key, default=None):
        with self.lock:
            task = super().get(key)
            if task is not None:
                if time.time() - task.get("created_at", time.time()) > self.retention_seconds:
                    self._path(key).unlink(missing_ok=True)
                    super().pop(key, None)
                    return default
                return task
            try:
                path = self._path(key)
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    return default
                if time.time() - value.get("created_at", path.stat().st_mtime) > self.retention_seconds:
                    path.unlink(missing_ok=True)
                    return default
            except (OSError, ValueError, TypeError):
                return default
            if value.get("status") in {"pending", "running"}:
                value.update(status="interrupted", phase="interrupted",
                             error="Server restarted. Rendering was interrupted. Start a new job to retry.",
                             message="Server restarted; this job was not automatically regenerated.")
            self[key] = value
            return super().get(key)

    def cleanup(self):
        """Remove expired journals only; never delete audio or finished videos."""
        directory = self._path("cleanup").parent
        with self.lock:
            for path in directory.glob("*.json"):
                try:
                    if time.time() - path.stat().st_mtime > self.retention_seconds:
                        path.unlink(missing_ok=True)
                        super().pop(path.stem, None)
                except OSError:
                    continue
