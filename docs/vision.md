# ARES vision

ARES makes independently built agent frameworks behave like one understandable
personal system without pretending they share one brain.

The user may talk directly to Hermes, directly to JaegerAI, or through the
System Inbox. The System route follows explicit policy and preserves the chosen
agent's identity and session. A shared control policy can make the experience
coherent, while ownership boundaries prevent accidental credential, memory, or
tool leakage.

## Product principles

1. **One relationship, visible routing.** The system can feel continuous, but
   every run shows which agent acted and why.
2. **Independent agents.** Hermes and Jaeger remain complete, directly usable
   products when ARES is stopped.
3. **Closed-loop automation.** ARES supplies schedules, wakeups, evaluation,
   pause, approval, retry, and audit—not model reasoning.
4. **Default-deny sharing.** Tools, memory, sessions, workspaces, and credentials
   cross a boundary only through an explicit scoped grant.
5. **Replaceable plumbing.** MCP, A2A, Agentgateway, and optional workflow
   engines are dependencies behind contracts, not forks that ARES must own.
6. **Reproducible setup.** Pinned installers and conservative defaults should
   let another Mac reproduce the topology without copying personal state.

ARES is the system around the assistants. It is not a third assistant.
