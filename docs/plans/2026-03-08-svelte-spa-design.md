# Svelte SPA Frontend Design

## Overview

Add a Svelte 5 single-page application frontend that consumes the existing Django REST API. Initial scope: Contacts and Businesses only, with structure designed to support multiple frontend variants (full, mobile, lite) sharing common code.

## Decisions

- **Framework:** Svelte 5 + Vite (standalone, no SvelteKit)
- **Router:** svelte-spa-router (lightweight client-side routing)
- **Auth:** Session-based (same as current Django setup), no JWT
- **Dev setup:** Vite dev server on :5173, proxies `/api/*` to Django on :8000
- **Production:** nginx serves SPA static files directly; Django only handles `/api/*`
- **Styling:** Separate CSS directory, decoupled from components, empty/minimal to start
- **Data flow:** Direct fetch calls via thin API wrapper, no state management library
- **SPA base path:** `/app/` (avoids collision with existing Django views and `/api/`)

## Project Structure

```
frontend/
├── shared/
│   ├── lib/
│   │   └── api.js              # Fetch wrapper (CSRF, error handling, pagination)
│   ├── stores/                 # Shared state (if needed later)
│   └── components/
│       └── contacts/
│           ├── ContactList.svelte
│           ├── ContactDetail.svelte
│           ├── ContactForm.svelte
│           ├── BusinessList.svelte
│           ├── BusinessDetail.svelte
│           └── BusinessForm.svelte
│
├── full/                       # "Full" frontend variant
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── src/
│   │   ├── main.js
│   │   ├── App.svelte          # Root: nav + router outlet
│   │   ├── css/
│   │   │   └── app.css
│   │   ├── routes/
│   │   │   ├── Home.svelte
│   │   │   └── contacts/      # Route wiring, composes shared components
│   │   └── components/
│   │       └── Nav.svelte
│
├── mobile/                     # Future: same shape, different layout + CSS
└── lite/                       # Future: same shape, minimal feature set
```

Each frontend variant is its own Vite project with its own `package.json`, importing from `../shared/` via a Vite alias (`$shared`).

## Django Integration

### Development
- Run Vite dev server from `frontend/full/` (port 5173)
- Vite proxies `/api/*` to Django on port 8000
- Session auth works because browser sees single origin (localhost:5173)
- `AutoLoginMiddleware` continues to work

### Production
- `vite build` outputs to `frontend/full/dist/`
- nginx serves SPA files and handles client-side routing:
  ```nginx
  location /app/ {
      try_files $uri /app/index.html;
  }
  location /api/ {
      proxy_pass http://django;
  }
  ```
- Django never sees frontend requests; focused purely on API
- No CORS configuration needed (same origin)

## API Client (`shared/lib/api.js`)

Thin wrapper around `fetch`:
- `api.get(url)`, `api.post(url, data)`, `api.patch(url, data)`, `api.delete(url)`
- Reads `csrftoken` cookie, sends as `X-CSRFToken` header on mutating requests
- Returns parsed JSON
- Throws on 4xx/5xx with status and message
- Handles paginated responses (`{count, next, previous, results}`)

## URL Scheme

| URL | Component | Notes |
|---|---|---|
| `/app` | Home | Landing page |
| `/app/contacts` | ContactList | Paginated list |
| `/app/contacts/new` | ContactForm | Create mode |
| `/app/contacts/:id` | ContactDetail | View with edit/delete |
| `/app/contacts/:id/edit` | ContactForm | Edit mode |
| `/app/businesses` | BusinessList | Paginated list |
| `/app/businesses/new` | BusinessForm | Create mode |
| `/app/businesses/:id` | BusinessDetail | View with edit/delete |
| `/app/businesses/:id/edit` | BusinessForm | Edit mode |

## Contacts Feature Scope

### Contacts
- List (paginated, searchable)
- Detail view (with linked business, phone numbers)
- Create / edit form
- Delete with impact confirmation (API already supports this)

### Businesses
- List (paginated)
- Detail view (with linked contacts, payment terms)
- Create / edit form
- Set default contact (existing API action)

### PaymentTerms
- Read-only (used as dropdown in business forms)

## What This Design Does NOT Include

- Styling decisions (deferred, CSS directory is ready)
- Global state management (start without, add if needed)
- Mobile or lite variants (structure is ready, build later)
- Any other sections beyond Contacts (expand after patterns are established)
- JWT or token-based auth
- SSR or SvelteKit
