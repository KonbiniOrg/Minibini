# Frontend

Svelte 5 SPA that consumes the Django REST API.

## Structure

```
frontend/
├── src/
│   ├── lib/              # API client, utilities
│   ├── stores/           # Shared state (viewMode, etc.)
│   ├── components/       # Reusable components
│   ├── routes/           # Page-level components (routing, wiring)
│   ├── css/              # Global styles
│   ├── App.svelte        # Root: nav + router outlet
│   └── main.js           # Entry point
├── index.html
├── package.json
└── vite.config.js
```

Flat structure with relative imports, no aliases. `components/` holds reusable pieces, `routes/` holds page-level wiring. Content density (full vs lite) is handled by a runtime view mode toggle, not separate builds. See `docs/designs/architecture-and-conventions.md` §6 (View mode).

## Prerequisites

- Node.js (v20+): `brew install node` on macOS, or download from https://nodejs.org

## Setup

```bash
cd frontend
npm install
```

## Development

Start the Vite dev server:

```bash
cd frontend
npx vite
```

This runs on http://localhost:9000 and proxies `/api/*` requests to Django on http://localhost:8000. You need Django running separately (`python manage.py runserver`), or use `./dev.sh` from the project root to start both.

## Build

```bash
cd frontend
npx vite build
```

Output goes to `frontend/dist/`. In production, nginx serves these files directly.

## Front-end testing

