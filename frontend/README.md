# Frontend

Svelte 5 SPA that consumes the Django REST API.

## Structure

```
frontend/
├── shared/          # Reusable components and API client (shared across all variants)
│   ├── lib/         # API client, utilities
│   ├── components/  # Shared Svelte components
│   └── stores/      # Shared state (if needed)
├── full/            # "Full" frontend variant
│   ├── src/         # App source (routes, layout, CSS)
│   ├── index.html   # Entry point
│   ├── package.json # Dependencies
│   └── vite.config.js
├── mobile/          # Future: mobile-optimized variant
└── lite/            # Future: lightweight variant
```

Each variant is its own Vite project with its own `package.json`. They import shared code from `../shared/` via a Vite alias (`$shared`).

## Prerequisites

- Node.js (v20+): `brew install node` on macOS, or download from https://nodejs.org

## Setup

```bash
cd frontend/full
npm install
```

## Development

Start the Vite dev server:

```bash
cd frontend/full
npx vite
```

This runs on http://localhost:9000 and proxies `/api/*` requests to Django on http://localhost:8000. You need Django running separately (`python manage.py runserver`).

## Build

```bash
cd frontend/full
npx vite build
```

Output goes to `frontend/full/dist/`. In production, nginx serves these files directly.

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

- The API client (`shared/lib/api.js`) checks `content-type` before parsing JSON to guard against HTML error pages from Django.
- Action errors (delete failures, validation errors) display in an overlay on top of the current page, preserving the content underneath.
- Load errors (page/object not found) replace the page content.
- Views catch `ProtectedError`, `ValidationError`, and `ServiceError` from services, returning user-friendly messages.

### CSS

- Global styles live in `frontend/full/src/css/app.css`, imported via `main.js`.
- No CSS frameworks. Semantic HTML with minimal global styles.
- Error overlays (`.error-overlay`) have a red border; success overlays (`.success-overlay`) have a green border. Both share the same layout pattern.

### Routing

- Hash-based routing (`#/path`). All internal links use the `#/` prefix.
- The `svelte-spa-router` library handles client-side navigation.

### Delete Flow

- First DELETE request (no `?confirm=true`) returns impact information and `confirm_required: true`.
- Frontend shows a confirmation prompt with the impact details.
- On confirm, the confirmation prompt is cleared immediately (returning the page to its normal state) and the confirmed DELETE is sent.
- On success, a success overlay displays the server's message. On error, an error overlay is shown.
