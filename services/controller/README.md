# ARES controller

The controller owns ARES HTTP contracts, product metadata, projections, and
capability-gated workflows. Agent execution is delegated to JaegerAI through
`integrations/providers/jaeger/`.

Run and test:

```bash
./start_ares.sh
./scripts/test.sh -q tests/test_jaeger_ownership_literals.py
```

Do not add direct JaegerAI source, state, credential, model, persona, skill, or
MCP file access. Add owner bridge operations and advertise them through the
versioned contract instead.
