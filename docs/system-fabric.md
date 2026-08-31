# System fabric

## Components and ports

| Component | Bind | Authentication |
| --- | --- | --- |
| Hermes WebUI | `127.0.0.1:8787` | Loopback; Tailscale identity proxy on `127.0.0.1:8786` |
| Jaeger WebUI | `127.0.0.1:8790` | Loopback; Tailscale identity proxy on `127.0.0.1:8785` |
| Jaeger runner | `127.0.0.1:8791` | Loopback only |
| ARES dashboard/API | `127.0.0.1:8788` | Loopback; exact Tailscale user enforced on remote requests |
| OpenClaw gateway | `127.0.0.1:18789` | Token-authenticated, digest-pinned container runtime; reached through ARES |
| Agentgateway MCP | `*:8811` | Strict generated bearer key |
| Agentgateway A2A | `*:8812` | Strict generated bearer key; Agent Card public |
| Agentgateway admin/metrics/readiness | loopback `15000/15020/15021` | Loopback only |
| n8n | `127.0.0.1:5678` | n8n owner setup |
| Ollama | `127.0.0.1:11434` | ARES-managed; Apple containers use the runtime's host redirect/bridge |

## Remote access

Tailscale Serve is the only browser ingress. Funnel is disabled, so none of
these URLs are public internet endpoints. Tailnet ACLs are the outer boundary;
ARES validates Tailscale's signed-in user header and the direct Hermes/Jaeger
routes pass through owner-only loopback identity proxies. Tailscale Serve
strips client-supplied identity headers before adding its own.

| Surface | Tailnet URL pattern |
| --- | --- |
| ARES command portal | `https://<tailnet-host>:8444/` |
| Hermes owner UI | `https://<tailnet-host>/` |
| Jaeger owner UI | `https://<tailnet-host>:8443/` |

Use the ARES portal for the unified path. Its agent selector is populated from
the live `/api/agents` inventory and can message Hermes, Jaeger, or OpenClaw.
OpenClaw stays loopback-only; ARES reaches its authenticated container CLI, so
there is no second public/token-bearing browser endpoint to maintain.

The machine-local `~/.ares/config/system-fabric.json` supplies the deployed
tailnet URL and allowed identities. The ARES Agent Card advertises its configured
`ARES_A2A_PUBLIC_URL`; no private hostname is compiled into the repository.

The owner key is created at `~/.ares/gateway/client.token` with mode `0600`.
Hermes receives a different key at `~/.hermes/ares/ares-mcp.token`.
The generated config is `~/.ares/gateway/config.yaml`, also mode `0600`.

## MCP

Connect clients to `http://127.0.0.1:8811/mcp` with:

```http
Authorization: Bearer <gateway token>
```

Agentgateway prefixes tools by target:

- `system_*`: goals, wakes, run inspection/cancellation, approvals, and system metrics;
- `host-hermes_*`: Hermes-scoped Mac workspace capabilities, Apple integrations, and physical perception (camera, microphone, PTZ gimbal).

See [mcp-catalog.md](mcp-catalog.md) for the exhaustive tool reference, input
schemas, and capability grants.

The owner key can use both target groups. Gateway authorization filters the
Hermes key before tool discovery:

- the Hermes key sees only `host-hermes_*`;
- it cannot see System or owner routing tools.

The host worker enforces the same boundary again from
`~/.ares/capabilities/grants.json`. Every identity receives only the configured
shared workspace by default. Additional roots must be declared explicitly in
the private `~/.ares/config/host-capabilities.json` operator policy. Available
operations are bounded text-file list/read/write/mkdir/move, read-only Git
status/diff, capability inspection, service health, Apple tools (Calendar,
Notes, Reminders, Shortcuts), and camera vision/audio/PTZ. Writes are atomic,
limited to 1 MB, and require a SHA-256 precondition before changing an existing
file. There is no shell, delete, chmod, Keychain-value, or service mutation
tool. Metadata-only audit records are appended to
`~/.ares/audit/host-capabilities.jsonl`.

Hermes reaches the MCP listener from its Apple container through the Mac's
Tailscale address rather than container loopback. Configure it with the
identity-specific token and a 60-second discovery timeout because the gateway
federates several independent stdio targets. Never give it the owner token.

The System tools accept an explicit `agent_id` and route through ARES adapters.
Jaeger's private MCP worker never boots a second Jaeger process.

## A2A

Agent Card:

```text
http://127.0.0.1:8812/.well-known/agent-card.json
```

JSON-RPC endpoint:

```text
http://127.0.0.1:8812/a2a
```

Send the bearer token and `A2A-Version: 0.3`. Prefix text with a registered
durable agent id, including `@hermes`, `@jaeger`, or `@openclaw`, to select a
runtime explicitly.

## External dependencies

`config/system-fabric.lock.json` pins:

- Agentgateway, installed as a checksum-verified native binary;
- the official A2A Python SDK;
- n8n as an optional external workflow service.

n8n is source-available under its Sustainable Use License, not an ARES code
dependency. Paperclip is not installed because its company/agent authority
model would duplicate the deliberately small ARES ownership layer. Either can
be connected later through MCP, A2A, webhook, or a narrow adapter.

## Recovery

- launchd keeps Agentgateway active and starts managed Apple containers at login;
- Tailscale Serve configuration persists independently of ARES and proxies only
  to loopback owner services;
- the Mac is configured with AC system sleep disabled (`sleep 0`) and Wake on
  network access enabled (`womp 1`);
- ARES reconciles interrupted/stale runs and goals, retaining terminal reasons;
- stale Hermes session IDs are discarded only after Hermes reports that the
  session no longer exists;
- Jaeger runs use the native runner's run IDs and cancellation endpoint;
- no installer deletes an agent state directory or credential store.
