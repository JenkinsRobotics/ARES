"""Common runtime adapter contract and independent Hermes/Jaeger clients."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
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

    def continue_runtime_run(
        self,
        agent: Agent,
        owner_run_id: str,
        owner_approval_id: str,
        owner_cursor: str,
        decision: str,
        session_id: str,
        emit: EventSink,
        cancel: threading.Event,
    ) -> AdapterResult:
        """Resume an owner-held run after an ARES approval decision.

        Runtimes that can pause for an external decision must implement this
        method. Starting the prompt again is deliberately not the default: it
        could repeat the consequential action that was awaiting approval.
        """

        raise RuntimeError("runtime does not support approval continuation")

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
        self.webui_url = (webui_url or os.environ.get("ARES_HERMES_WEBUI_URL") or os.environ.get("ARES_PUBLIC_URL") or "http://127.0.0.1:8787").rstrip("/")
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
        # Use Hermes' stdin transport so substantial context is not constrained
        # by macOS' per-process command-line argument limit. ``--query-file -``
        # also preserves arbitrary quotes, backticks, and shell-like text.
        args = [self.command, "--in", agent.workspace, "chat", "--query-file", "-", "-Q", "--source", "tool", "--max-turns", str(agent.max_turns)]
        if agent.model:
            args.extend(["-m", agent.model])
        if agent.toolsets:
            args.extend(["-t", ",".join(agent.toolsets)])
        if session_id:
            args.extend(["--resume", session_id])
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=agent.workspace if Path(agent.workspace).is_dir() else None,
            start_new_session=True,
        )
        self._active = proc
        try:
            stdout, stderr = proc.communicate(input=prompt, timeout=agent.timeout_seconds)
        except subprocess.TimeoutExpired:
            self._terminate_process_tree(proc)
            stdout, stderr = proc.communicate(timeout=10)
            return AdapterResult("", session_id, "Hermes run timed out")
        finally:
            self._active = None
        if cancel.is_set():
            return AdapterResult("", session_id, "cancelled")
        combined = stdout + "\n" + stderr
        if session_id and proc.returncode != 0 and re.search(r"(?i)session not found", combined):
            emit("checkpoint", {
                "reason": "stale_agent_session",
                "owner": "hermes",
                "discarded_session_id": session_id,
                "action": "start_fresh_session",
            })
            return self.start_run(agent, prompt, "", emit, cancel)
        match = self._session.search(combined)
        next_session = match.group(1) if match else session_id
        text = self._session.sub("", stdout).strip()
        if text:
            emit("text_delta", {"text": text})
        return AdapterResult(text, next_session, "" if proc.returncode == 0 else (stderr.strip() or f"Hermes exited {proc.returncode}"))

    def cancel_run(self, _session_id: str) -> None:
        if self._active is not None:
            self._terminate_process_tree(self._active)

    @staticmethod
    def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
        """Terminate a CLI wrapper and descendants such as `container exec`."""
        if getattr(proc, "poll", lambda: None)() is not None:
            return
        try:
            process_group = os.getpgid(proc.pid)
            os.killpg(process_group, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # Apple's `container exec` can ignore TERM while its remote
                # process is in a model/tool turn. Leaving it alive retains
                # Ollama weights and the ARES local-model lease indefinitely.
                os.killpg(process_group, signal.SIGKILL)
                proc.wait(timeout=3)
        except (AttributeError, ProcessLookupError, PermissionError):
            proc.terminate()


class JaegerAdapter(AgentAdapter):
    def __init__(self, runner_url: str | None = None) -> None:
        self.runner_url = (
            runner_url or os.environ.get("ARES_JAEGER_RUNNER_URL") or "http://127.0.0.1:8791"
        ).rstrip("/")
        self._active_run_id = ""

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.runner_url}{path}", data=body, method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Jaeger rejected {method} {path}: HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Jaeger runner is unavailable at {self.runner_url}: {exc.reason}") from exc
        if len(raw) > 2_000_000:
            raise RuntimeError("Jaeger response exceeded the adapter safety limit")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"Jaeger returned an invalid object for {method} {path}")
        return value

    def probe(self, agent: Agent) -> dict[str, Any]:
        try:
            ready = self._request("GET", "/health")
            return {
                "available": bool(ready.get("ok")), "owner": "jaeger",
                "endpoint": self.runner_url, "ready": ready.get("ready") or ready,
            }
        except Exception as exc:
            return {"available": False, "owner": "jaeger", "error": str(exc)}

    def _collect_run(
        self,
        agent: Agent,
        run_id: str,
        durable_session: str,
        emit: EventSink,
        cancel: threading.Event,
        *,
        cursor: str = "",
    ) -> AdapterResult:
        text_parts: list[str] = []
        error = ""
        deadline = time.monotonic() + agent.timeout_seconds
        encoded_run = urllib.parse.quote(run_id, safe="")
        while time.monotonic() < deadline:
            if cancel.is_set():
                self._request("POST", f"/v1/runs/{encoded_run}/cancel", {})
                return AdapterResult("".join(text_parts), durable_session, "cancelled")
            suffix = f"?cursor={urllib.parse.quote(cursor, safe='')}" if cursor else ""
            batch = self._request("GET", f"/v1/runs/{encoded_run}/events{suffix}")
            pending_approval: dict[str, Any] | None = None
            for event in batch.get("events") or []:
                if not isinstance(event, dict):
                    continue
                kind = str(event.get("event") or "")
                data = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                if kind == "token":
                    delta = str(data.get("text") or "")
                    text_parts.append(delta)
                    if delta:
                        emit("text_delta", {"text": delta})
                elif kind == "reasoning":
                    # Hidden model reasoning is neither a stable protocol nor
                    # safe audit evidence. Record only that the runtime made
                    # progress; decisions, tools, and results remain visible.
                    emit("checkpoint", {"reason": "runtime_reasoning_activity"})
                elif kind in {"tool", "tool_complete"}:
                    emit("tool_result", dict(data))
                elif kind == "approval":
                    pending_approval = dict(data)
                elif kind == "apperror":
                    error = str(data.get("message") or "Jaeger run failed")
            cursor = str(batch.get("cursor") or cursor)
            if pending_approval is not None:
                owner_approval_id = str(pending_approval.get("approval_id") or "")
                if not owner_approval_id:
                    return AdapterResult(
                        "".join(text_parts).strip(), durable_session,
                        "Jaeger requested approval without an approval_id",
                    )
                emit("approval_required", {
                    **pending_approval,
                    "owner": "jaeger",
                    "owner_run_id": run_id,
                    "owner_approval_id": owner_approval_id,
                    "owner_cursor": cursor,
                })
                # Jaeger retains the paused run. ARES must relay the eventual
                # decision and continue this exact run, never replay the prompt.
                return AdapterResult("".join(text_parts).strip(), durable_session)
            status = self._request("GET", f"/v1/runs/{encoded_run}")
            if status.get("terminal_state") or status.get("status") in {"completed", "failed", "cancelled"}:
                if status.get("status") != "completed" and not error:
                    error = str(status.get("error") or f"Jaeger run {status.get('status')}")
                return AdapterResult("".join(text_parts).strip(), durable_session, error)
            time.sleep(0.25)
        self._request("POST", f"/v1/runs/{encoded_run}/cancel", {})
        return AdapterResult("".join(text_parts).strip(), durable_session, "Jaeger run timed out")

    def start_run(self, agent: Agent, prompt: str, session_id: str, emit: EventSink, cancel: threading.Event) -> AdapterResult:
        # A new ARES goal gets a new Jaeger-owned session. Continuations pass
        # the owner-issued id back explicitly through ``session_id``.
        durable_session = session_id or f"ares-{agent.id}-{uuid.uuid4().hex}"
        payload: dict[str, Any] = {"message": prompt, "session_id": durable_session}
        if agent.model:
            payload["model"] = agent.model
        try:
            started = self._request("POST", "/v1/runs", payload)
            run_id = str(started.get("run_id") or "")
            if not run_id:
                raise RuntimeError("Jaeger did not return a run_id")
            self._active_run_id = run_id
            return self._collect_run(agent, run_id, durable_session, emit, cancel)
        except Exception as exc:
            return AdapterResult("", session_id, str(exc))
        finally:
            self._active_run_id = ""

    def continue_runtime_run(
        self,
        agent: Agent,
        owner_run_id: str,
        owner_approval_id: str,
        owner_cursor: str,
        decision: str,
        session_id: str,
        emit: EventSink,
        cancel: threading.Event,
    ) -> AdapterResult:
        if not owner_run_id or not owner_approval_id:
            return AdapterResult("", session_id, "Jaeger approval continuation is missing owner identifiers")
        encoded_run = urllib.parse.quote(owner_run_id, safe="")
        choice = "once" if decision == "approved" else "deny"
        try:
            self._active_run_id = owner_run_id
            self._request("POST", f"/v1/runs/{encoded_run}/approval", {
                "approval_id": owner_approval_id,
                "choice": choice,
            })
            return self._collect_run(
                agent, owner_run_id, session_id, emit, cancel, cursor=owner_cursor,
            )
        except Exception as exc:
            return AdapterResult("", session_id, str(exc))
        finally:
            self._active_run_id = ""

    def cancel_run(self, _session_id: str) -> None:
        if self._active_run_id:
            encoded = urllib.parse.quote(self._active_run_id, safe="")
            self._request("POST", f"/v1/runs/{encoded}/cancel", {})


class OpenClawAdapter(AgentAdapter):
    """Drive the ARES-managed OpenClaw container through its own CLI.

    OpenClaw runs as a container here, so unlike Hermes there is no host
    command to spawn: every turn goes through ``container exec`` into the
    running gateway. That is deliberate rather than incidental -- the container
    boundary is the isolation story, and reaching in through the published HTTP
    port instead would mean handling the gateway token in ARES' process.

    The host binary from Homebrew is intentionally left alone. It is the user's
    own interactive install with its own state directory, and ARES neither
    manages nor routes to it.
    """

    _session = re.compile(r"(?im)^\s*session(?:[ _-]?id)?:\s*([A-Za-z0-9_.:-]+)\s*$")

    def __init__(
        self,
        container: str | None = None,
        container_cli: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        self.container = container or os.environ.get("ARES_OPENCLAW_CONTAINER") or "ares-openclaw"
        self.container_cli = (
            container_cli
            or os.environ.get("ARES_CONTAINER_CLI")
            or shutil.which("container")
            or "/opt/homebrew/bin/container"
        )
        # OpenClaw's default agent id; a run may override it per Agent record.
        self.agent_name = agent_name or os.environ.get("ARES_OPENCLAW_AGENT") or "main"
        self._active: subprocess.Popen[str] | None = None

    def _exec(self, inner: str, *, stdin: bool = False) -> list[str]:
        # `container exec` closes stdin unless --interactive is passed, which
        # turns --message-file /dev/stdin into "Message file is empty".
        flags = ["--interactive"] if stdin else []
        # The gateway credential is deliberately not a persisted container
        # environment value (``container inspect`` would reveal it). Load the
        # private runtime file only inside the exec process.
        command = (
            'export OPENCLAW_GATEWAY_TOKEN="$(cat '
            '/home/node/.openclaw/gateway.token)"; ' + inner
        )
        return [self.container_cli, "exec", *flags, self.container, "sh", "-lc", command]

    def _is_running(self) -> bool:
        try:
            completed = subprocess.run(
                [self.container_cli, "list", "--quiet"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        names = {line.strip() for line in completed.stdout.splitlines()}
        return self.container in names

    def probe(self, _agent: Agent) -> dict[str, Any]:
        running = self._is_running()
        result: dict[str, Any] = {
            "available": running,
            "command": f"{self.container_cli} exec {self.container}",
            "owner": "openclaw",
            "container": self.container,
            "running": running,
        }
        if not running:
            result["error"] = (
                f"container {self.container!r} is not running; "
                "run scripts/install-openclaw-container.sh"
            )
            return result
        try:
            completed = subprocess.run(
                self._exec('node dist/index.js gateway health --token "$OPENCLAW_GATEWAY_TOKEN"'),
                capture_output=True, text=True, timeout=30,
            )
            healthy = completed.returncode == 0 and "OK" in completed.stdout
            result["gateway"] = {
                "healthy": healthy,
                "detail": (completed.stdout or completed.stderr).strip()[:500],
            }
            result["available"] = healthy
        except (OSError, subprocess.SubprocessError) as exc:
            result["available"] = False
            result["gateway"] = {"healthy": False, "detail": str(exc)}
        return result

    def start_run(
        self,
        agent: Agent,
        prompt: str,
        session_id: str,
        emit: EventSink,
        cancel: threading.Event,
    ) -> AdapterResult:
        # The message is passed on stdin via --message-file so that prompt text
        # never has to survive a shell quoting round-trip through `sh -lc`.
        # ``runtime_instance`` names the agent *inside* OpenClaw. It defaults to
        # the ARES agent id, so an operator must either create a matching
        # OpenClaw agent or point this at an existing one such as "main".
        target_agent = agent.runtime_instance or self.agent_name
        # --json is not a convenience here: the human-readable output carries
        # neither a session id nor a reliable reply boundary, so scraping it
        # silently loses run continuity between turns.
        # The message goes in on stdin via --message-file so prompt text never
        # has to survive a shell quoting round-trip through `sh -lc`.
        parts = [
            "node dist/index.js agent",
            f"--agent {shlex.quote(target_agent)}",
            "--message-file /dev/stdin",
            "--json",
        ]
        if agent.model:
            model_ref = agent.model
            # OpenClaw names custom Ollama lanes as providers. ARES stores the
            # provider and model separately so the common model catalog stays
            # consistent across runtimes; qualify only at this adapter edge.
            if "/" not in model_ref:
                if agent.model_provider == "ollama-local":
                    model_ref = f"ollama-local/{model_ref}"
                elif agent.model_provider == "ollama-cloud":
                    model_ref = f"ollama-cloud-via-host/{model_ref}"
            parts.append(f"--model {shlex.quote(model_ref)}")
        if session_id:
            parts.append(f"--session-id {shlex.quote(session_id)}")
        proc = subprocess.Popen(
            self._exec(" ".join(parts), stdin=True),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self._active = proc
        try:
            stdout, stderr = proc.communicate(input=prompt, timeout=agent.timeout_seconds)
        except subprocess.TimeoutExpired:
            self._terminate_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.SubprocessError:
                stdout, stderr = "", ""
            return AdapterResult("", session_id, "OpenClaw run timed out")
        finally:
            self._active = None
        if cancel.is_set():
            return AdapterResult("", session_id, "cancelled")

        payload = self._parse_json(stdout)
        if payload is None:
            error = stderr.strip() or stdout.strip() or f"OpenClaw exited {proc.returncode}"
            return AdapterResult("", session_id, error)

        result = payload.get("result") or {}
        meta = (result.get("meta") or {}).get("agentMeta") or {}
        next_session = str(meta.get("sessionId") or "") or session_id
        text = "\n".join(
            str(row.get("text") or "").strip()
            for row in (result.get("payloads") or [])
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ).strip()

        error = ""
        if str(payload.get("status") or "").lower() not in {"ok", "success", ""}:
            error = str(payload.get("summary") or "").strip() or "OpenClaw run failed"
        elif proc.returncode != 0:
            error = stderr.strip() or f"OpenClaw exited {proc.returncode}"

        if text:
            emit("text_delta", {"text": text})
        return AdapterResult(text, next_session, error)

    @staticmethod
    def _parse_json(stdout: str) -> dict[str, Any] | None:
        """Pull the JSON document out of stdout.

        The CLI may print banner or log lines before the document, so locate
        the first balanced object rather than assuming stdout is pure JSON.
        """
        start = stdout.find("{")
        while start != -1:
            try:
                value = json.loads(stdout[start:])
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                try:
                    value, _ = decoder.raw_decode(stdout[start:])
                except ValueError:
                    start = stdout.find("{", start + 1)
                    continue
            return value if isinstance(value, dict) else None
        return None

    def cancel_run(self, _session_id: str) -> None:
        if self._active is not None:
            self._terminate_process_tree(self._active)

    @staticmethod
    def _terminate_process_tree(proc: "subprocess.Popen[str]") -> None:
        if getattr(proc, "poll", lambda: None)() is not None:
            return
        try:
            process_group = os.getpgid(proc.pid)
            os.killpg(process_group, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process_group, signal.SIGKILL)
                proc.wait(timeout=3)
        except (AttributeError, ProcessLookupError, PermissionError):
            proc.terminate()


def _host_env() -> dict[str, str]:
    env = os.environ.copy()
    dirs = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        str(Path.home() / ".grok" / "bin"),
        str(Path.home() / "bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    existing = env.get("PATH", "").split(":")
    for d in reversed(dirs):
        if d not in existing:
            existing.insert(0, d)
    env["PATH"] = ":".join(existing)
    return env


class CliToolAdapter(AgentAdapter):
    """Generic adapter for independently owned host CLI tools."""

    def __init__(
        self,
        command: str,
        cli_name: str,
        arg_builder: Callable[[str, Agent], list[str]],
    ) -> None:
        self.command = command
        self.cli_name = cli_name
        self.arg_builder = arg_builder
        self._active: subprocess.Popen[str] | None = None

    def probe(self, _agent: Agent) -> dict[str, Any]:
        env = _host_env()
        resolved = shutil.which(self.command, path=env["PATH"]) or (self.command if os.path.exists(self.command) else None)
        if not resolved:
            return {
                "available": False,
                "command": self.command,
                "owner": self.cli_name,
                "error": f"{self.cli_name} CLI not found on host PATH",
            }
        try:
            res = subprocess.run([resolved, "--version"], env=env, capture_output=True, text=True, timeout=5)
            version = (res.stdout.strip() or res.stderr.strip()).splitlines()[0]
            return {
                "available": True,
                "command": resolved,
                "owner": self.cli_name,
                "version": version,
            }
        except Exception as exc:
            return {"available": False, "command": resolved, "owner": self.cli_name, "error": str(exc)}

    def start_run(
        self,
        agent: Agent,
        prompt: str,
        session_id: str,
        emit: EventSink,
        cancel: threading.Event,
    ) -> AdapterResult:
        env = _host_env()
        resolved = shutil.which(self.command, path=env["PATH"]) or (self.command if os.path.exists(self.command) else None)
        if not resolved:
            return AdapterResult("", session_id, f"{self.cli_name} CLI not found on host PATH")

        args = [resolved] + self.arg_builder(prompt, agent)
        cwd = agent.workspace or "/Users/matthewjenkins/workspace"
        if not os.path.isdir(cwd):
            cwd = str(Path.home())

        try:
            proc = subprocess.Popen(
                args,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            self._active = proc
        except Exception as exc:
            return AdapterResult("", session_id, f"Failed to spawn {self.cli_name}: {exc}")

        output_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _stream_stdout():
            try:
                for line in iter(proc.stdout.readline, ""):
                    if cancel.is_set():
                        break
                    output_chunks.append(line)
                    emit("text_delta", {"text": line})
            except Exception:
                pass

        def _stream_stderr():
            try:
                for line in iter(proc.stderr.readline, ""):
                    if cancel.is_set():
                        break
                    stderr_chunks.append(line)
            except Exception:
                pass

        t_out = threading.Thread(target=_stream_stdout, daemon=True)
        t_err = threading.Thread(target=_stream_stderr, daemon=True)
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=agent.timeout_seconds)
            t_out.join(timeout=2)
            t_err.join(timeout=2)
        except subprocess.TimeoutExpired:
            self._terminate_process_tree(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.SubprocessError:
                pass
            return AdapterResult("".join(output_chunks), session_id, f"{self.cli_name} run timed out")
        finally:
            self._active = None

        if cancel.is_set():
            return AdapterResult("".join(output_chunks), session_id, "cancelled")

        full_text = "".join(output_chunks).strip()
        stderr_text = "".join(stderr_chunks).strip()
        error = stderr_text if proc.returncode != 0 and not full_text else ""
        return AdapterResult(full_text or (stderr_text if proc.returncode == 0 else ""), session_id, error)

    def cancel_run(self, _session_id: str) -> None:
        if self._active is not None:
            self._terminate_process_tree(self._active)

    @staticmethod
    def _terminate_process_tree(proc: "subprocess.Popen[str]") -> None:
        if getattr(proc, "poll", lambda: None)() is not None:
            return
        try:
            process_group = os.getpgid(proc.pid)
            os.killpg(process_group, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process_group, signal.SIGKILL)
                proc.wait(timeout=3)
        except (AttributeError, ProcessLookupError, PermissionError):
            proc.terminate()


class ClaudeAdapter(CliToolAdapter):
    def __init__(self, command: str | None = None) -> None:
        cmd = command or os.environ.get("ARES_CLAUDE_COMMAND") or shutil.which("claude") or "/opt/homebrew/bin/claude"
        super().__init__(cmd, "claude", lambda prompt, agent: ["-p", prompt])


class CodexAdapter(CliToolAdapter):
    def __init__(self, command: str | None = None) -> None:
        cmd = command or os.environ.get("ARES_CODEX_COMMAND") or shutil.which("codex") or "/opt/homebrew/bin/codex"
        super().__init__(cmd, "codex", lambda prompt, agent: ["exec", "--skip-git-repo-check", prompt])


class GrokAdapter(CliToolAdapter):
    def __init__(self, command: str | None = None) -> None:
        cmd = command or os.environ.get("ARES_GROK_COMMAND") or shutil.which("grok") or str(Path.home() / ".grok" / "bin" / "grok")
        super().__init__(cmd, "grok", lambda prompt, agent: ["-p", prompt, "--permission-mode", "auto"])


class GeminiAdapter(CliToolAdapter):
    def __init__(self, command: str | None = None) -> None:
        cmd = command or os.environ.get("ARES_GEMINI_COMMAND") or shutil.which("gemini") or "/opt/homebrew/bin/gemini"
        super().__init__(cmd, "gemini", lambda prompt, agent: ["-p", prompt, "-y"])


#: Adapter class per runtime id. A runtime is promotable to ``durable=True`` in
#: ``core.runtimes`` only once it has an entry here -- ``default_adapters()``
#: enforces that pairing so a half-finished promotion fails at construction
#: with a clear message instead of at dispatch with a KeyError.
ADAPTER_TYPES: dict[str, type[AgentAdapter]] = {
    "hermes": HermesAdapter,
    "jaeger": JaegerAdapter,
    "openclaw": OpenClawAdapter,
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "grok": GrokAdapter,
    "gemini": GeminiAdapter,
}


def default_adapters() -> dict[str, AgentAdapter]:
    """Instantiate one adapter per durable runtime in the registry."""

    from ..runtimes import RUNTIME_BY_ID, durable_runtime_ids

    adapters: dict[str, AgentAdapter] = {}
    missing: list[str] = []
    for runtime_id in durable_runtime_ids():
        adapter_type = ADAPTER_TYPES.get(runtime_id)
        if adapter_type is None:
            missing.append(runtime_id)
            continue
        adapters[runtime_id] = adapter_type()
    if missing:
        labels = ", ".join(
            f"{rid} ({RUNTIME_BY_ID[rid].label})" for rid in missing
        )
        raise RuntimeError(
            "runtimes are marked durable in core.runtimes but have no adapter "
            f"in ADAPTER_TYPES: {labels}"
        )
    return adapters
