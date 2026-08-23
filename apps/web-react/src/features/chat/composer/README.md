# Composer Components

**WHAT:** The chat input box at the bottom of every conversation — textarea, attachment chips, and the toolbar of selector pills.

**WHERE YOU SEE IT:** Bottom of the chat column. On desktop: full toolbar with Backend, Workspace, Model, Reasoning, Toolsets chips. On mobile/narrow: collapses to Attach + Mic + Overflow button.

**KEY FILES:**
- `Composer.tsx` — The input frame (textarea, file preview, drag-drop)
- `ComposerToolbar.tsx` — The chip row (all selector buttons + Send)
- `Chip.tsx` — Reusable pill component (icon + label + LED + chevron)
- `chips.css` — All chip/popover styles + container query collapse logic
- `README.md` — This file

## How the Toolbar Collapses (Smart Responsive)

The toolbar uses **container queries** (`@container`) not viewport media queries. This means:

- **Desktop with sidebar OPEN:** Toolbar collapses even on 4K screen because chat column is narrow
- **Desktop with sidebar CLOSED:** Full toolbar shows
- **Mobile phone:** Overflow button appears, chips move to bottom sheet

**Collapse stages:**
1. **Wide (>700px):** All chips visible with labels
2. **Medium (520–700px):** Icon-only chips (labels hidden, `cf-icons` pattern)
3. **Narrow (<520px):** Only Attach + Mic + Overflow button (`cf-burger` pattern)

## Chips (Selector Pills)

Each chip is a `<Chip>` component with:
- **Icon** (Lucide)
- **Label** (current selection, e.g., "grok-4.6")
- **LED** (status indicator: emerald=ready, cyan=active, amber=warning, red=blocked)
- **Chevron** (opens dropdown on click)

**Chip types:**
- **Backend** — Switches AI adapter (Jaeger Local, Hermes Agent, Ollama Cloud)
- **Workspace** — Working folder + toggle right panel
- **Model** — Model selector (grouped by provider: Grok, Codex, Ollama)
- **Reasoning** — Thinking effort (none/low/med/high) — only shows if model supports it
- **Toolsets** — Global vs per-tool control (stub, Settings owns this)

## Popovers (Dropdown Menus)

All chip menus use `ComposerPopover` which:
- **Portals to `document.body`** — Never gets clipped by scrollbars or overflow
- **Positions dynamically** — Anchored to the chip, auto-flips if near screen edge
- **Closes on outside click or Escape** — Standard UX

## Mobile Overflow

Below 520px container width:
- Secondary chips hide (Reasoning, Toolsets, YOLO)
- Overflow button (⋮) appears
- Click opens bottom sheet with all options as 44px touch targets

## Teaching Comments

Every file has a 5-line header at the top:
```tsx
/**
 * WHAT: Component purpose
 * WHERE YOU SEE IT: Where on screen
 * CLICK: What happens on interaction
 * SAVES TO: Where state persists
 * HIDES WHEN: Responsive collapse conditions
 */
```

This is **Doctrine compliance**: "Teaching as a Feature" — a non-coder can read the code and understand what it does.
