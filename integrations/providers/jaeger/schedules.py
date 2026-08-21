"""ARES adapter: WebUI cron panel → JaegerAI schedule store."""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


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
    try:
        from api.providers.jaeger.streaming import query_local_companion

        payload = query_local_companion("cron", {})
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
    from api.providers.jaeger.streaming import query_local_companion

    payload = query_local_companion("list_schedules", {})
    rows = payload.get("schedules") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise JaegerScheduleError("Jaeger returned an invalid schedule list")
    return [_job_from_jaeger(row) for row in rows if isinstance(row, dict)]


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    from api.providers.jaeger.streaming import command_local_companion

    name = str(payload.get("name") or "").strip() or f"job_{uuid.uuid4().hex[:10]}"
    command_local_companion(
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
    from api.providers.jaeger.streaming import command_local_companion

    command_local_companion("cancel_schedule", {"name": job_id, "id": job_id})


def pause_job(job_id: str) -> None:
    from api.providers.jaeger.streaming import command_local_companion

    command_local_companion("pause_schedule", {"name": job_id, "id": job_id})


def resume_job(job_id: str) -> None:
    from api.providers.jaeger.streaming import command_local_companion

    command_local_companion("resume_schedule", {"name": job_id, "id": job_id})
