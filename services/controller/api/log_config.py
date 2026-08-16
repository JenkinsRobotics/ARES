"""ARES logging configuration — rotation, retention, and optional JSON format.

Configurable via environment variables:
    ARES_LOG_DIR         Log directory (default: $ARES_HOME/logs/)
    ARES_LOG_FORMAT      "text" (default) or "json"
    ARES_LOG_LEVEL       Python log level (default: INFO)
    ARES_LOG_MAX_BYTES   Max bytes per log file before rotation (default: 10MB)
    ARES_LOG_BACKUP_COUNT Number of rotated log files to keep (default: 5)

Called from ``fastapi_app/lifecycle.py`` during ``startup_runtime()``.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from pathlib import Path
from typing import Any

__all__ = ["configure_logging", "get_log_dir"]

_CONFIGURED = False

# ── Defaults ────────────────────────────────────────────────────────────

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_DEFAULT_BACKUP_COUNT = 5
_DEFAULT_LEVEL = "INFO"
_DEFAULT_FORMAT = "text"


def get_log_dir() -> Path:
    """Resolve the log directory, creating it if needed."""
    ares_home = Path(os.environ.get("ARES_HOME", "") or Path.home() / ".ares")
    log_dir = Path(os.environ.get("ARES_LOG_DIR", "") or (ares_home / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


# ── JSON Formatter ──────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter.

    Each log line is a single JSON object with:
        ts, level, logger, message, and optional exc, pid, thread.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            entry["exc"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            entry["request_id"] = record.request_id
        entry["pid"] = record.process
        entry["thread"] = record.threadName
        return json.dumps(entry, ensure_ascii=False, default=str)


# ── Text Formatter ──────────────────────────────────────────────────────

_TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_TEXT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ── Public API ──────────────────────────────────────────────────────────

def configure_logging() -> dict[str, Any]:
    """Install rotating file handler and optional JSON format on the root logger.

    Safe to call multiple times — only configures once.

    Returns a status dict for lifecycle logging.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return {"status": "already_configured"}

    log_dir = get_log_dir()
    log_format = os.environ.get("ARES_LOG_FORMAT", _DEFAULT_FORMAT).strip().lower()
    log_level_str = os.environ.get("ARES_LOG_LEVEL", _DEFAULT_LEVEL).strip().upper()
    max_bytes = int(os.environ.get("ARES_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES))
    backup_count = int(os.environ.get("ARES_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT))

    # Resolve log level
    log_level = getattr(logging, log_level_str, None)
    if not isinstance(log_level, int):
        log_level = logging.INFO
        log_level_str = "INFO"

    # Build formatter
    if log_format == "json":
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(_TEXT_FORMAT, datefmt=_TEXT_DATE_FORMAT)

    # ── Rotating file handler ───────────────────────────────────────
    log_file = log_dir / "ares-webui.log"
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # ── Console handler (stderr) ────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # ── Apply to root logger ────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Reduce noise from noisy libraries
    for noisy in ("httpcore", "httpx", "urllib3", "watchdog", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    return {
        "status": "configured",
        "log_file": str(log_file),
        "format": log_format,
        "level": log_level_str,
        "max_bytes": max_bytes,
        "backup_count": backup_count,
    }
