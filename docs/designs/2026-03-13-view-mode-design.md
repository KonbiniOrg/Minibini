# View Mode Design

Supersedes the multi-variant project structure from the SPA design doc (2026-03-08). Instead of separate Vite projects per variant (full/, lite/, mobile/), there is one Vite project with a runtime view mode toggle.

## Two Independent Axes

**Content density** (view mode) — what to show:
- **Lite**: essentials only. Collapsed sections with "show more" links to expand inline. Default for new users.
- **Full**: everything visible upfront. All related data, history, secondary fields.

**Layout/styling** (responsive) — how to lay it out:
- Handled by CSS media queries. Same HTML, different layout per screen size.
- Kiosk or mobile-specific stylesheets can be added later without changing components.

These compose independently. A mobile user in full mode sees all the data, laid out for a small screen.

## Implementation

### Store

`frontend/src/stores/viewMode.js` — a Svelte writable store.

- Reads from `localStorage` on init, defaults to `'lite'`
- Subscribes to changes, writes back to `localStorage`
- Exports `viewMode` (store) and `toggleViewMode()` (function)
- Later: replace localStorage with a user preference fetched from the API on load

### FullOnly Component

`frontend/src/components/FullOnly.svelte` — a wrapper that renders its children only in full mode.

```svelte
<script>
  import { viewMode } from '../stores/viewMode.js';
  const { children } = $props();
</script>

{#if $viewMode === 'full'}
  {@render children()}
{/if}
```

Components wrap full-mode-only sections in `<FullOnly>` instead of checking `$viewMode` directly. This keeps mode logic out of business components.

### Nav Toggle

A link in the nav: "Switch to full" / "Switch to lite". The `<h1>` shows the current mode: "Minibini (lite)" or "Minibini (full)".

### Component Pattern

Lite mode shows a summary with expand links. Full mode shows everything. Example for a business detail:

```svelte
<dl>
  <!-- Always visible -->
  <dt>Name</dt>
  <dd>{business.business_name}</dd>
  <dt>Phone</dt>
  <dd>{business.business_phone}</dd>
  <dt>Default Contact</dt>
  <dd>...</dd>

  <!-- Full mode only -->
  <FullOnly>
    <dt>Address</dt>
    <dd>{business.business_address}</dd>
    <dt>Tax Info</dt>
    <dd>...</dd>
  </FullOnly>
</dl>
```

In lite mode, hidden data is still fetched (same API calls). Expanding inline via "show more" links uses local component state, no extra requests.

## Project Structure (Updated)

```
frontend/
├── src/
│   ├── lib/              # API client, utilities
│   │   └── api.js
│   ├── stores/           # Shared state
│   │   └── viewMode.js
│   ├── components/       # Reusable components
│   │   ├── FullOnly.svelte
│   │   └── contacts/
│   │       └── ...
│   ├── routes/           # Page-level components (routing, wiring)
│   │   └── contacts/
│   │       └── ...
│   ├── css/
│   │   └── app.css
│   ├── App.svelte
│   └── main.js
├── index.html
├── package.json
└── vite.config.js
```

Flat structure — no aliases, just relative imports. `components/` holds reusable pieces, `routes/` holds page-level wiring.

## Future

- User preference stored server-side (User model or Configuration), fetched on app load
- Additional modes possible (e.g., `'kiosk'`) by extending the store and adding corresponding wrapper components
- CSS media queries for responsive layout, independent of view mode
