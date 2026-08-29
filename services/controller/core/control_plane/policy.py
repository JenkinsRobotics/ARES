"""Fail-closed evaluation for cross-agent resource access."""

from __future__ import annotations

import time

from .definitions import AgentDefinition, GrantDecision


def evaluate_grant(
    definition: AgentDefinition,
    *,
    resource: str,
    resource_id: str,
    mode: str,
    now: float | None = None,
) -> GrantDecision:
    if not definition.enabled:
        return GrantDecision(False, "agent_disabled")
    timestamp = time.time() if now is None else now
    for grant in definition.grants:
        if grant.grantee != definition.id:
            continue
        if grant.resource != resource or grant.resource_id != resource_id:
            continue
        if mode not in grant.modes:
            continue
        if grant.expires_at is not None and grant.expires_at <= timestamp:
            return GrantDecision(False, "grant_expired")
        return GrantDecision(
            True, "explicit_grant", grant.approval_required,
            grant.credential_reference,
        )
    return GrantDecision(False, "no_explicit_grant")
