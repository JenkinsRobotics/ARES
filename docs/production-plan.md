# ARES production plan

## Objective

Operate one dependable, remotely reachable assistant fabric on a Mac while
preserving the ownership boundaries of Hermes, JaegerAI, OpenClaw, and every
installed AI client. ARES coordinates work; it does not absorb an agent's
reasoning loop, transcript, credentials, or model configuration.

Production means more than a green status badge. A release is production-ready
only when its source is reproducible, private machine data is outside Git,
capabilities fail closed, restart recovery works, and the complete remote user
journey has current evidence.

## Target architecture

| Layer | Owner | Production responsibility |
| --- | --- | --- |
| Conversation and agent runtime | Hermes, JaegerAI, OpenClaw | Turns, sessions, memory, tools, model policy, credentials |
| Control plane | ARES | Goals, schedules, leases, routing, approvals, budgets, evidence, portal |
| Protocol edge | Agentgateway | Authenticated MCP and A2A routing only |
| Inference | Ollama | Distinct local and cloud model lanes; live capability discovery |
| Remote ingress | Tailscale Serve | Tailnet-only HTTPS and signed user identity |
| Native Mac boundary | ARES Host MCP | Typed, identity-scoped and audited host capabilities |
| Deterministic automation | n8n, optional | Workflows that remain subordinate to ARES policy |

The only supported production calls into an agent are its documented CLI,
HTTP API, MCP server, or A2A endpoint. ARES may store an opaque owner-issued
session ID, but it must not import agent source or directly read owner state.

## Repository and configuration policy

### Public agent repositories

- Stay at a released upstream revision whenever configuration or a supported
  protocol can provide the integration.
- Accept only generic owner-side fixes, protocol support, and tests that are
  useful without ARES or a particular operator's Mac.
- Never contain tailnet hostnames, usernames, absolute operator paths, selected
  production models, launchd instances, tokens, or live evidence.

### Public ARES repository

- Contains generic adapters, protocols, schemas, portal code, policy
  enforcement, installers, health checks, and documentation.
- Defaults to loopback binding, strict authentication, least privilege, bounded
  inputs, and explicit failure.
- Reads machine-specific choices from the private overlay rather than compiling
  them into source.

### Private machine overlay

`~/.ares/config/` owns non-secret machine settings. Files are mode `0600` and
the directory is mode `0700`.

- `system-fabric.json`: tailnet URL, allowed identities, bind/port choices, and
  shared workspace.
- `host-capabilities.json`: explicit additional workspace roots by identity.
- Keychain: credentials and bearer-token sources of truth. Tokens are never
  accepted in the JSON overlay.

Generated grants, runtime state, evidence, logs, quarantine, and backups remain
under `~/.ares/` and are not committed.

## Security model

1. Browser and management services bind to loopback by default.
2. Tailscale Serve is the only remote browser ingress; Funnel remains disabled.
3. Remote requests require an allowlisted, Tailscale-asserted user identity.
4. Agentgateway network endpoints require separate generated bearer tokens.
5. Host MCP starts with the shared workspace as its only root.
6. Read operations are audited. Consequential operations require a one-shot
   lease bound to agent, capability, payload hash, expiry, and approval record.
7. An approval must explain benefit, risks, exact scope, destination,
   reversibility, expiry, and a safer alternative.
8. Secrets never appear in messages, traces, command lines, JSON configuration,
   container metadata, or API responses.
9. Containers receive explicit mounts and resource limits. Ollama remains
   inaccessible from LAN and tailnet peers.
10. Global pause, per-run cancellation, bounded retries, and one active lease
    per agent are mandatory controls.

## Release phases

### Phase 0 — Source and state hygiene

Deliverables:

- Recoverable backup ref before cleanup in every dirty repository.
- No misplaced, generated, or operator-specific files in public worktrees.
- Generic changes split by owner: Jaeger fixes in JaegerAI; control plumbing in
  ARES; minimal UI adapter changes in the owner UI fork.
- Clean `git diff --check`, secret scan, and repository status after commits.
- Stale test/runtime instances quarantined rather than silently deleted.

Exit gate: every affected repository has a reviewable commit and clean status.

### Phase 1 — Reproducible control plane

Deliverables:

- One canonical runtime registry and an adapter for each durable runtime.
- Fail-fast startup if a durable runtime has no adapter.
- One System MCP catalog and one Agentgateway network edge.
- Machine overlay loaded through an allowlist; unknown or secret-like keys fail.
- Generic launchd labels and idempotent service installation.
- Database schema startup and restart recovery verified on a copy of production
  state before any future migration.

Exit gate: a cold login starts the same topology without an interactive shell.

### Phase 2 — Least-privilege host integration

Deliverables:

- Shared workspace is the only default host root.
- Additional roots are explicit in the private operator policy.
- No arbitrary shell or unrestricted delete, chmod, Keychain-read, process-kill,
  or service-mutation tool is exposed to an agent.
- Typed Calendar, Notes, Reminders, Shortcuts, camera, audio, PTZ, workspace, Git,
  and health operations enforce size, duration, path, and approval bounds.
