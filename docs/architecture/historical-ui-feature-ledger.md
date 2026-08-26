# Historical UI feature disposition ledger

This ledger prevents old ARES ideas from being rediscovered and described as
working without a current implementation. It compares the v1 baseline
(`e84815c9c`), the Jaeger ownership migration (`1302867b8`), the donor WebUI
refresh (`06b924444`), and the additive restoration series beginning at
`1880502ca`. A status describes the current tree, not the intent in an old
commit message.

Status vocabulary: **restored** is present again; **replaced** is served by a
current equivalent; **retired** was deliberately removed; **missing** has no
current public adapter; **rejected** conflicts with current ownership or safety.

| Historical capability | Disposition | Current evidence or reason |
|---|---|---|
| Mission-control / Dispatcher | restored | Isolated `mainDispatcher`, persistent mission session, Worklog projection, runtime/approval status, pinned context, outputs, Git and Operations cards. |
| Dispatcher retry and resume | restored | Canonical recovery API and effect-aware controls from `8a231525f`; halt state is shown rather than hidden. |
| Generic “undo anything” | rejected | External effects are not generally reversible. UI only offers undo when the effect ledger says the action is safely reversible. |
| Operations overview | restored | Isolated `mainOperations`; existing schedule, Kanban, goals and work-management APIs remain the owners. |
| Simultaneous Chat + recovered-tab split | retired | `a783ab076` makes Dispatcher and Operations mutually exclusive full-content views. Chat appears only when selected. |
| Library / unified conversation search | replaced | Workbench Library uses lineage-aware session search plus the document journal (`c388c4fea`). |
| Code intelligence / RepoMap | missing | Workspace and graph entry points remain; no stable public symbol-map/call-graph controller adapter exists. Workbench labels this “Adapter needed.” |
| Model Lab and routing history | restored | Workbench projects the existing model-intelligence catalog/history and links to the full Model Lab. |
| Skill Studio / usage | restored | Workbench projects installed skills and usage; persistent skill mutation is not autonomous. |
| Content Studio workflows | restored | Deep research, YouTube, PDF, image and report cards are capability-gated and link to the existing Content Studio. |
| Sibling ARES apps / extension hub | replaced | Connected Apps projects the extension registry and negotiated status rather than hard-wiring sibling products. |
| Theme creator | missing | Appearance remains in Settings; arbitrary theme editing needs an extension-owned validated asset contract. |
| Typography packs | missing | No validated font manifest/loader is currently exposed. |
| Skin packs and custom branding | missing | Current icon/appearance controls remain; historical arbitrary skins need sandboxed assets. |
| MCP shortcut gallery | missing | MCP management exists, but no negotiated shortcut projection is exposed to Workbench. |
| Avatar and live thought stream | restored | Current Avatar surface and transparent stream activity supersede the older incremental-thought implementation (`14dc74560`). |
| Plan / Manual / Auto composer modes | restored | Current composer modes from `d2d5e04e0`; no duplicate control was added to Dispatcher. |
| Cron / scheduled mission execution | replaced | Scheduled jobs execute through Jaeger ownership (`e7e4ec986`) and are projected into Dispatcher/Operations. |
| Hermes as canonical runtime | retired | Jaeger is the canonical runtime boundary (`579657fda`); Hermes remains a reference/upstream source, not a hidden production route. |
| Direct filesystem/runtime access from restored tabs | rejected | Recovered tabs consume public ARES APIs and canonical session state; they do not create a second executor or persistence store. |

## Audit procedure

Run these commands when changing the ledger:

```sh
git log --all --oneline -- apps/web
git diff e84815c9c..HEAD -- apps/web services/controller/fastapi_app
rg -n "Adapter needed|unavailable|switchPanel|data-panel" apps/web/static apps/web/templates
```

Every concept discovered in those baselines must land in one of the five
dispositions above. A commit message or comment is discovery evidence only;
runtime/API behavior is required before changing a row to **restored**.

