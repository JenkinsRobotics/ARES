# ARES contributor contract

Read `DOCTRINE.md` before changing product behavior.

ARES is the control fabric for independent agents. It is not a Hermes fork, a
Jaeger runtime, a shared transcript database, or an inference provider.

## Ownership

- Hermes owns Hermes turns, tools, sessions, memory, credentials, configuration, and model selection.
- JaegerAI owns Jaeger turns, tools, sessions, memory, credentials, configuration, and model selection.
- ARES owns agent definitions, goals, schedules, budgets, run leases, approvals, scoped grants, and audit events.
- Agentgateway owns only protocol-edge routing and authentication.
- n8n owns optional deterministic workflow execution; it has no authority to bypass ARES policy.
- Cross-product identifiers are canonical and opaque. ARES may persist an owner-issued session ID but never the owner's transcript or secret.

## Source map

- `services/controller/core/automation/`: durable controller and agent adapters
- `services/controller/apps/dashboard/static/`: minimal System dashboard
- `services/controller/fastapi_app/a2a_server.py`: A2A protocol adapter
- `services/controller/system_mcp_server.py`: System MCP tools
- `services/controller/jaeger_mcp_proxy.py`: Jaeger runner MCP facade
- `scripts/`: external dependency and service installers
- `apps/macos/`: optional native shell and macOS tools

## Rules

1. Never traverse or edit an agent's source, state, credentials, or configuration directly.
2. Use the Hermes launcher/WebUI API and the versioned Jaeger runner contract.
3. Never infer support from a runtime name or version; probe live capabilities.
4. Keep secrets out of JSON, messages, traces, logs, and API responses.
5. Bind browser and management services to loopback by default.
6. Network protocol endpoints require authentication and fail closed.
7. Validate workspace paths and keep container mounts explicit and minimal.
8. Preserve one active run lease per agent, idempotency keys, bounded retries, cancellation, and global pause.
9. Default-deny all cross-agent sharing; add only explicit scoped grants.
10. Commit approved work locally; push only when the user asks.

## Verification

Read the implementation and test the production wiring. Report the exact
command and observed result; do not turn old evidence or mocks into a standing
claim.

```bash
cd services/controller
PYTHONPATH=../.. .venv/bin/python -m pytest -q \
  tests/test_automation_controller.py tests/test_system_protocols.py
cd ../..
git diff --check
```

Live acceptance must independently verify Hermes, Jaeger, ARES routing, MCP and
A2A authentication, persistence after restart, cancellation/pause behavior,
and browser reachability.
