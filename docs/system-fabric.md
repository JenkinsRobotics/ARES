# System fabric

## Components and ports

| Component | Bind | Authentication |
| --- | --- | --- |
| Hermes WebUI | `127.0.0.1:8787` | WebUI owner configuration |
| Jaeger WebUI | `127.0.0.1:8790` | Local/Tailscale browser boundary |
| Jaeger runner | `127.0.0.1:8791` | Loopback only |
| ARES dashboard/API | `127.0.0.1:8788` | Loopback/Tailscale boundary |
| Agentgateway MCP | `*:8811` | Strict generated bearer key |
| Agentgateway A2A | `*:8812` | Strict generated bearer key; Agent Card public |
| Agentgateway admin/metrics/readiness | loopback `15000/15020/15021` | Loopback only |
| n8n | `127.0.0.1:5678` | n8n owner setup |
| Ollama | `127.0.0.1:11434` plus container bridge | Ollama local/cloud configuration |

The gateway key is created at `~/.ares/gateway/client.token` with mode `0600`.
The generated config is `~/.ares/gateway/config.yaml`, also mode `0600`.

## MCP

Connect clients to `http://127.0.0.1:8811/mcp` with:

```http
Authorization: Bearer <gateway token>
```

Agentgateway prefixes tools by target:

- `system_*`: goals, wakes, run inspection/cancellation, approvals;
- `hermes_*`: Hermes-owned gateway/messaging operations;
- `jaeger_*`: native Jaeger health, turns, run events, and cancellation.

The System tools accept an explicit `agent_id`. A Jaeger MCP call goes through
the Jaeger runner facade and never boots a second Jaeger process.

## A2A

Agent Card:

```text
http://127.0.0.1:8812/.well-known/agent-card.json
```

JSON-RPC endpoint:

```text
http://127.0.0.1:8812/a2a
```

Send the bearer token and `A2A-Version: 1.0`. Prefix text with `@hermes`,
`[hermes]`, or `hermes:` (and the equivalent Jaeger forms) to select a runtime.

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
- ARES marks interrupted active runs `continue` with a restart checkpoint;
- stale Hermes session IDs are discarded only after Hermes reports that the
  session no longer exists;
- Jaeger runs use the native runner's run IDs and cancellation endpoint;
- no installer deletes an agent state directory or credential store.
