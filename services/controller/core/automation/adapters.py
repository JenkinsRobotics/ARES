"""Common runtime adapter contract and independent Hermes/Jaeger clients."""

from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import Agent

EventSink = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class AdapterResult:
    text: str
    session_id: str = ""
    error: str = ""


class AgentAdapter(ABC):
    @abstractmethod
    def probe(self, agent: Agent) -> dict[str, Any]: ...

    @abstractmethod
    def start_run(self, agent: Agent, prompt: str, session_id: str, emit: EventSink, cancel: threading.Event) -> AdapterResult: ...

    def resume_run(self, agent: Agent, prompt: str, session_id: str, emit: EventSink, cancel: threading.Event) -> AdapterResult:
        return self.start_run(agent, prompt, session_id, emit, cancel)

    @abstractmethod
    def cancel_run(self, session_id: str) -> None: ...

    def stream_events(self, _run_id: str) -> list[dict[str, Any]]:
        return []

    def collect_result(self, result: AdapterResult) -> AdapterResult:
        return result

    def inspect_configuration(self, _agent: Agent) -> dict[str, Any]:
        raise NotImplementedError("runtime does not expose configuration management")

    def apply_configuration(self, _agent: Agent, _desired: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("runtime does not expose configuration management")


class HermesAdapter(AgentAdapter):
    _session = re.compile(r"(?im)^session_id:\s*([A-Za-z0-9_.:-]+)\s*$")

    def __init__(self, command: str | None = None, webui_url: str | None = None) -> None:
        configured = command or os.environ.get("ARES_HERMES_COMMAND")
        self.command = configured or shutil.which("hermes") or str(Path.home() / "bin" / "hermes")
        self.webui_url = (webui_url or os.environ.get("ARES_HERMES_WEBUI_URL") or "http://127.0.0.1:8787").rstrip("/")
        self._active: subprocess.Popen[str] | None = None

    def probe(self, _agent: Agent) -> dict[str, Any]:
        candidate = Path(self.command).expanduser()
        resolved = candidate if candidate.is_file() else None
        if resolved is None and os.sep not in self.command:
            resolved_path = shutil.which(self.command)
            resolved = Path(resolved_path) if resolved_path else None
        result = {
            "available": resolved is not None,
            "command": str(resolved or self.command),
            "owner": "hermes",
            "configuration": {"available": False, "endpoint": self.webui_url},
        }
        try:
            current = self.inspect_configuration(_agent)
            result["configuration"] = {
                "available": True,
                "endpoint": self.webui_url,
                "workspace_count": len(current["workspaces"]),
            }
        except Exception as exc:
            result["configuration"]["error"] = str(exc)
        return result

    def _webui_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.webui_url}{path}",
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                encoded = response.read(1_048_577)
                if len(encoded) > 1_048_576:
                    raise RuntimeError(f"Hermes WebUI response is too large for {method} {path}")
                raw = encoded.decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Hermes WebUI rejected {method} {path}: HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Hermes WebUI is unavailable at {self.webui_url}: {exc.reason}") from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Hermes WebUI returned non-JSON for {method} {path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Hermes WebUI returned an invalid object for {method} {path}")
        if value.get("error"):
            raise RuntimeError(f"Hermes WebUI rejected {method} {path}: {value['error']}")
        return value

    def inspect_configuration(self, _agent: Agent) -> dict[str, Any]:
        memory = self._webui_request("GET", "/api/memory")
        workspace_payload = self._webui_request("GET", "/api/workspaces")
        workspaces = []
        for row in workspace_payload.get("workspaces") or []:
            if isinstance(row, dict) and row.get("path"):
                workspaces.append({"path": str(row["path"]), "name": str(row.get("name") or "")})
        return {
            "owner": "hermes",
            "endpoint": self.webui_url,
            "soul": str(memory.get("soul") or ""),
            "soul_path": str(memory.get("soul_path") or ""),
            "workspaces": workspaces,
            "last_workspace": str(workspace_payload.get("last") or ""),
        }

    def apply_configuration(self, agent: Agent, desired: dict[str, Any]) -> dict[str, Any]:
        before = self.inspect_configuration(agent)
        existing_paths = {row["path"] for row in before["workspaces"]}
        added: list[str] = []
        try:
            for workspace in desired.get("workspaces") or []:
                if workspace in existing_paths:
                    continue
                self._webui_request("POST", "/api/workspaces/add", {"path": workspace})
                added.append(workspace)
            soul = desired.get("soul")
            if soul is not None and soul != before["soul"]:
                self._webui_request("POST", "/api/memory/write", {"section": "soul", "content": soul})
        except Exception:
            # Workspace registration is reversible; restore only entries added
            # by this request. The prior SOUL is written last, so a workspace
            # failure cannot leave an identity half-applied.
            for workspace in reversed(added):
                try:
                    self._webui_request("POST", "/api/workspaces/remove", {"path": workspace})
                except Exception:
                    pass
            raise
        after = self.inspect_configuration(agent)
        after_paths = {row["path"] for row in after["workspaces"]}
        missing = [path for path in desired.get("workspaces") or [] if path not in after_paths]
        if missing or (soul is not None and after["soul"] != soul):
            raise RuntimeError("Hermes configuration verification failed")
        return after

    def start_run(self, agent: Agent, prompt: str, session_id: str, emit: EventSink, cancel: threading.Event) -> AdapterResult:
        args = [self.command, "--in", agent.workspace, "chat", "-q", prompt, "-Q", "--source", "tool", "--max-turns", str(agent.max_turns)]
        if agent.model:
            args.extend(["-m", agent.model])
        if agent.toolsets:
            args.extend(["-t", ",".join(agent.toolsets)])
        if session_id:
            args.extend(["--resume", session_id])
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=agent.workspace if Path(agent.workspace).is_dir() else None)
        self._active = proc
        try:
            stdout, stderr = proc.communicate(timeout=agent.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=10)
            return AdapterResult("", session_id, "Hermes run timed out")
        finally:
            self._active = None
        if cancel.is_set():
            return AdapterResult("", session_id, "cancelled")
        match = self._session.search(stdout + "\n" + stderr)
        next_session = match.group(1) if match else session_id
        text = self._session.sub("", stdout).strip()
        if text:
            emit("text_delta", {"text": text})
        return AdapterResult(text, next_session, "" if proc.returncode == 0 else (stderr.strip() or f"Hermes exited {proc.returncode}"))

    def cancel_run(self, _session_id: str) -> None:
        if self._active is not None:
            self._active.terminate()


