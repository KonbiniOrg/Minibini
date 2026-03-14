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

Flat structure with relative imports, no aliases. `components/` holds reusable pieces, `routes/` holds page-level wiring. Content density (full vs lite) is handled by a runtime view mode toggle, not separate builds. See `docs/plans/2026-03-13-view-mode-design.md`.

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

### Serializers

- Nested read-only serializers are used to include related object data in responses (e.g., `BusinessSerializer` includes a full `ContactSerializer` for `default_contact`).
- Use summary serializers (e.g., `BusinessSummarySerializer`) for nested objects that don't need full detail, to avoid excessive nesting depth.
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
