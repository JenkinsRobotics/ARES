# Architecture

## Product boundary

```text
User → ARES UI → ARES controller → versioned adapter → JaegerAI
```

ARES owns UI workflows and product metadata. JaegerAI owns agent execution,
transcripts, tools, skills, MCP, credentials, models, personas, and runtime
history. ARES combines owner projections but does not duplicate authoritative
transcripts or edit JaegerAI files.

## Integration rules

- The stdio bridge is the canonical local JaegerAI transport.
- The bridge advertises a versioned contract and live capabilities.
- ARES routes mutations to the owner and treats retries as idempotent.
- Session deletion uses tombstones so imports or restarts cannot resurrect it.
- Secrets remain in the owner credential service; ARES receives references or
  redacted status only.
- UI features stay visible with explicit unavailable states. User settings may
  disable a feature or plugin.

### External worker source boundary

ARES does not import or copy the worker's execution loop. Development source mounts can be removed
without changing the product contract; only the installed
runtime launcher and versioned bridge are dependencies.

## Dynamic inventory

Routers, routes, tools, skills, plugins, MCP servers, and capabilities are
enumerated from their registries and negotiated runtime contract. Documentation
does not contain numeric inventory claims.

## Extensibility

Agent-callable integrations use tools, skills, MCP, or the generic plugin
manifest. App-only presentation belongs to ARES. Sidecars bind to loopback,
authenticate, receive only declared environment variables, and require approval
for administrative actions.
