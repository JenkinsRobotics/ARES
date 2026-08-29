"""Atomic JSON persistence for ARES-owned automation metadata."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable


class AutomationStore:
    def __init__(self, path: Path | None = None) -> None:
        home = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
        self.path = path or home / "automation" / "state.json"
        self._lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return self._empty()
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError("unsupported ARES automation-store version")
            for key, default in self._empty().items():
                value.setdefault(key, default)
            return value

    def update(self, fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._lock:
            value = self.read()
            fn(value)
            self._write(value)
            return value

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": 1,
            "paused": False,
            "agents": [],
            "goals": [],
            "runs": [],
            "events": [],
            "approvals": [],
            "configuration_changes": [],
        }

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="automation-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