class JaegerAdapter(AgentAdapter):
    def __init__(self) -> None:
        self._client = None

    @staticmethod
    def _client_type():
        from api.providers.jaeger.bridge_client import JaegerClient
        return JaegerClient

    def probe(self, agent: Agent) -> dict[str, Any]:
        try:
            with self._client_type()(instance=agent.runtime_instance) as client:
                return {"available": True, "owner": "jaeger", "ready": client.ready, "contract": client.integration_contract()}
        except Exception as exc:
            return {"available": False, "owner": "jaeger", "error": str(exc)}

    def start_run(self, agent: Agent, prompt: str, session_id: str, emit: EventSink, cancel: threading.Event) -> AdapterResult:
        def on_event(frame: dict[str, Any]) -> None:
            kind = str(frame.get("type") or "checkpoint")
            mapped = {"delta": "text_delta", "reasoning": "reasoning_delta", "tool": "tool_result"}.get(kind, "checkpoint")
            emit(mapped, {"frame": frame})

        def on_request(frame: dict[str, Any]) -> str:
            emit("approval_required", {"request": frame})
            return "deny"

        try:
            with self._client_type()(instance=agent.runtime_instance) as client:
                self._client = client
                if cancel.is_set():
                    return AdapterResult("", session_id, "cancelled")
                durable_session = session_id or f"ares-{agent.id}"
                reply = client.turn(prompt, session=durable_session, workspace=agent.workspace, on_event=on_event, on_request=on_request)
                return AdapterResult(str(reply.get("text") or ""), durable_session, str(reply.get("error") or ""))
        except Exception as exc:
            return AdapterResult("", session_id, str(exc))
        finally:
            self._client = None

    def cancel_run(self, session_id: str) -> None:
        if self._client is not None:
            self._client.cancel(session_id)
