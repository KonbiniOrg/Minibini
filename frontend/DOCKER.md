# Frontend Docker Integration

Notes for the release engineer on integrating the SPA frontend into the Docker deployment.

## What Needs to Happen

The SPA is a static site after building. Vite compiles Svelte components into plain HTML/CSS/JS in `frontend/dist/`. Nginx serves these files and proxies API requests to Django.

## Build Step

The frontend needs a Node.js build step that produces static files:

```bash
cd frontend
npm ci                # Install exact versions from package-lock.json
npx vite build        # Output: frontend/dist/
```

This can be a multi-stage Docker build or a separate build container. The output is:

```
frontend/dist/
├── index.html
└── assets/
    ├── index-XXXX.js
    └── index-XXXX.css
```

## Nginx Configuration

The SPA needs two nginx rules:

1. Serve static SPA files for `/app/*` routes
2. Handle client-side routing (return `index.html` for unknown paths under `/app/`)

```nginx
# SPA static files
location /app/ {
    alias /path/to/frontend/dist/;
    try_files $uri /app/index.html;
}

# API proxy (existing)
location /api/ {
    proxy_pass http://django;
}
```

`try_files` is the key part — it makes client-side routing work. When a user navigates to `/app/contacts/123`, nginx serves `index.html` and the Svelte router handles the URL.

## Docker Image Options

**Option A: Multi-stage build in existing Dockerfile**

```dockerfile
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ /app/frontend/
RUN npx vite build

# Stage 2: Nginx (copy built files in)
FROM nginx:alpine
COPY --from=frontend-build /app/frontend/dist/ /usr/share/nginx/html/app/
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

**Option B: Separate build step, copy into nginx volume**

Build the frontend outside Docker and mount `dist/` into the nginx container. Simpler if the build pipeline already handles this.

## Dependencies

- `node:20-alpine` (or newer) for the build step — only needed at build time, not runtime
- No Node.js needed in the final nginx or Django containers
- `npm ci` (not `npm install`) for reproducible builds from `package-lock.json`

## Environment Considerations

- The SPA makes API calls to `/api/*` — same origin, no CORS needed
- Session authentication works because nginx serves both the SPA and proxies the API
- No environment variables needed in the frontend build (API URL is always relative `/api/`)
