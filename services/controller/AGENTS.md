# Controller

FastAPI app under `services/controller/`. Serves API + `apps/web/dist` on **:8788**.

## Docs

- Product/architecture: repo `docs/`
- RFCs: `docs/rfcs/`
- ADRs: `docs/decisions/`

Do not resurrect hermes-webui leftover guides into this tree. Removed copies live on Desktop archives if needed.

## Rules

- Read root `AGENTS.md` and `DOCTRINE.md` first.
- Workers via adapters only; no absorbing peer execution loops.
- Targeted pytest while iterating.
