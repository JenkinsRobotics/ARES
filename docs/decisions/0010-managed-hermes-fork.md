# 0010 — Manage Hermes WebUI as an upstream fork with an ARES overlay

Status: accepted

Date: 2026-08-25

## Decision

ARES will track Hermes WebUI as a managed source upstream, not install the
entire Hermes application as a runtime dependency.

The immutable upstream and merge anchors live in
`upstream/hermes-webui.json`. Product-area classifications live in
`upstream/ownership.json`. `scripts/check_upstream_contract.py` validates both.

## Why

ARES changes application-level contracts: routing, streaming, sessions,
approvals, clarification, tools, Jaeger integration, native macOS lifecycle,
and recovery. A whole-application dependency would expose unsupported Hermes
internals as an accidental API and move ARES behavior into overrides or monkey
patches. An unmanaged copy, however, loses upstream security and reliability
fixes. A managed fork preserves both explicit ownership and upstream review.

Stable, separately versioned Hermes libraries may be consumed as normal
dependencies later. They must have a documented public API and may not own the
ARES controller or Jaeger boundary.

## Sync procedure

1. Start with clean ARES and JaegerAI worktrees. Never sync over an active
   verification or feature worktree.
2. Fetch `hermes-upstream` and record its exact commit and license.
3. Create a temporary sync branch or worktree from ARES `main`.
4. Compare upstream changes since `last_merged_upstream_commit`. Classify each
   affected area as `UPSTREAM`, `ARES_MODIFIED`, or `ARES_ONLY`.
5. Port upstream fixes into the reorganized ARES paths. Do not blindly run
   `git subtree pull`: the historical `webui/` subtree no longer matches the
   current `apps/web` and `services/controller` layout.
6. Run upstream-relevant tests, ARES controller tests, browser smoke, native
   tests, the clean-install smoke, and the upstream-contract check.
7. Update the immutable commit fields only after the merge rehearsal passes.
   The merge commit must state conflicts and how each ARES behavior was kept.

## Release boundary

An upstream sync is not proof that the ARES application works. A release still
requires the release gate in `docs/release-gate.md`. Results are stated per
boundary; the phrase “fully working” is not an accepted verdict.
