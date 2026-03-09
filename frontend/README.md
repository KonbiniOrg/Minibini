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
