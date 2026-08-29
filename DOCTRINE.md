# ARES doctrine

ARES is a transparent coordination system, not an AI persona or model runtime.

1. Hermes and JaegerAI are independent agents and remain usable when ARES is off.
2. Each agent owns its inference, tools, sessions, memory, identity, and secrets.
3. ARES owns definitions, goals, schedules, run leases, approvals, grants, and audit evidence.
4. Cross-product operations use explicit versioned adapters, MCP, or A2A; never private state access.
5. Sharing is default-deny and limited to the resource, operation, agent, and lifetime named by a grant.
6. Consequential actions fail closed and are inspectable before approval.
7. Deterministic workflow engines may execute plumbing; they do not decide agent policy or become the assistant.
8. One user-facing System Inbox may route to either agent, but it does not merge their private histories.
9. A feature is complete only when its contract, persistence, security checks, recovery behavior, and live verification agree.
