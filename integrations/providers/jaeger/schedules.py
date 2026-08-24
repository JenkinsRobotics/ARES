"""ARES adapter: WebUI cron panel → JaegerAI schedule store."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_QUERY_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jaeger-sched")
_QUERY_TIMEOUT_S = 3.0


def _query_with_timeout(what: str, args: dict[str, Any] | None = None) -> Any:
    from api.providers.jaeger.streaming import query_local_companion

    future = _QUERY_POOL.submit(query_local_companion, what, args or {})
    try:
        return future.result(timeout=_QUERY_TIMEOUT_S)
    except FuturesTimeout as exc:
        raise JaegerScheduleError("Jaeger schedule query timed out", 504) from exc


def _command_with_timeout(cmd: str, args: dict[str, Any] | None = None) -> Any:
    from api.providers.jaeger.streaming import command_local_companion

    future = _QUERY_POOL.submit(command_local_companion, cmd, args or {})
    try:
        return future.result(timeout=_QUERY_TIMEOUT_S)
    except FuturesTimeout as exc:
        raise JaegerScheduleError("Jaeger schedule command timed out", 504) from exc


class JaegerScheduleError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


def _job_from_jaeger(row: dict[str, Any]) -> dict[str, Any]:
    name = str(row.get("name") or "").strip()
    cron = str(row.get("cron") or row.get("schedule") or "")
    paused = bool(row.get("paused"))
    cancelled = bool(row.get("cancelled"))
    status = str(row.get("status") or ("paused" if paused else "active"))
    deliver = row.get("deliver")
    if isinstance(deliver, dict):
        deliver = deliver.get("channel") or "local"
    return {
        "id": name,
        "name": name,
        "prompt": str(row.get("prompt") or ""),
        "schedule": cron,
        "schedule_display": cron,
        "enabled": status == "active" and not cancelled,
        "paused": paused or status == "paused",
        "state": status,
        "next_run_at": row.get("next_run_at"),
        "last_run_at": row.get("last_run_at"),
        "last_status": None,
        "last_error": None,
        "deliver": deliver or "local",
        "toast_notifications": True,
        "owner": "jaeger",
        "profile": None,
    }


def runtime_status() -> dict[str, Any]:
    """Status for the scheduled-jobs banner: Jaeger scheduler, not a Hermes gateway."""
    from api.providers.jaeger.paths import jaeger_integration_disabled

    if jaeger_integration_disabled():
        # Answer exactly as an uninstalled JaegerAI does, so callers take the
        # ARES-owned path deterministically instead of by whether the
        # operator's agent is currently running.
        return {
            "available": False,
            "scheduler": "jaeger",
            "configured": False,
            "running": False,
            "job_count": 0,
            "in_flight": {},
            "message": "JaegerAI integration disabled (ARES_NO_JAEGER).",
        }
    try:
        payload = _query_with_timeout("cron", {})
        if not isinstance(payload, dict):
            payload = {}
        jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
        return {
            "available": True,
            "scheduler": "jaeger",
            "configured": True,
            "running": True,
            "job_count": int(payload.get("count") or len(jobs)),
            "in_flight": payload.get("running") or {},
            "message": "",
        }
    except Exception as exc:
        logger.debug("Jaeger schedule runtime unavailable: %s", exc, exc_info=True)
        return {
            "available": False,
            "scheduler": "jaeger",
            "configured": False,
            "running": False,
            "job_count": 0,
            "in_flight": {},
            "message": str(exc),
        }


def list_jobs() -> list[dict[str, Any]]:
    payload = _query_with_timeout("list_schedules", {})
    rows = payload.get("schedules") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise JaegerScheduleError("Jaeger returned an invalid schedule list")
    return [_job_from_jaeger(row) for row in rows if isinstance(row, dict)]


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip() or f"job_{uuid.uuid4().hex[:10]}"
    _command_with_timeout(
        "create_schedule",
        {
            "name": name,
            "prompt": payload.get("prompt") or "",
            "schedule": payload.get("schedule") or "",
            "deliver": payload.get("deliver"),
            "recipient": payload.get("recipient") or "",
        },
    )
    jobs = list_jobs()
    match = next((job for job in jobs if job.get("id") == name), None)
    if match is not None:
        return match
    return _job_from_jaeger({"name": name, "prompt": payload.get("prompt"), "cron": payload.get("schedule")})


def cancel_job(job_id: str) -> None:
    _command_with_timeout("cancel_schedule", {"name": job_id, "id": job_id})


def pause_job(job_id: str) -> None:
    _command_with_timeout("pause_schedule", {"name": job_id, "id": job_id})


def resume_job(job_id: str) -> None:
    _command_with_timeout("resume_schedule", {"name": job_id, "id": job_id})
