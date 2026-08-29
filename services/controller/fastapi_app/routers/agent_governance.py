"""ARES-owned agent configuration and sharing-policy API."""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from core.control_plane import AgentDefinition, DefinitionStore, evaluate_grant
from ..errors import CoreApiError
from ..request_context import RequestIdentity, require_mutation_identity

router = APIRouter(prefix="/api/control-plane", tags=["agent-governance"])


@router.get("/agents")
def list_agents() -> dict[str, Any]:
    return {"default_isolation": True, "agents": [row.as_dict() for row in DefinitionStore().list()]}


@router.put("/agents/{agent_id}")
def put_agent(
    agent_id: str,
    payload: dict[str, Any],
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
) -> dict[str, Any]:
    if payload.get("id") not in (None, agent_id):
        raise CoreApiError(400, "agent id does not match route")
    try:
        definition = AgentDefinition.from_dict({**payload, "id": agent_id})
    except (TypeError, ValueError) as exc:
        raise CoreApiError(400, str(exc)) from exc
    return DefinitionStore().put(definition).as_dict()


@router.post("/agents/{agent_id}/evaluate")
def evaluate_agent_grant(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    definition = DefinitionStore().get(agent_id)
    if definition is None:
        raise CoreApiError(404, "agent definition not found")
    decision = evaluate_grant(
        definition,
        resource=str(payload.get("resource") or ""),
        resource_id=str(payload.get("resource_id") or ""),
        mode=str(payload.get("mode") or "use"),
    )
    return asdict(decision)
