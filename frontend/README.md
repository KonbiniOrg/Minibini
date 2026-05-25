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

## Design Decisions

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

- The API client (`src/lib/api.js`) checks `content-type` before parsing JSON to guard against HTML error pages from Django.
- Action errors (delete failures, validation errors) display in an overlay on top of the current page, preserving the content underneath.
- Load errors (page/object not found) replace the page content.
- Views catch `ProtectedError`, `ValidationError`, and `ServiceError` from services, returning user-friendly messages.

### CSS

- Global styles live in `frontend/src/css/app.css`, imported via `main.js`.
- No CSS frameworks. Semantic HTML with minimal global styles.
- Error overlays (`.error-overlay`) have a red border; success overlays (`.success-overlay`) have a green border. Both share the same layout pattern.
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
