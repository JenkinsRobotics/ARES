# Architecture

## Product boundary

```text
                         ┌─ Hermes Agent (container) ─ Ollama on Mac
User / MCP / A2A ─ ARES ─┤
                         └─ JaegerAI (native Mac) ─── Ollama on Mac
```

ARES is deterministic control-plane plumbing. It selects an agent from explicit
policy, creates a durable goal and leased run, relays the request through an
adapter, records evidence, and evaluates the returned status. It does not choose
answers, run inference, execute another agent's tools, or merge agent memory.

The direct Hermes and Jaeger browser/CLI paths do not depend on ARES.

## Ownership map

| Owner | Authoritative state |
| --- | --- |
| Hermes | Hermes sessions, transcripts, memory, identity, tools, credentials, model policy |
| JaegerAI | Jaeger sessions, transcripts, memory, identity, tools, credentials, model policy |
| ARES | Definitions, goals, schedules, budgets, runs, approvals, grants, audit events |
| Agentgateway | Edge configuration, API-key policy, transient protocol sessions |
| n8n | Optional workflow definitions and execution state |

ARES stores only owner-issued session identifiers needed to resume a run. If an
agent deletes its history, the adapter discards the stale identifier and starts
a fresh owner session.

## Protocol boundaries

- `HermesAdapter` runs the installed `hermes` launcher noninteractively. Hermes
  remains containerized and chooses its configured model.
- `JaegerAdapter` calls the native versioned runner on `127.0.0.1:8791`.
- `system_mcp_server.py` exposes safe controller operations through MCP.
- `jaeger_mcp_proxy.py` maps MCP directly onto the native Jaeger runner without
  importing or booting Jaeger.
- Agentgateway federates MCP targets on `8811` and protects MCP/A2A with a
  generated bearer key.
- The official A2A Python SDK publishes an A2A v1 Agent Card and JSON-RPC handler.

## Integration strategy

ARES publishes one canonical, secret-free integration catalog. Installed MCP
clients (Claude Code/Desktop, Codex, Gemini/Antigravity, and VS Code) connect to
the same `ares-system` boundary. Agentgateway is the only network MCP gateway;
Docker MCP remains disabled to avoid a second policy and credential plane.

Remote OAuth services are discoverable but disabled until a user approves the
specific account and scope. Tool execution remains default-deny, host tools are
identity-scoped, approvals expire after 15 minutes, and every run carries a
trace ID through its evidence events. `scripts/configure-mcp-clients.py`
idempotently synchronizes supported local client configurations.

## Closed loop

1. A wake creates an immutable run record with agent, goal, policy version,
   trigger, attempt, and idempotency key.
2. A per-agent lease admits one active run.
3. The adapter streams normalized events and returns the owner session ID.
4. ARES evaluates `continue`, `complete`, `blocked`, `approval_required`,
   `failed`, `paused`, or `cancelled`.
5. Heartbeats may wake incomplete goals; bounded retries retain evidence.
6. Global pause blocks admission without modifying owner sessions.

## Access boundary

Browser and management interfaces bind to loopback. Hermes receives only its
declared Apple-container mounts. n8n receives its state directory and
`~/workspace`, not the user's home folder or credential stores. Jaeger stays
native because audio, Metal, Accessibility, and other macOS capabilities cannot
be delegated safely to a Linux container.

## External worker source boundary

ARES may discover an external worker installation and invoke its supported
contract, but it does not import or copy the worker's execution loop. Source
checkout discovery is a compatibility mechanism, not ownership: external stores
remain read-only and source mounts can be removed once an equivalent installed
client/contract is available. The detailed compatibility inventory remains in
[`rfcs/agent-source-boundary.md`](rfcs/agent-source-boundary.md).

See `system-fabric.md` for ports, installation, and protocol details.
