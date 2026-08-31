"""Public automation API for the minimal ARES controller."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from core.automation import AutomationService

from ..errors import CoreApiError
from ..request_context import (
    RequestIdentity,
    require_identity,
    require_mutation_identity,
)

router = APIRouter(
    prefix="/api", tags=["automation"], dependencies=[Depends(require_identity)],
)
_service = AutomationService()


def service(request: Request) -> AutomationService:
    return getattr(request.app.state, "automation_service", _service)


def fail(exc: Exception) -> CoreApiError:
    return CoreApiError(409 if isinstance(exc, RuntimeError) else 400, str(exc))


@router.get("/agents")
def agents(request: Request) -> dict[str, Any]:
    controller = service(request)
    return {"paused": controller.snapshot()["paused"], "agents": controller.list_agents()}


@router.get("/integrations")
def integrations(request: Request) -> dict[str, Any]:
    return service(request).list_integrations()


@router.get("/agent-models")
def agent_models(request: Request) -> dict[str, Any]:
    return service(request).model_catalog()


@router.get("/threads")
def threads(request: Request) -> list[dict[str, Any]]:
    return service(request).list_threads()


@router.post("/threads")
def create_thread(
    payload: dict[str, Any], request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    try:
        return service(request).create_thread(payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.get("/threads/{thread_id}")
def thread(thread_id: str, request: Request) -> dict[str, Any]:
    try:
        return service(request).thread(thread_id)
    except ValueError as exc:
        raise CoreApiError(404, str(exc)) from exc


@router.post("/threads/{thread_id}/messages")
def send_thread_message(
    thread_id: str, payload: dict[str, Any], request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    try:
        return service(request).send_thread_message(thread_id, payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.get("/agents/{agent_id}/agent-card.json")
def agent_card(agent_id: str, request: Request) -> dict[str, Any]:
    try:
        agent = next(row for row in service(request).list_agents() if row["id"] == agent_id)
    except StopIteration as exc:
        raise CoreApiError(404, "agent not found") from exc
    return {
        "name": agent["name"],
        "description": agent["identity"],
        "version": "1.0.0",
        "runtimeOwner": agent["runtime"],
        "aresManaged": ["goals", "leases", "budgets", "approvals", "audit"],
        "inputModes": ["text/plain"],
        "outputModes": ["text/plain"],
        "skills": [{"id": "delegated_task", "name": "Delegated task", "tags": [agent["runtime"], "ares-governed"]}],
    }


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


@router.get("/agents/{agent_id}/configuration")
def agent_configuration(agent_id: str, request: Request) -> dict[str, Any]:
    try:
        return service(request).inspect_agent_configuration(agent_id)
    except NotImplementedError as exc:
        raise CoreApiError(409, str(exc)) from exc
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.put("/agents/{agent_id}/configuration")
def request_agent_configuration(
    agent_id: str,
    payload: dict[str, Any],
    request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    try:
        return service(request).request_agent_configuration(agent_id, payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.get("/goals")
def goals(request: Request) -> list[dict[str, Any]]:
    return service(request).snapshot()["goals"]


@router.post("/goals")
def create_goal(payload: dict[str, Any], request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    try:
        return service(request).create_goal(payload)
    except (TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.post("/goals/{goal_id}/close")
def close_goal(
    goal_id: str, payload: dict[str, Any], request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    try:
        return service(request).close_goal(
            goal_id,
            status=str(payload.get("status") or "blocked"),
            reason=str(payload.get("reason") or ""),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
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
    return service(request).list_approvals()


@router.get("/approvals/{approval_id}/preview")
def preview_approval(approval_id: str, request: Request) -> dict[str, Any]:
    try:
        return service(request).preview_approval(approval_id)
    except ValueError as exc:
        raise CoreApiError(404, str(exc)) from exc


@router.post("/approvals")
def resolve_approval(payload: dict[str, Any], request: Request, _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]) -> dict[str, Any]:
    try:
        return service(request).resolve_approval(payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.post("/capabilities/request")
def request_capability(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        return service(request).request_capability(
            agent_id=str(payload.get("agent_id") or "hermes"),
            capability=str(payload.get("capability") or ""),
            root=str(payload.get("root") or ""),
            reason=str(payload.get("reason") or ""),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.post("/effects/request")
def request_effect(
    payload: dict[str, Any], request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    try:
        return service(request).request_effect(payload)
    except PermissionError as exc:
        raise CoreApiError(403, str(exc)) from exc
    except (RuntimeError, TypeError, ValueError) as exc:
        raise fail(exc) from exc


@router.post("/effects/{approval_id}/consume")
def consume_effect(
    approval_id: str, payload: dict[str, Any], request: Request,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    try:
        return service(request).consume_effect(approval_id, payload)
    except PermissionError as exc:
        raise CoreApiError(403, str(exc)) from exc
    except (RuntimeError, TypeError, ValueError) as exc:
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
