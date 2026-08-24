# Prime Upgrade audit — not installed functionality

The `~/.ares/prime_archetypes.json` and `~/.ares/memories/SOUL.md` drafts
are **unregistered**. ARES does not read them. They are not identity.

## Ownership

```text
ARES  = UI, character editor, status, approvals, image ingest
          │  AF_UNIX capability-negotiated bridge
          ▼
JaegerAI = character/v1, persona composition, permissions, runtime, tools
```

ARES is not a cognitive controller. Prompts cannot supersede permission
policy. Operating modes (Focus, Audit, Research) are runtime/workflow
configuration, not character lore.

## Registered personas

Bundled JaegerAI `character/v1` sheets (numeric HEXACO/SPECIAL sliders):

- `systems_principal`
- `research_strategist`
- `robotics_architect`
- `reliability_auditor`

ARES lists them through the existing `characters` bridge query.

## Image repair without touching the SI

`inspect_image_bytes` reads screenshot metadata locally (`jaeger_involved:
false`). Set `ARES_NO_JAEGER=1` when working on the ARES checkout so this
process does not attach to the live Jaeger instance.

Exact operator loop:

1. In a fresh terminal export `ARES_NO_JAEGER=1` and `ARES_NO_JAEGER_ATTACH=1`, then start the ARES controller. Do not stop or restart the live Jaeger flock.
2. In ARES, select `/Users/matthewjenkins/GitHub/ARES` as the session workspace.
3. Attach the UI screenshot in Chat. Local Pillow inspection reports `jaeger_involved: false` and never opens Jaeger's `state.db`.
4. Send `this UI is broken`. An image-only turn is also converted into a usable `[Image …]` message, so either form can begin the repair.

When attachment is intentionally enabled and Jaeger is running, the character picker enriches summaries through Jaeger's `character` detail bridge query. ARES never reads or owns the sheets.

Completion verification (2026-08-24): controller `5634 passed, 91 skipped, 1 xfailed, 2 xpassed, 16 subtests`; frontend `61 passed`; TypeScript and source-ownership gates passed. Implementation commits: `7c30f7846`, `7a02bf5d9`, `3e6172007`.
