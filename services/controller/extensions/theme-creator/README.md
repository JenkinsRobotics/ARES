# Theme Creator

Theme Creator is a trusted local ARES extension that lets you **build your
own theme**. Pick colors for the key design tokens, watch a live preview, name
it, and save — your custom theme registers into the **native Settings →
Appearance** skin picker, selectable and persisted like a built-in skin. Create,
edit, and delete as many themes as you like.

This is the extension form of the closed core PR #1589 ("user-defined custom
themes" by @Michaelyklam), which was declined for core on curation grounds —
custom user themes are exactly the kind of opt-in, local personalization the
extension system is for.

## What It Does

- Adds a rail button that opens the Theme Creator panel.
- A curated set of color inputs (background, surfaces, text, muted, accent,
  borders, your-message bubble), each with a color picker + hex field.
- **Optional background image upload**: pick a JPEG/PNG from your device; it's
  compressed and resized client-side (max 1920 px wide, ~70% JPEG quality),
  stored as a base64 data URL in the theme record, and applied directly on
  `:root` as the page background. Surface CSS variables (`--bg`, `--surface`) take
  dynamic opacity from the **Glass opacity slider**, and `backdrop-filter: blur(...)` (configurable
  0-50px via the **Blur intensity slider**) is applied directly to known panel
  containers (`nav.rail`, `aside.sidebar`, `aside.rightpanel`, `div.main-view`)
  via class selectors — covering panels whose backgrounds are hardcoded in the
  core CSS (not using CSS variables). The result is a **glassmorphism /**
  **frosted-glass** effect where the background image shows through all
  surfaces — the sidebar, conversation list, chat area, and input bar —
  with a smooth blur. Remove the image to restore solid colours.
- **Glass opacity slider** (1-50%): adjusts the transparency of all frosted-glass
  panel backgrounds in real time. Lower = more transparent (more image visible);
  higher = more solid. Saved per theme, reflected in live preview.
- **Blur intensity slider** (0-50px): adjusts the `backdrop-filter` blur on glass
  panel surfaces. 0px = no blur (clear glass), higher values = frosted effect.
  Saved per theme, reflected in live preview.
- **Live preview** applies the in-progress theme (colours + image + glass opacity + blur)
  app; **Stop preview** reverts to your previous skin.
- **Save** registers the theme into the native Appearance picker and applies it.
- **Saved themes** list: apply / edit / delete each.
- Everything is stored locally (`hermes-ext-custom-themes`); nothing is uploaded.

## How it stays usable (and safe)

Rather than expose ~30 raw CSS tokens, the editor offers a handful of primary
colors and **derives** the rest (the full accent family, secondary surfaces,
borders, code background, etc.) with simple color math. Every derived value is
still sent through the core `registerHermesSkin` **sanitizer**, so an invalid or
malicious color value can never be applied — the core capability is the single
security chokepoint.

## Code / chat surface coverage

The core `registerHermesSkin()` allowlist excludes a few code/chat-surface tokens
(`--strong`, `--code-inline-bg`, `--pre-text`, `--input-bg`) and emits no
dark-mode variant, so on a mismatched base theme a custom theme's inline code and
code blocks would inherit the base-theme values and could render unreadable. To
cover that, the extension emits its own managed `<style>` (id
`hwxThemeCreatorBgStyles`) with code-surface tokens derived from each saved theme's
(and the live preview's) own palette alongside the glassmorphism CSS, under both `:root[data-skin]` and
`:root.dark[data-skin]`, so a custom theme composes cleanly in Light, Dark, and
System Default base modes. The block is refreshed on register/save/preview/delete.

## Dependency

Requires the core **theme-registration capability** (`window.registerHermesSkin`),
added in `nesquena/hermes-webui` **PR #5100**. Without it, the panel still opens
and you can design a theme, but a notice explains it can't be applied yet (the
extension does nothing destructive).

## Current Shape

```text
ARES page
  -> manifest-bundled extension assets
  -> /extensions/assets/theme-creator.js + .css
  -> rail button -> editor panel (color pickers + optional image upload + live preview)
  -> window.registerHermesSkin({...derived tokens...})  -> native Appearance picker
  -> managed <style> element: hwxThemeCreatorBgStyles (root background-image + semi-transparent vars + backdrop-filter blur)
  -> localStorage: hermes-ext-custom-themes (your saved themes)
                   hermes-skin (the core skin-selection key, to apply a theme)
```

This extension is `static-ui` / manifest-bundle only — no backend, no sidecar,
no network, no native host. Color processing is pure in-browser math.

## Capabilities

- `manifest-bundle`

## Install For Local Testing

```bash
cd /path/to/hermes-webui
HERMES_WEBUI_EXTENSION_DIR=/path/to/hermes-webui-extensions/extensions/theme-creator HERMES_WEBUI_EXTENSION_MANIFEST=manifest.json ./start.sh
```

Click the Theme Creator rail button, design a theme, Live preview, then Save. It
appears in Settings → Appearance.

## Controls

Also on `window.HermesThemeCreatorExtension`:

- `.themes()` — your saved themes
- `.open()` — open the editor
- `.registerAll()` — re-register saved themes into the picker

## Disable And Uninstall

Restart ARES without `HERMES_WEBUI_EXTENSION_DIR` /
`HERMES_WEBUI_EXTENSION_MANIFEST`, or remove the `extensions/theme-creator/`
directory. Your themes live under `hermes-ext-custom-themes`. If a custom theme
was the active skin, switch to another skin in Appearance (a removed skin falls
back to default).

## Trust And Permissions

This is trusted local code. Current disclosed behavior:

- creates extension-owned DOM (a rail button + the editor panel)
- calls `window.registerHermesSkin(...)` with derived, sanitized color tokens
- injects a single extension-managed `<style>` element:
  - `hwxThemeCreatorBgStyles` for all per-theme overrides (root background image,
    semi-transparent surface variables, code/chat token coverage, backdrop-filter blur) — uses validated
    base64 data URLs only
- reads/writes `localStorage`:
  - **owned:** `hermes-ext-custom-themes` (your saved themes; validated on read,
    capped at 50 themes / 2 MB)
  - **shared:** `hermes-skin` — the core skin-selection key, written to apply a
    theme (the same key the built-in Appearance picker uses)
- applies a theme through the core `window._pickSkin()` path when available, which
  commits the appearance change immediately — i.e. core **autosaves appearance via
  an authenticated `POST /api/settings`** as a side effect (disclosed as
  `webui_api.write: ["settings"]`). The extension itself issues no other HTTP calls.
- does NOT access cookies, contact any external network, or use the filesystem /
  native hosts
- all rendered text (theme names) is escaped; theme records are validated on read
  (key grammar + hex base colors); all colors are validated hex and re-sanitized by
  the core registration API

## Compatibility

- manifest-bundled extension assets + same-origin serving under `/extensions/`
- the left rail (`.rail`) to host the button
- the core theme-registration capability (`window.registerHermesSkin`, PR #5100)
- uses the core `_pickSkin()` to apply when available, falling back to setting
  `data-skin` + `hermes-skin` directly

## Verification

```bash
node scripts/validate-extensions.mjs
node scripts/scan-extension-safety.mjs
node scripts/generate-registry.mjs --out dist/registry.json
node --check extensions/theme-creator/assets/theme-creator.js
python3 -m json.tool extensions/theme-creator/extension.json
python3 -m json.tool extensions/theme-creator/manifest.json
```

Manual verification (on a WebUI build with PR #5100):

- the rail button opens the editor; color pickers + hex fields stay in sync
- Live preview applies the theme app-wide; Stop preview reverts
- Save registers the theme into Settings → Appearance and applies it
- saved themes can be applied / edited / deleted
- themes persist across a reload and re-register into the picker on load

## Known Limitations

- Requires the core theme-registration capability (PR #5100).
- Curated inputs with derived tokens (not every raw token is individually
  editable) — a deliberate usability trade-off.
- Themes are per-browser (`localStorage`), not synced across devices.
- Background images are stored as base64 JPEG data URLs (~70% quality,
  max 1920 px wide). Large or high-res images are compressed to fit, but
  images with many themes can push against the 2 MB `localStorage` ceiling.
  JPEG compression also flattens any transparency in the original file.
- Glassmorphism transparency (controlled by the **Glass opacity** slider) works best with
  bright or vibrant images. Very dark images may still look nearly opaque
  through the frosted-glass layer. Adjust opacity in the source if needed.
- The glassmorphism overrides target known WebUI panel class names
  (`.rail`, `.sidebar`, `.rightpanel`, `.main-view`). If the core WebUI
  changes these class names, the effect will break until the extension is
  updated. The `nav`/`main`/`aside` backdrop-filter and CSS variable
  overrides are version-independent.
- The brand logo glyph keeps its gold gradient (hardcoded in core; no skin
  recolors it).
