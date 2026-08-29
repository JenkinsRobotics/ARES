# Experimental agent improvements

Micro-compaction and autonomous skill learning are not enabled production
features. They remain experiments until measurements and approval controls
justify adoption.

## Micro-compaction gate

Compare the current whole-arc compaction with incremental summaries on the same
long-session corpus. Record:

- wall-clock latency and provider token cost;
- prompt-token reduction;
- exact fact/task/tool-result recall on second and third turns;
- summary drift after repeated compactions;
- recovery fidelity after controller and Jaeger restarts.

Adoption requires no material recall regression, lower total token cost, and no
new lineage/session-rotation failure. Synthetic extractive tests are useful for
calibrating the harness but are not evidence about model-generated summaries.
Results must name the model/provider, corpus revision, commits and command.

## Approval-gated skill learning contract

An agent may propose a skill change, but may not activate it. A proposal must be
a reviewable diff with source-run lineage, cited observations, security scope,
tests, rollback instructions and a content hash. A human approval creates a
separate activation event. Rejection and rollback are durable events as well.

Proposals must never collect credentials, silently broaden tool permissions,
modify another profile, or treat generated text as trusted instructions. Until
the proposal/approval/rollback event model and adversarial tests exist, skill
learning remains disabled.
