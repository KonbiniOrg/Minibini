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

### Loaders called from `$effect` are write-only

Runes track *reads* transitively: an `$effect` subscribes to every piece of
`$state` read synchronously anywhere down its call stack, including inside
helper functions. So a loader that both reads and writes the same state
(`if (!task || …) { … } task = await api.get(…)`) turns the mount effect
into an infinite refetch loop — the effect re-runs every time the loader
lands (2026-07-06: TaskDetailPage refetched its whole fan-out 4-5×/second).

The rule, which the whole codebase already followed implicitly:

- A function invoked from an `$effect` may **write** `$state` freely but
  must **not synchronously read** `$state` that it (or anything the effect
  triggers) writes.
- Loader bookkeeping — "have I already loaded this?", last-loaded ids,
  in-flight guards — lives in **plain variables, not `$state`** (see
  `loadedTaskId` in `TaskDetailPage.svelte`), with a comment marking the
  non-reactivity as deliberate. Version-counter subscriptions (the
  `lastBlepVersion` pattern) keep their guard in `$state` only because the
  effect must re-check it; they never feed it back into a loader's reads.
- If a loader genuinely must branch on reactive state, wrap the read in
  `untrack()` — and treat needing that as a design smell first.

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

**The three display venues** (every message goes to exactly one; users
learn where to look):

1. **Under the input** — field validation errors. Place
   `<FieldError {errors} field="x" />` (components/) directly below each
   input; the label stays above. Set the bag (`errors = t.fields`) once in
   the catch; every slot lights up.
2. **Under the form's buttons** — operation errors ("Job is on hold"),
   `non_field_errors`, and the rare in-form success ack. Place
   `<FormMessage error={...} success={...} />` immediately after the
   button row. Conflict responses that carry a next step (`code` +
   machine payload, e.g. the referenced-scheme 409) render an action
   button in FormMessage's children — see RateSchemeManager for the
   pattern.
3. **The global red/green overlay** — everything with no form: failed row
   actions, infrastructure errors (backend down, 5xx), page-level success
   acknowledgements. Raise it with `showError(...)` / `showSuccess(...)`
   from `stores/messages.js`; `MessageOverlay.svelte` (mounted once in
   App.svelte) renders it. Pages never carry their own overlay markup.

**The uniform catch block** for forms:

```js
import { triageError } from '../lib/errorTriage.js';
import { showError } from '../stores/messages.js';

} catch (e) {
  const t = triageError(e);
  if (t.overlay) showError(t.overlay);      // infrastructure → venue 3
  else { formError = t.message; errors = t.fields; }  // venues 2 + 1
}
```

Clear `formError`/`errors` at submit start and on open/cancel.

- Never `JSON.stringify(e.data)`; never display bare `e.message`
  (field-keyed errors reduce it to "Request failed"); never
  `window.alert()` for API results (`confirm()` for irreversible deletes
  is fine). Branch on `err.status` / `err.data?.code` for flow decisions.
- Load errors (page/object not found on mount) are not "messages" — they
  replace the page content, per the existing convention.
- The exemplar conversion is `components/RateSchemeManager.svelte`; the
  primitives are `lib/errorTriage.js`, `components/FieldError.svelte`,
  `components/FormMessage.svelte`, `stores/messages.js`,
  `components/MessageOverlay.svelte`.

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

### Material status vocabulary

- `lib/materialStatus.js` derives **one display status per material row** from
  serializer fields (no backend state): **Needs pricing / Needed / Ordered —
  PO-NNNN / Awaiting customer / On Hand / Consumed / Released** (precedence in
  that file), plus a `costUnconfirmed` ⚠ when `cost_source === 'estimated'`.
- **Venue rule:** the job-overview pillar (`TaskTree`) shows these chips
  passively — **no actions**. All per-material actions (Set pricing / Order /
  Attach expense / Mark on-hand / Mark received / PO link) live on the task view
  page (`JobTaskListPage`), each gated on its callback being wired.
- Full vocabulary + backend contract: `docs/designs/materials-inventory-and-purchasing.md` §16.

### Delete Flow

- First DELETE request (no `?confirm=true`) returns impact information and `confirm_required: true`.
- Frontend shows a confirmation prompt with the impact details.
- On confirm, the confirmation prompt is cleared immediately (returning the page to its normal state) and the confirmed DELETE is sent.
- On success, a success overlay displays the server's message. On error, an error overlay is shown.
