"""ARES-owned model comparison, teacher escalation, and safe recipes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any
import uuid


_LOCK = threading.RLock()
MAX_RUNS = 200


class ModelIntelligenceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _directory(profile: str | None) -> Path:
    from api.profiles import get_ares_home_for_profile

    return Path(get_ares_home_for_profile(profile)) / "model-intelligence"


def _runs_path(profile: str | None) -> Path:
    return _directory(profile) / "runs.json"


def _load_runs(profile: str | None) -> list[dict[str, Any]]:
    try:
        value = json.loads(_runs_path(profile).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return value.get("runs", []) if isinstance(value, dict) else []


def _save_runs(profile: str | None, runs: list[dict[str, Any]]) -> None:
    directory = _directory(profile)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(
        prefix="runs-", suffix=".tmp", dir=directory
    )
    path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"version": 1, "runs": runs[-MAX_RUNS:]},
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o600)
        os.replace(path, _runs_path(profile))
    finally:
        path.unlink(missing_ok=True)


def inventory() -> dict[str, Any]:
    from api.backends.router import get_router

    targets = []
    for backend_id, backend in get_router().list_all().items():
        try:
            available = bool(backend.is_available())
        except Exception:
            available = False
        targets.append({"id": backend_id, "available": available})
    return {"targets": targets, "recipes": recipes()}


def _execute(target: dict[str, Any], prompt: str, run_id: str) -> dict[str, Any]:
    from api.backends.router import get_router
    from core.si.evaluator import evaluate_result

    backend_id = str(target.get("backend") or "").strip()
    backend = get_router().select(backend_id)
    if backend is None:
        return {
            "backend": backend_id,
            "model": target.get("model"),
            "error": "Selected runtime is unavailable.",
        }
    try:
        response = backend.run_turn(
            prompt,
            f"model-intelligence:{run_id}:{backend_id}",
            model=target.get("model"),
            model_provider=target.get("provider"),
        )
        text = str((response or {}).get("text") or "")
        error = str((response or {}).get("error") or "").strip() or None
    except Exception as exc:
        return {
            "backend": backend_id,
            "model": target.get("model"),
            "error": f"Runtime failed: {type(exc).__name__}",
        }
    evaluation = evaluate_result(result=text, intent="model_comparison")
    return {
        "backend": backend_id,
        "model": target.get("model"),
        "provider": target.get("provider"),
        "text": text,
        "error": error,
        "evaluation": {
            "score": evaluation.overall_score,
            "verdict": evaluation.verdict.value,
            "recommendation": evaluation.recommendation,
        },
    }


def compare(
    profile: str | None, *, prompt: str, targets: list[dict[str, Any]]
) -> dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ModelIntelligenceError("prompt is required")
    if not 2 <= len(targets) <= 4:
        raise ModelIntelligenceError("comparison requires 2 to 4 targets")
    run_id = uuid.uuid4().hex
    ordered: list[dict[str, Any] | None] = [None] * len(targets)
    with ThreadPoolExecutor(
        max_workers=len(targets), thread_name_prefix="model-compare"
    ) as pool:
        futures = {
            pool.submit(_execute, target, clean_prompt, run_id): index
            for index, target in enumerate(targets)
        }
        for future in as_completed(futures):
            ordered[futures[future]] = future.result()
    results = [item for item in ordered if item is not None]
    successful = [item for item in results if not item.get("error")]
    winner = max(
        successful,
        key=lambda item: float((item.get("evaluation") or {}).get("score") or 0),
        default=None,
    )
    record = {
        "id": run_id,
        "kind": "compare",
        "prompt_sha256": hashlib.sha256(clean_prompt.encode()).hexdigest(),
        "prompt_preview": clean_prompt[:160],
        "results": results,
        "winner": winner.get("backend") if winner else None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    with _LOCK:
        runs = _load_runs(profile)
        runs.append(record)
        _save_runs(profile, runs)
    return record


def teacher_escalation(
    profile: str | None,
    *,
    prompt: str,
    primary: dict[str, Any],
    teacher: dict[str, Any],
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    first = _execute(primary, prompt, run_id)
    verdict = str((first.get("evaluation") or {}).get("verdict") or "fail")
    escalated = bool(first.get("error") or verdict in {"fail", "escalate", "unknown"})
    taught = _execute(teacher, prompt, run_id) if escalated else None
    record = {
        "id": run_id,
        "kind": "teacher_escalation",
        "primary": first,
        "teacher": taught,
        "escalated": escalated,
        "created_at": datetime.now(UTC).isoformat(),
    }
    with _LOCK:
        runs = _load_runs(profile)
        runs.append(record)
        _save_runs(profile, runs)
    return record


def history(profile: str | None) -> dict[str, Any]:
    return {"runs": list(reversed(_load_runs(profile)))}


def recipes() -> list[dict[str, Any]]:
    return [
        {
            "id": "compare",
            "name": "Compare runtimes",
            "kind": "model_compare",
            "mutable": False,
        },
        {
            "id": "teacher",
            "name": "Escalate weak answers",
            "kind": "teacher_escalation",
            "mutable": False,
        },
        {
            "id": "local-model-hatchery",
            "name": "Local model hatchery",
            "kind": "model_serving",
            "mutable": False,
            "owner": "ares",
            "routes": [
                "/api/hatchery/scan",
                "/api/hatchery/mold",
                "/api/hatchery/hatch",
            ],
        },
    ]
