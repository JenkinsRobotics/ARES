# Provenance and third-party notices

ARES is licensed **AGPL-3.0** (see `LICENSE`). It is not written from scratch:
substantial parts are derived from MIT-licensed work, and the browser bundle
redistributes three MIT libraries verbatim. This file records what came from
where, and what obligations travel with it.

MIT into AGPL-3.0 is a permitted one-way combination. The condition is that the
original copyright notice and permission text travel with the code — which is
what the `LICENSE` files listed below are for. Renaming identifiers does not
discharge that obligation, so this file is the durable record even as the code
diverges.

---

## Derived work

### Hermes WebUI — MIT

**Upstream:** https://github.com/nesquena/hermes-webui
**Copyright:** © 2025 Hermes Web UI Contributors
**Notices retained at:** `apps/web/static/LICENSE`, `services/controller/LICENSE`

ARES began as a fork of Hermes WebUI and still carries a large amount of its
code. Two surfaces are affected, to very different degrees:

| Surface | Relationship |
| --- | --- |
| `apps/web/static/` | Largely unmodified. At the fork point seven of twelve JavaScript modules were byte-identical to upstream, and the browser code has diverged far less than the backend. |
| `services/controller/` | Rewritten, not forked line-for-line. Upstream's single-file threaded HTTP server became a FastAPI application with ~60 routers, but the request/response and SSE contracts, and much of the streaming engine, descend directly from it. |

Artifacts of that inheritance remain visible in the running system —
`localStorage` keys, the `HermesExtensionSettings` extension surface, and an
accepted `X-Hermes-CSRF-Token` header among them. Where those are renamed, the
attribution obligation stays with this file and the two `LICENSE` files above.

---

## Redistributed verbatim

Three MIT libraries ship inside the browser bundle under
`apps/web/static/vendor/`. Their minified builds mostly strip the upstream
license banners, so the notices are reproduced in
**`apps/web/static/vendor/LICENSES.md`**:

| Library | Version | License |
| --- | --- | --- |
| KaTeX | 0.16.22 | MIT — © 2013–2020 Khan Academy and other contributors |
| js-yaml | 4.1.0 | MIT — © 2011–2015 Vitaly Puzrin |
| streaming-markdown | bundled build | MIT — Damian Tarnawski |

---

## Interoperates with, but does not contain

Recorded so the boundary is explicit — **no code from these is vendored into
this repository**, so they impose no notice obligation here.

| Project | License | Relationship |
| --- | --- | --- |
| JaegerAI | Apache-2.0 | Runs as a separate process. ARES speaks to it over an NDJSON bridge; `integrations/providers/jaeger/` is ARES's own adapter code, not a copy of JaegerAI's. |
| JaegerOS · jaeger-agent | Apache-2.0 | Reached only through the JaegerAI process, never imported by ARES. |
| Hermes (agent) | MIT | An external agent that ARES can import memory and sessions from. `core/memory/journal/import_hermes.py` reads its data; it contains no Hermes source. |

If a future change vendors any Apache-2.0 code into this repository, that
introduces a `NOTICE` obligation under section 4 of the Apache License, and this
file must gain a NOTICE section.

---

## Maintaining this file

Update it in the same commit that changes what ships. In particular:

- Adding or upgrading anything under `apps/web/static/vendor/` — update the
  version and the notice in `vendor/LICENSES.md`.
- Vendoring code from any other project — add a row, and add its `LICENSE`
  alongside the code.
- Renaming donor identifiers — change nothing here. Provenance is unaffected by
  what the symbols are called.
