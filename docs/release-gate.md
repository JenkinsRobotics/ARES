# ARES release gate

Every release candidate is built from a committed revision. Record the commit,
commands, expected result, actual result, environment, and untested boundaries.

## Required automated gates

- `python3 scripts/check_upstream_contract.py`
- `cd services/controller && ./scripts/test.sh -q tests/test_jaeger_ownership_literals.py`
- `bash scripts/smoke_clean_install.sh`
- Controller test suite and browser smoke
- `swift test`
- Secret and dependency vulnerability scans used by CI

The clean-install smoke must run from `git archive HEAD` with a temporary,
empty home and state directory. This proves the committed artifact rather than
the developer's checkout. A release fails if runtime behavior depends on a
personal username, absolute source path, sibling repository, or uncommitted
file.

## Required live gates

- Fresh install starts with no source checkout available.
- Existing supported user state upgrades without data loss.
- Three model turns retain the same session and clean prompt boundaries.
- A controlled bridge termination between turns recovers and recalls prior
  conversation state.
- At least one harmless tool call completes through the production bridge.
- Approval, denial, clarification, secret request, cancellation, and steering
  each exercise their production event path.
- Two simultaneous sessions do not cross transcripts, approvals, or tools.
- Sleep/wake and provider timeout recover without duplicate user-visible turns.
- A bounded 50-turn soak finishes without leaked processes or unbounded memory.
- The dispatcher benchmark records three of three successful attempts for at
  least one local execution engine. Each attempt must prove A2A-shaped
  capability registration, read-only tool use, same-session recall, bounded
  ARES RAG context, and clean completion.
- After the local-model keep-alive expires, Ollama reports no loaded model and
  system memory pressure is stable. Historical swap alone is not a failure;
  growing swap or an orphaned model process is.

Mail and other personal connectors remain read-only during release
qualification unless a separate destructive-action test environment is
explicitly authorized.

## Verdicts

Use `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN` for each row. “PASS” applies only to
the named boundary and recorded revision. Do not summarize partial evidence as
“fully working”, “production ready”, or an equivalent whole-application claim.