- TCC preflight reports unavailable permissions without attempting unsupported
  programmatic grants.

Exit gate: negative tests prove path traversal, forged identity, replayed
approval, expired lease, changed payload, and direct remote access all fail.

### Phase 3 — Agent and model reliability

Deliverables:

- Hermes, JaegerAI, and OpenClaw independently pass probe, new session, resumed
  session, cancellation, timeout, restart, and goal completion tests.
- Ollama Local and Ollama Cloud remain separate provider lanes.
- Only live completion-and-tool-capable models are offered to agents.
- Model choice is an operator setting; installers fall back to the first live
  suitable model rather than embedding a private preference.
- Context and artifact transfer is bounded, resumable, and reports truncation.

Exit gate: each agent completes and resumes a unique acceptance conversation
without ARES reading its transcript store.

### Phase 4 — Remote production acceptance

Deliverables:

- Portal, Hermes, and Jaeger are reachable from a second tailnet device.
- OpenClaw remains behind ARES instead of exposing another remote control plane.
- MCP initialize/list/call and A2A Agent Card/message calls pass with valid auth.
- Missing, invalid, or wrong-user credentials fail with no information leak.
- Voice/camera actions show an approval before capture and save only under an
  approved workspace.
- Restart the Mac and repeat the critical path without local intervention.

Exit gate: signed second-device evidence covers login, message, approval,
cancellation, agent handoff, reconnect, and restart.

### Phase 5 — Operations, backup, and continuous verification

Deliverables:

- Health endpoint distinguishes process alive, dependency ready, degraded, and
  blocked states.
- Metrics cover CPU, memory, swap, disk, model load, queue depth, run age,
  approval age, error rate, and latency without exposing command lines or data.
- Alert on crash loops, stale active runs, runaway memory/swap, unavailable
  inference, expired approvals, and backup failure.
- Encrypted backups cover ARES databases/configuration and owner-supported agent
  exports; restore is tested quarterly into isolated state.
- Dependency digests and protocol versions are pinned and reviewed monthly.

Exit gate: a documented restore drill meets the recovery objectives below.

## Service objectives

| Objective | Target |
| --- | --- |
| Portal availability while Mac is awake and online | 99.5% monthly |
| Control API health response | p95 under 500 ms |
| Read-only MCP tool response excluding owner work | p95 under 2 s |
| Run dispatch acknowledgement | p95 under 2 s |
| Stale active-run reconciliation | under 5 minutes |
| Approval expiry | 15 minutes unless policy explicitly shortens it |
| Recovery point objective | 24 hours |
| Recovery time objective | 2 hours |

## Deployment checklist

### Pre-deploy

- [ ] Working trees contain only the intended release diff.
- [ ] Backup refs and current state/database backups exist.
- [ ] Focused tests and complete supported test suites pass.
- [ ] `git diff --check` and sensitive-data scans pass.
- [ ] Database migration and rollback behavior is tested if schemas changed.
- [ ] Private configuration parses and contains no credentials.
- [ ] Current resource baseline and active runs are recorded.
- [ ] Rollback commit IDs and service commands are recorded before restart.

### Deploy

- [ ] Install/reconcile host capability grants.
- [ ] Install launchd definitions and verify exactly one instance per service.
- [ ] Restart ARES, Agentgateway, proxies, Ollama, and managed containers in
      dependency order.
- [ ] Verify loopback health before changing Tailscale Serve.
- [ ] Run authenticated MCP and A2A smoke tests.
- [ ] Complete one short run on each durable agent.
- [ ] Verify the portal from a second tailnet device.

### Post-deploy

- [ ] Observe CPU, memory, swap, logs, error rate, and run reconciliation for at
      least 15 minutes.
- [ ] Confirm no duplicate/stale worker or MCP processes remain.
- [ ] Confirm restart persistence and owner session continuation.
- [ ] Record exact commands, results, commit IDs, and unresolved limitations.

## Rollback

Rollback is triggered by any of the following:

- authenticated MCP initialize or A2A messaging fails;
- a remote request bypasses identity enforcement;
- an effect executes without a valid exact-payload approval;
- two control planes or two instances of a singleton service are active;
- any agent loses owner session continuity or cannot cancel a run;
- controller error rate exceeds 5% for five minutes;
- controller RSS grows above 1 GiB or system swap grows continuously for 15
  minutes after model work has stopped;
- production state cannot be opened or migrated safely.

Rollback procedure:

1. Pause new ARES runs and deny pending approvals.
2. Stop only the affected launchd job or managed container.
3. Restore the previous local commit or pinned container digest.
4. Restore state only when a data migration—not application code—caused the
   failure; preserve the failed state for diagnosis.
5. Restart dependencies, rerun loopback smoke tests, then reopen remote ingress.
6. Record the failure, evidence, and corrective action before attempting another
   production deployment.

## Definition of done

The system is production-ready when all phase exit gates through Phase 4 pass,
the source trees are clean, the private overlay is reproducible, the remote
second-device drill is current, and rollback has been rehearsed. Phase 5 then
becomes the continuing operating standard rather than a one-time project.