Component and unit tests use [Vitest](https://vitest.dev/) with
[@testing-library/svelte](https://testing-library.com/docs/svelte-testing-library/intro/).

### Setup

The test tooling is declared in `package.json` as devDependencies, so a normal
install picks it up — no separate install step:

```bash
npm install
```

### Running tests

```bash
npm test         # watch mode — re-runs on change; use this during development
npm run test:run # one-shot run — use for CI / a quick full pass
```

### Where tests live

All tests live under `frontend/tests/`, mirroring the `src/` tree:

- `tests/lib/<name>.test.js`        — pure module / function tests
- `tests/components/<Name>.test.js` — Svelte component tests

Import source with the `@` alias (e.g. `import { linkify } from '@/lib/linkify.js'`).
Config lives in `vitest.config.js`, separate from `vite.config.js` so the
production build is unaffected.

For how to write tests (patterns, the behavior-vs-display triage, conventions,
the jsdom storage shim), see `docs/designs/frontend-testing.md`.

## Design Decisions

### Modals

Every form modal rides the shared shell, `src/components/Modal.svelte`. The
shell owns everything cross-cutting so it can't drift per-modal:

- **Geometry:** one place on screen — horizontally centered, anchored
  `--modal-top` (50px) from the top — so a modal handing off to another
  (picker → form) never moves on the user. `maxWidth` is the single sanctioned
  size knob. Every modal is draggable by its grab bar (position resets on each
  open) to peek at the page behind.
- **Keyboard contract:**
  - Every modal passes `onCancel` — **Escape always closes**. A modal with an
    internal sub-state (confirm-delete, a nested prompt) passes a smarter
    `onCancel` that backs out one level before closing.
  - **Enter** is decided by one question: *is the content a native `<form>`?*
    If yes, the form owns Enter (native submit + `required` validation) and
    you omit `onSave` — binding both would double-fire. If no (button-driven
    content), pass `onSave`. Deliberately Esc-only modals (an ambiguous
    primary action, e.g. `StartWorkConflictModal`'s join-vs-takeover) omit
    `onSave` **with a comment saying why**.
  - Pass the modal's in-flight flag as `busy` — the shell suppresses Enter
    while it's true (the busy-guard lives once, in the shell), so a
    double-Enter during a slow save can never fire the API twice. The Save
    *button* still wants its own `disabled={busy}` for the click path.
- **Not on the shell (deliberate):** `TaskQuickCard` — a positioned popup
  card with backdrop-click close, not a form modal.

New modals: prefer native-`<form>` content where the modal is genuinely a
form (free `required` validation, one submit path); wrap it in `<Modal>` and
wire only `onCancel`. As of 2026-07-04 **every** form modal in the app is a
native form (`<form onsubmit>` + `type="submit"` save button, all other
buttons `type="button"` — the HTML default inside a form is submit, so an
untyped Cancel would save); the shell's `onSave`/`busy` path remains for
future button-driven modals with an unambiguous primary action.

### API Responses

- All API responses return JSON with a 200 status, even for operations like DELETE that normally have no meaningful data to return. No 204 responses. An empty response is `{}`.
- Error responses return JSON with a `detail` field and an appropriate 4xx status code.
- Successful delete responses may return a `message` field with a human-readable confirmation (e.g., `{"message": "\"Acme Corp\" has been deleted. 2 contact(s) were disassociated."}`).

### Serializer Tiers

Each model has up to three serializer tiers, used in different contexts:

| Tier | Naming | Used when | Example fields |
|---|---|---|---|
| **Summary** | `FooSummarySerializer` | Nested inside other objects as supporting data | id, name, status |
| **Standard** | `FooSerializer` | List views, create, update | All own fields + summary-level nested objects |
| **Detail** | `FooDetailSerializer` | Retrieve (detail view) — the object is the main focus | All standard fields + related object lists |

The ViewSet switches serializers based on the action:

```python
def get_serializer_class(self):
    if self.action == 'retrieve':
        return FooDetailSerializer
    return FooSerializer
```

Key rules:
- **Detail serializers** include related object lists (e.g., `BusinessDetailSerializer` includes contacts and jobs). These use summary serializers for the nested objects to avoid deep nesting.
- **Standard serializers** include key FKs as nested summary objects for display (e.g., `ContactSerializer` includes `BusinessSummarySerializer` for the contact's business) but not reverse relation lists.
- **Summary serializers** include only what's needed to identify and link to the object (id, name/title, maybe status).
- Write-only `PrimaryKeyRelatedField` fields (e.g., `business_id`) are added alongside read-only nested serializers to accept foreign key IDs on create/update.

### Error Handling

The API error contract (two body shapes, status semantics, the central
backend handler) is documented in
`docs/designs/architecture-and-conventions.md` §3.9 — read that first.
Frontend rules:

- The API client (`src/lib/api.js`) attaches `.status` and `.data` to every
  thrown error; `.data` is `null` when the body wasn't JSON (HTML error
  pages still carry `.status`).
- Read error text ONLY via the two sanctioned readers: `errorMessage(err)`
  (`lib/api.js`) for a single display string, `fieldErrors(bag, field)`
  (`lib/formErrors.js`) for inline per-field lists (set the bag from
  `err.data` when it's an object). Never `JSON.stringify(e.data)`; never
  display bare `e.message` (field-keyed errors reduce it to "Request
  failed"). Branch on `err.status` for flow decisions (e.g. `=== 409`).
- Action errors (delete failures, validation errors) display in an overlay
  on top of the current page, preserving the content underneath.
- Load errors (page/object not found) replace the page content.

### CSS

- Global styles live in `frontend/src/css/app.css`, imported via `main.js`.
- No CSS frameworks. Semantic HTML with minimal global styles.
- Error overlays (`.error-overlay`) have a red border; success overlays (`.success-overlay`) have a green border. Both share the same layout pattern.
- **z-index scale:** cross-component stacking uses named tokens defined on
  `:root` in `app.css` — `--z-sticky` (100) < `--z-dropdown` (200) <
  `--z-popover` (400) < `--z-sidebar` (600) < `--z-modal` (800) <
  `--z-modal-nested` (900, a modal opened from within a popover/modal) <
  `--z-toast` (1000, the global feedback overlay, always on top). Use
  `z-index: var(--z-modal)` etc. rather than bare numbers. Self-contained local
  stacks (the schedule lane stack; the JobHeader / hold-reason popover) keep
  their own small values and are intentionally off this global ladder.
- **Tables:** don't use the `border="1"` attribute (the light grey cell border
  comes from the global `table, th, td` rule). For a table full of data, opt into
  the house style with `class="data-table"` — full-width, padded cells, a teal
  header band, and a subtle grey zebra stripe. The stripe is defined with
  `:where(.data-table)` (zero specificity) so a table's own row classes (e.g.
  `.subtask-row`) override it without a fight; components may add scoped styles to
  tweak any `.data-table`. Tables that aren't tabular data (layout, key-value
  one-offs) and intentionally bespoke tables keep their own styling — `.data-table`
  is opt-in, not a global default. Scope is the Svelte SPA only; Django HTML
  templates follow their own table conventions (see root `CLAUDE.md`).

### Routing

- Hash-based routing (`#/path`). All internal links use the `#/` prefix.
- The `svelte-spa-router` library handles client-side navigation.

### View Mode (Full / Lite)

- A `viewMode` Svelte store (`'full'` or `'lite'`) controls content density at runtime.
- Defaults to `'lite'`, persisted in `localStorage`. (Server-side user preference planned.)
- Components use a `<FullOnly>` wrapper to hide sections in lite mode — avoids scattering `$viewMode` checks throughout components.
- Lite mode still fetches full data; hidden sections can be expanded inline without extra API calls.
- Responsive layout (mobile, kiosk) is handled separately via CSS media queries, independent of view mode.

### Delete Flow

- First DELETE request (no `?confirm=true`) returns impact information and `confirm_required: true`.
- Frontend shows a confirmation prompt with the impact details.
- On confirm, the confirmation prompt is cleared immediately (returning the page to its normal state) and the confirmed DELETE is sent.
- On success, a success overlay displays the server's message. On error, an error overlay is shown.
