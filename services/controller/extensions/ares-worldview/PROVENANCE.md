# Provenance

`ares-worldview` is an ARES extension **drafted** from a local clone of

**Upstream:** https://github.com/kevtoe/worldview  
**Snapshot SHA:** `44e0900ad0bf8530a974a6cdab181342c42b06e9`  
**Clone name on this machine:** `worldview2`

A frozen copy of that SHA also lives in the gitignored tree
`ARES/drafts/upstream/worldview2/`.

## License status (blocking for publish)

The upstream tree has **no LICENSE file**. Its README states the project is
for educational and demonstration purposes and that no commercial use is
intended. External API use is subject to each provider's terms.

Until that is resolved with the author, or the globe is rewritten:

- Keep this repo **local**.
- Do not `git push` to Jenkins Robotics.
- Do not ship inside an ARES release tarball.

New ARES wrapper files (`manifest.json`, `dashboard/`, this file,
`EXTENSION.md`) are Jenkins Robotics scaffolding for the extension slot.
They do not relicense the upstream Cesium app or Express sidecar.

## What was copied

Tracked files from `git archive HEAD` of `worldview2` at the SHA above.
Not copied: `.git`, `node_modules/`, `dist/`.
