# ARES

ARES is the local control fabric for independently owned AI agents. It gives a
person or another agent one audited place to create goals, route work, approve
consequential actions, and inspect results without turning ARES into another
chat model or copying an agent's private memory.

Hermes Agent and JaegerAI remain useful on their own. ARES connects them with
explicit adapters and default-deny sharing.

## What runs on this Mac

| Service | Role | Location | Address |
| --- | --- | --- | --- |
| Hermes Agent + WebUI | Stable reference agent | Apple container | `http://127.0.0.1:8787` |
| JaegerAI + WebUI adapter | Native macOS agent | Host | `http://127.0.0.1:8790` |
| ARES System dashboard/API | Goals, routing, approvals, audit | Host | `http://127.0.0.1:8788` |
| Agentgateway | Authenticated MCP and A2A edge | Host | MCP `8811`, A2A `8812` |
| OpenClaw gateway | Third agent runtime | Apple container | `http://127.0.0.1:18789` |
| n8n | Optional deterministic workflow executor | Apple container | `http://127.0.0.1:5678` |
| Ollama | Local weights and Ollama Cloud routing | Host | `http://127.0.0.1:11434` |

ARES never imports Hermes Agent, JaegerAI, or OpenClaw. Hermes is invoked
through its installed launcher; Jaeger is reached through its versioned native
runner API; OpenClaw is reached through its own CLI inside the container ARES
manages for it. Each agent owns its own sessions, memory, tools, credentials,
and model policy.

Which runtimes exist, how they are deployed, and which may hold durable goals
are all declared in one place. See [docs/agent-runtimes.md](docs/agent-runtimes.md).

## Install the System fabric

The checked-in lock file pins the external components and checksums used by the
installer. On an Apple Silicon Mac with Apple `container`, Hermes, JaegerAI,
ARES, and Ollama already installed:

```bash
cd ~/GitHub/ARES/services/controller
.venv/bin/pip install -r requirements.txt

cd ~/GitHub/ARES
./scripts/install-agentgateway.py
./scripts/configure-host-capabilities.py
./scripts/configure-system-fabric.py
./scripts/install-openclaw-container.sh
./scripts/install-n8n-container.sh
./scripts/install-system-services.py
```

The service installer creates login jobs for Agentgateway and the managed Apple
containers. ARES and Jaeger retain their existing native launch jobs during
development.

n8n is optional and starts loopback-only with a dedicated state directory and
the single shared folder `~/workspace`. Finish n8n's owner setup locally before
considering remote access.

## Talk to the system

The ARES dashboard has a small System Inbox. Pick Hermes or Jaeger and send a
goal; ARES records the goal, run, events, and final state.

Agentic clients such as Claude Code, Codex, and other MCP clients can connect to:

```text
http://127.0.0.1:8811/mcp
Authorization: Bearer <contents of ~/.ares/gateway/client.token>
```

Owner tools are namespaced as `system_*`. Hermes receives a separate
credential that reveals only `host-hermes_*`. Jaeger connects to the same
ARES-owned capability worker through its private native stdio configuration,
so it does not depend on the remote gateway. ARES also
publishes an official A2A v1 Agent Card at:

```text
http://127.0.0.1:8812/.well-known/agent-card.json
```

A2A calls require the same bearer token and `A2A-Version: 0.3`. Prefix a request
with `@hermes` or `@jaeger` to choose explicitly; otherwise the configured
default is Hermes.

## Safety boundary

- Sharing tools, memory, sessions, workspaces, or credentials is off unless a
  scoped grant says otherwise.
- Credentials are opaque Keychain references, never values stored in ARES JSON.
- ARES executes one leased run per agent and records immutable run events.
- Consequential operations fail closed and require approval.
- The global pause blocks new work without deleting active session history.
- Browser services bind to loopback; Tailscale publication is an explicit host
  configuration, not a repository default.
- Agentgateway's admin, metrics, and readiness endpoints bind to loopback. MCP
  and A2A require a generated API key.
- Host capabilities expose approved workspace read/write, read-only Git, and
  service health only. There is no arbitrary shell, delete, or credential tool.

## Repository map

- `services/controller/core/automation/` — durable goals, runs, policy, adapters
- `services/controller/fastapi_app/a2a_server.py` — official A2A v1 surface
- `services/controller/system_mcp_server.py` — ARES control-plane MCP tools
- `services/controller/jaeger_mcp_proxy.py` — MCP-to-native-Jaeger bridge
- `services/controller/host_capability_mcp_server.py` — scoped, audited Mac work tools
- `services/controller/apps/dashboard/static/` — lightweight System dashboard
- `scripts/` — checksum-verified gateway, container, and launchd installers
- `config/system-fabric.lock.json` — pinned external dependencies
- `docs/system-fabric.md` — protocol, state, and security details
- `docs/production-plan.md` — release gates, operations, and rollback plan

See `DOCTRINE.md`, `docs/vision.md`, `docs/architecture.md`, `docs/api.md`,
and `docs/development.md` before changing ownership boundaries.
