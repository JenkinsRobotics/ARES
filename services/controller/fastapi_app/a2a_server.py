"""A2A protocol surface for the ARES System router.

ARES is not the reasoning runtime.  This executor turns an A2A task into one
durable ARES goal/run and delegates it to an independently owned agent.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any

from fastapi import FastAPI

from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState

from core.automation import AutomationService


TERMINAL_RUN_STATES = {
    "complete",
    "blocked",
    "approval_required",
    "failed",
    "paused",
    "cancelled",
}


def select_agent(message: str, default_agent: str = "hermes") -> tuple[str, str]:
    """Resolve an explicit ``@agent`` prefix, otherwise use policy default."""

    stripped = message.strip()
    lowered = stripped.lower()
    for agent_id in ("hermes", "jaeger"):
        for prefix in (f"@{agent_id} ", f"[{agent_id}] ", f"{agent_id}: "):
            if lowered.startswith(prefix):
                return agent_id, stripped[len(prefix) :].strip()
    return default_agent, stripped


class SystemAgentExecutor(AgentExecutor):
    """Translate A2A tasks into ARES-owned goals and leased agent runs."""

    def __init__(self, service: AutomationService) -> None:
        self.service = service
        self._task_runs: dict[str, str] = {}
        self._lock = threading.RLock()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)

        message = get_message_text(context.message) or ""
        default_agent = os.environ.get("ARES_SYSTEM_DEFAULT_AGENT", "hermes").strip() or "hermes"
        agent_id, objective = select_agent(message, default_agent)
        if not objective:
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message("A text request is required."),
            )
            return

        try:
            goal = self.service.create_goal({"agent_id": agent_id, "objective": objective})
            run = self.service.wake(
                agent_id,
                goal_id=goal["id"],
                trigger="a2a",
                idempotency_key=f"a2a:{task.id}",
            )
        except Exception as exc:
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"ARES could not delegate the task: {exc}"),
            )
            return

        with self._lock:
            self._task_runs[task.id] = run["id"]
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message(f"Delegated to {agent_id}; ARES run {run['id']} is active."),
        )

        configured_timeout = max(10, int(os.environ.get("ARES_A2A_TASK_TIMEOUT", "900")))
        deadline = time.monotonic() + configured_timeout
        latest: dict[str, Any] = run
        while time.monotonic() < deadline:
            rows = self.service.snapshot()["runs"]
            latest = next((row for row in rows if row["id"] == run["id"]), latest)
            if latest.get("status") in TERMINAL_RUN_STATES:
                break
            await asyncio.sleep(0.25)
        else:
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"ARES run {run['id']} exceeded the A2A wait limit."),
            )
            return

        result_text = str(latest.get("result") or latest.get("error") or "No result text was returned.")
        await updater.add_artifact(
            parts=[new_text_part(text=result_text, media_type="text/plain")],
            name=f"ARES run {run['id']}",
        )
        status = str(latest.get("status") or "failed")
        if status == "complete":
            state = TaskState.TASK_STATE_COMPLETED
        elif status == "cancelled":
            state = TaskState.TASK_STATE_CANCELED
        elif status == "approval_required":
            state = TaskState.TASK_STATE_INPUT_REQUIRED
        else:
            state = TaskState.TASK_STATE_FAILED
        await updater.update_status(
            state=state,
            message=new_text_message(f"ARES run {run['id']} finished with status {status}."),
        )

    async def cancel(self, context: RequestContext, _event_queue: EventQueue) -> None:
        task_id = str(getattr(context.current_task, "id", "") or "")
        with self._lock:
            run_id = self._task_runs.get(task_id)
        if not run_id:
            raise ValueError("No ARES run is associated with this A2A task.")
        self.service.cancel(run_id)


def build_agent_card() -> AgentCard:
    public_url = os.environ.get("ARES_A2A_PUBLIC_URL", "http://127.0.0.1:8788/a2a")
    return AgentCard(
        name="ARES System",
        description=(
            "A deterministic coordination surface that delegates work to independent "
            "Hermes and JaegerAI runtimes and records goals, runs, approvals, and evidence."
        ),
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=public_url, protocol_version="1.0")
        ],
        skills=[
            AgentSkill(
                id="delegate_task",
                name="Delegate task",
                description="Run a durable task through Hermes or JaegerAI. Prefix with @jaeger or @hermes to select explicitly.",
                input_modes=["text/plain"],
                output_modes=["text/plain"],
                tags=["coordination", "delegation", "audit"],
                examples=["Research this topic", "@jaeger inspect the local project"],
            )
        ],
    )


def install_a2a_routes(application: FastAPI, service: AutomationService) -> None:
    """Install official SDK routes before the browser catch-all."""

    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=SystemAgentExecutor(service),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    application.router.routes.extend(create_agent_card_routes(card))
    application.router.routes.extend(create_jsonrpc_routes(handler, "/a2a", enable_v0_3_compat=True))


__all__ = ["SystemAgentExecutor", "build_agent_card", "install_a2a_routes", "select_agent"]
