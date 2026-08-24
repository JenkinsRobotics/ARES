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
