"""Public automation API for the minimal ARES controller."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from core.automation import AutomationService
from ..errors import CoreApiError
from ..request_context import RequestIdentity, require_mutation_identity

router = APIRouter(prefix="/api", tags=["automation"])
_service = AutomationService()


def service(request: Request) -> AutomationService:
    return getattr(request.app.state, "automation_service", _service)


def fail(exc: Exception) -> CoreApiError:
    return CoreApiError(409 if isinstance(exc, RuntimeError) else 400, str(exc))


@router.get("/agents")
def agents(request: Request) -> dict[str, Any]:
    controller = service(request)
    return {"paused": controller.snapshot()["paused"], "agents": controller.list_agents()}


@router.put("/agents")
def put_agent(payload: dict[str, Any], request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    try:
        return service(request).put_agent(payload)
    except (TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.get("/agents/{agent_id}/probe")
def probe_agent(agent_id: str, request: Request) -> dict[str, Any]:
    try:
        return service(request).probe_agent(agent_id)
    except (TypeError, ValueError) as exc:
        raise CoreApiError(404, str(exc)) from exc


@router.get("/goals")
def goals(request: Request) -> list[dict[str, Any]]:
    return service(request).snapshot()["goals"]


@router.post("/goals")
def create_goal(payload: dict[str, Any], request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    try:
        return service(request).create_goal(payload)
    except (TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.post("/agents/{agent_id}/wake")
def wake(agent_id: str, payload: dict[str, Any], request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    try:
        return service(request).wake(agent_id, goal_id=str(payload.get("goal_id") or ""), trigger=str(payload.get("trigger") or "manual"), idempotency_key=str(payload.get("idempotency_key") or ""))
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.get("/runs")
def runs(request: Request) -> list[dict[str, Any]]:
    return list(reversed(service(request).snapshot()["runs"]))


@router.get("/runs/{run_id}/events")
def events(run_id: str, request: Request) -> list[dict[str, Any]]:
    return [row for row in service(request).snapshot()["events"] if row["run_id"] == run_id]


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    try:
        return service(request).cancel(run_id)
    except ValueError as exc:
        raise CoreApiError(404, str(exc)) from exc


@router.get("/approvals")
def approvals(request: Request) -> list[dict[str, Any]]:
    return list(reversed(service(request).snapshot()["approvals"]))


@router.post("/approvals")
def resolve_approval(payload: dict[str, Any], request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    try:
        return service(request).resolve_approval(payload)
    except ValueError as exc:
        raise fail(exc) from exc


@router.post("/control/pause")
def pause(request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    return service(request).pause(True)


@router.post("/control/resume")
def resume(request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    return service(request).pause(False)


@router.post("/control/tick")
def tick(request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    return {"created": service(request).tick()}
