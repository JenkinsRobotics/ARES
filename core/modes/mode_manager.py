"""ARES Mode Manager — State coordinator and background reflection executor."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .operating_modes import CognitiveMode, DreamReport, ModeState

logger = logging.getLogger(__name__)

_DEFAULT_STATE_FILE = "mode_state.json"


def _get_ares_home() -> Path:
    home = os.environ.get("ARES_HOME", "").strip()
    return Path(home).expanduser() if home else Path.home() / ".ares"


class ModeManager:
    """Coordinates active cognitive mode transitions, background dream cycles, and event dispatch."""

    _instance: ModeManager | None = None
    _lock = threading.RLock()

    def __init__(self, state_file: Path | None = None) -> None:
        self._state_file = state_file or (_get_ares_home() / _DEFAULT_STATE_FILE)
        self._listeners: list[Callable[[CognitiveMode, CognitiveMode], None]] = []
        self._dream_lock = threading.Lock()
        self._state = self._load_state()

    @classmethod
    def get_instance(cls) -> ModeManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def state(self) -> ModeState:
        with self._lock:
            return self._state

    def _load_state(self) -> ModeState:
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return ModeState.from_dict(data)
        except Exception:
            logger.warning("Failed to load mode state from %s; resetting to default", self._state_file, exc_info=True)
        return ModeState()

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_file.with_suffix(f".tmp.{os.getpid()}")
            tmp.write_text(json.dumps(self._state.as_dict(), indent=2), encoding="utf-8")
            os.replace(tmp, self._state_file)
        except Exception:
            logger.error("Failed to save mode state to %s", self._state_file, exc_info=True)

    def subscribe(self, listener: Callable[[CognitiveMode, CognitiveMode], None]) -> None:
        """Register a callback for mode transitions: listener(prev_mode, new_mode)."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[CognitiveMode, CognitiveMode], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def switch_mode(
        self,
        new_mode: CognitiveMode | str,
        session_id: str | None = None,
    ) -> ModeState:
        """Transition ARES to a new cognitive operating mode."""
        from .operating_modes import normalize_mode

        target_mode = normalize_mode(new_mode)
        prev_mode = self._state.current_mode
        with self._lock:
            self._state.previous_mode = prev_mode
            self._state.current_mode = target_mode
            self._state.switched_at = time.time()
            if target_mode == CognitiveMode.FOCUS:
                self._state.active_focus_session = session_id
                self._state.focus_runs_count += 1
            else:
                self._state.active_focus_session = None

            self._save_state()
            listeners_snapshot = list(self._listeners)

        # Notify listeners outside the lock
        for listener in listeners_snapshot:
            try:
                listener(prev_mode, target_mode)
            except Exception:
                logger.warning("Error in mode change listener", exc_info=True)

        logger.info("ARES cognitive mode transitioned: %s -> %s", prev_mode.value, target_mode.value)
        return self._state

    def trigger_dream_cycle(self, workspaces: list[str] | None = None) -> DreamReport:
        """Execute a Wonder/Dream reflection cycle to synthesize knowledge & index codebase ASTs."""
        with self._dream_lock:
            started_at = time.time()
            cycle_id = f"dream_{int(started_at)}_{uuid.uuid4().hex[:6]}"
            report = DreamReport(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=started_at,
            )

            try:
                from core.knowledge.repomap import build_workspace_repomap
                from api.workspace import load_workspaces

                target_workspaces: list[str] = []
                if workspaces:
                    target_workspaces = [str(w) for w in workspaces]
                else:
                    registered = load_workspaces()
                    target_workspaces = [item["path"] for item in registered if isinstance(item, dict) and "path" in item]

                total_symbols = 0
                total_files = 0
                insights = []

                for ws_path in target_workspaces:
                    p = Path(ws_path).expanduser().resolve()
                    if not p.is_dir():
                        continue
                    report.workspaces_scanned.append(str(p))
                    repomap_result = build_workspace_repomap(p, max_files=100)
                    total_symbols += repomap_result.get("total_symbols", 0)
                    total_files += repomap_result.get("scanned_files", 0)
                    if repomap_result.get("total_symbols", 0) > 0:
                        insights.append(f"Indexed {repomap_result['total_symbols']} symbols across {repomap_result['scanned_files']} files in {p.name}")

                report.symbols_indexed = total_symbols
                report.files_analyzed = total_files
                report.insights = insights
                report.completed_at = time.time()
                report.status = "completed"

                with self._lock:
                    self._state.last_dream_at = report.completed_at
                    self._state.dreams_count += 1
                    self._state.last_dream_report = report.as_dict()
                    self._save_state()

                logger.info("Dream cycle %s completed in %.2fms: %d symbols indexed", cycle_id, report.duration_ms, total_symbols)
                return report

            except Exception as exc:
                report.completed_at = time.time()
                report.status = "failed"
                report.error = str(exc)
                logger.error("Dream cycle %s failed: %s", cycle_id, exc, exc_info=True)
                return report


def get_mode_manager() -> ModeManager:
    """Return the global ARES ModeManager instance."""
    return ModeManager.get_instance()
