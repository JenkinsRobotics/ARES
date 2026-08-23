# Web UI

Production UI lives only here (`apps/web`). React + TypeScript + Vite → `dist/`, served by the controller on **:8788**.

## Layout files (start here for "it looks wrong on phone")

| File | Role |
| --- | --- |
| `src/styles/chat-layout.css` | Chat padding, gaps, safe-area, toolbar |
| `src/styles/shell-drawers.css` | Mobile session/workbench drawers |
| `src/features/chat/ConversationPage.tsx` | Chat behavior + remaining component styles |
| `src/components/shell/WorkspaceShell.tsx` | App frame |
| `src/components/shell/SessionSidebar.tsx` | Sessions |
| `src/components/shell/SideWorkbench.tsx` | Right tools pane |

## Rules

- Import features via `@/features/...` and shell via `@/components/shell/...`.
- Contracts/translators in `src/shared/` only — no raw worker field names in components.
- One visual/behavior slice at a time. Prefer CSS in `src/styles/*-layout.css` over new inline padding.
- Verify: `npm run typecheck && npm test -- --run && npm run build`
