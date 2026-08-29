"""Atomic durable store for ARES-owned agent definitions."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .definitions import AgentDefinition


class DefinitionStore:
    def __init__(self, path: Path | None = None) -> None:
        home = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
        self.path = path or home / "control-plane" / "definitions.json"
        self._lock = threading.Lock()

    def list(self) -> list[AgentDefinition]:
        with self._lock:
            return self._read()

    def get(self, agent_id: str) -> AgentDefinition | None:
        return next((row for row in self.list() if row.id == agent_id), None)

    def put(self, definition: AgentDefinition) -> AgentDefinition:
        with self._lock:
            rows = self._read()
            updated = [row for row in rows if row.id != definition.id] + [definition]
            self._write(sorted(updated, key=lambda row: row.id))
        return definition

    def _read(self) -> list[AgentDefinition]:
        if not self.path.exists():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported ARES definition-store version")
        return [AgentDefinition.from_dict(row) for row in value.get("agents") or []]

    def _write(self, rows: list[AgentDefinition]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "agents": [row.as_dict() for row in rows]}
        fd, temporary = tempfile.mkstemp(prefix="definitions-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
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
