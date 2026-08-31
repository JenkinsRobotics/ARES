#!/usr/bin/env python3
"""Evidence-backed benchmark for ARES dispatcher execution engines.

The benchmark temporarily routes each durable agent through one local Ollama
model, then restores the exact original Agent record.  A successful attempt
must prove all five requirements: A2A-shaped registration JSON, a real
read-only file tool, owner-session continuity, ARES RAG retrieval, and clean
completion.  Results are recorded through the controller API and become the
dispatcher selector's qualification evidence.
"""

from __future__ import annotations

import argparse
import json
import secrets
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_ROOT = REPO_ROOT / "services" / "controller"
for candidate in (str(REPO_ROOT), str(CONTROLLER_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from core.memory.context_store import reindex_source

REQUIRED_PROBES = (
    "capability_registration",
    "read_only_tool",
    "session_continuity",
    "rag_context",
    "completion",
)
TERMINAL = {"complete", "blocked", "approval_required", "failed", "cancelled", "timed_out"}


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail[:500]}") from exc

    def wait_run(self, run_id: str, timeout: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                runs = self.request("GET", "/api/runs")
                run = next((row for row in runs if row["id"] == run_id), None)
                if run and run.get("status") in TERMINAL:
                    return run
                time.sleep(0.5)
            self.request("POST", f"/api/runs/{run_id}/cancel", {})
            cancel_deadline = time.monotonic() + 10
            while time.monotonic() < cancel_deadline:
                runs = self.request("GET", "/api/runs")
                run = next((row for row in runs if row["id"] == run_id), None)
                if run and run.get("status") in TERMINAL:
                    return run
                time.sleep(0.25)
            return {
                "id": run_id,
                "status": "timed_out",
                "result": "",
                "error": f"benchmark timeout after {timeout}s; cancellation did not settle within 10s",
            }
        except BaseException:
            # Ctrl-C and harness errors must not leave an expensive local
            # model turn running after the benchmark process exits.
            try:
                self.request("POST", f"/api/runs/{run_id}/cancel", {})
            except (OSError, RuntimeError) as exc:
                print(f"warning: could not cancel interrupted run {run_id}: {exc}", file=sys.stderr)
            raise


def _first_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for offset, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _settle_noncomplete_benchmark_run(api: Api, run: dict[str, Any]) -> None:
    status = str(run.get("status") or "")
    if status == "complete":
        return
    if status == "approval_required":
        for approval in api.request("GET", "/api/approvals"):
            if approval.get("run_id") != run.get("id") or approval.get("status") != "pending":
                continue
            resolved = api.request("POST", "/api/approvals", {
                "id": approval["id"],
                "decision": "denied",
            })
            resumed_run_id = str(resolved.get("resumed_run_id") or "")
            if resumed_run_id:
                api.request("POST", f"/api/runs/{resumed_run_id}/cancel", {})
    if not run.get("goal_id"):
        return
    terminal = {
        "approval_required": "blocked",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
    }.get(status, "failed")
    api.request("POST", f"/api/goals/{run['goal_id']}/close", {
        "status": terminal,
        "reason": (
            "Dispatcher benchmark attempt did not complete; approvals are denied "
            "and benchmark goals are never retried."
        ),
    })


def _run_attempt(
    api: Api,
    agent: dict[str, Any],
    attempt: int,
    fixture_paths: dict[str, str],
    file_nonce: str,
    rag_nonce: str,
    timeout: int,
) -> dict[str, Any]:
    session_nonce = f"session-{secrets.token_hex(8)}"
    prompt_payload = api.request(
        "GET",
        f"/api/dispatcher/benchmarks/{urllib.parse.quote(agent['id'])}/prompt?nonce={session_nonce}",
    )
    runtime_path = fixture_paths[agent["runtime"]]
    first_prompt = (
        f"{prompt_payload['prompt']}\n"
        "The relevant RAG topic is: ARES dispatcher context validation protocol. "
        f"Use a read-only file tool to read {runtime_path}. Do not use shell execution. "
        "The file and RAG nonces are unknown to you until their respective evidence sources are read."
    )
    thread = api.request("POST", "/api/threads", {
        "agent_id": agent["id"],
        "routing_mode": "direct",
        "title": f"Dispatcher benchmark {agent['id']} attempt {attempt}",
    })
    started = time.monotonic()
    first = api.request("POST", f"/api/threads/{thread['id']}/messages", {
        "agent_id": agent["id"], "content": first_prompt,
        "idempotency_key": f"dispatcher-benchmark:{agent['id']}:{attempt}:first:{session_nonce}",
    })
    first_run = api.wait_run(first["run"]["id"], timeout)
    _settle_noncomplete_benchmark_run(api, first_run)
    registration = _first_json_object(str(first_run.get("result") or ""))

    if first_run.get("status") != "complete":
        latency = time.monotonic() - started
        first_text = str(first_run.get("result") or "")
        probes = {
            "capability_registration": False,
            "read_only_tool": file_nonce in first_text,
            "session_continuity": False,
            "rag_context": rag_nonce in first_text,
            "completion": False,
        }
        return {
            "passed": False,
            "probes": probes,
            "latency_seconds": latency,
            "first_run_id": first_run["id"],
            "second_run_id": "",
            "first_status": first_run.get("status"),
            "second_status": "not_run",
            "registration": registration,
            "first_output": first_text[:2000],
            "second_output": "",
            "error": str(first_run.get("error") or "first turn did not complete"),
        }

    second = api.request("POST", f"/api/threads/{thread['id']}/messages", {
        "agent_id": agent["id"],
        "content": (
            "Without rereading a file or using a tool, return the exact session_nonce from the previous turn "
            "inside one JSON object with keys session_nonce and status."
        ),
        "idempotency_key": f"dispatcher-benchmark:{agent['id']}:{attempt}:second:{session_nonce}",
    })
    second_run = api.wait_run(second["run"]["id"], timeout)
    _settle_noncomplete_benchmark_run(api, second_run)
    latency = time.monotonic() - started
    first_text = str(first_run.get("result") or "")
    second_text = str(second_run.get("result") or "")
    probes = {
        "capability_registration": (
            str(registration.get("schema_version") or "").startswith("1")
            and registration.get("runtime_id") == agent["runtime"]
            and isinstance(registration.get("observed_tools"), list)
        ),
        "read_only_tool": file_nonce in first_text,
        "session_continuity": session_nonce in second_text,
        "rag_context": rag_nonce in first_text,
        "completion": first_run.get("status") == "complete" and second_run.get("status") == "complete",
    }
    return {
        "passed": all(probes.values()),
        "probes": probes,
        "latency_seconds": latency,
        "first_run_id": first_run["id"],
        "second_run_id": second_run["id"],
        "first_status": first_run.get("status"),
        "second_status": second_run.get("status"),
        "registration": registration,
        "first_output": first_text[:2000],
        "second_output": second_text[:1000],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--model", default="gemma4:latest")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--agents", nargs="*", default=[])
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be positive")

    api = Api(args.base_url)
    inventory = api.request("GET", "/api/agents")["agents"]
    selected = [row for row in inventory if not args.agents or row["id"] in set(args.agents)]
    if not selected:
        raise SystemExit("No matching durable agents are registered")

    file_nonce = f"file-{secrets.token_hex(12)}"
    rag_nonce = f"rag-{secrets.token_hex(12)}"
    rag_source = f"dispatcher-benchmark-{secrets.token_hex(8)}"
    shared_workspace = Path.home() / "workspace"
    shared_workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="ares-dispatcher-benchmark-", suffix=".txt",
        dir=shared_workspace, encoding="utf-8", delete=False,
    ) as fixture:
        fixture_path = Path(fixture.name)
        fixture.write(f"ARES read-only tool evidence nonce: {file_nonce}\n")
    fixture_paths = {
        "hermes": f"/workspace/{fixture_path.name}",
        "openclaw": f"/workspace/{fixture_path.name}",
        "jaeger": str(fixture_path),
    }
    rag_text = (
        "# ARES dispatcher context validation protocol\n\n"
        "For the active dispatcher benchmark only, the context evidence nonce is "
        f"{rag_nonce}. Return it as context_nonce.\n"
    )
    if not reindex_source(rag_source, "benchmark", "ARES dispatcher benchmark", rag_text):
        fixture_path.unlink(missing_ok=True)
        raise SystemExit("Could not index the temporary RAG benchmark source")

    reports: list[dict[str, Any]] = []
    try:
        for original in selected:
            local = {
                **original,
                "model": args.model,
                "model_provider": "ollama-local",
                "model_location": "local",
                "max_turns": min(8, int(original.get("max_turns") or 8)),
                "timeout_seconds": min(args.timeout, int(original.get("timeout_seconds") or args.timeout)),
                # The benchmark is intentionally read-only. Restricting the
                # declared toolset also keeps Hermes' tool schema small enough
                # that the model is measured on the requested capability
                # instead of tens of unrelated integrations.
                "toolsets": ["file"],
            }
            api.request("PUT", "/api/agents", local)
            attempts: list[dict[str, Any]] = []
            try:
                for index in range(1, args.attempts + 1):
                    report = _run_attempt(
                        api, local, index, fixture_paths, file_nonce, rag_nonce, args.timeout,
                    )
                    attempts.append(report)
                    print(json.dumps({"agent": original["id"], "attempt": index, **report["probes"]}, sort_keys=True), flush=True)
            finally:
                api.request("PUT", "/api/agents", original)

            aggregate_probes = {
                probe: all(row["probes"][probe] for row in attempts)
                for probe in REQUIRED_PROBES
            }
            record = api.request("POST", f"/api/dispatcher/benchmarks/{original['id']}", {
                "model": args.model,
                "model_location": "local",
                "attempts": len(attempts),
                "successes": sum(1 for row in attempts if row["passed"]),
                "median_latency_seconds": statistics.median(row["latency_seconds"] for row in attempts),
                "probes": aggregate_probes,
                "evidence": {"attempts": attempts},
            })
            reports.append(record)
            print(json.dumps({
                "agent": original["id"], "passed": record["passed"],
                "success_rate": record["success_rate"], "tier_scores": record["tier_scores"],
            }, sort_keys=True), flush=True)
    finally:
        fixture_path.unlink(missing_ok=True)
        # Reindexing an empty source deletes its chunks. The harmless source
        # metadata row remains as an auditable record that a benchmark ran.
        reindex_source(rag_source, "benchmark", "ARES dispatcher benchmark", "")

    print(json.dumps({"reports": reports}, indent=2, sort_keys=True))
    return 0 if all(row["passed"] for row in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
