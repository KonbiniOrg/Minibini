import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'path';

export default defineConfig({
  plugins: [svelte()],
  // Module resolution is the single source of truth for dev, build, AND test:
  // vitest.config.js merges this file, so an alias added here applies everywhere
  // and can never diverge between `vite build` and the test runner.
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        portal: resolve(__dirname, 'portal/index.html'),
      },
    },
  },
  server: {
    // Env overrides exist for the E2E suite, which runs its own vite on 9100
    // proxying to its own Django on 8100 so the dev stack can stay up
    // (docs/designs/e2e-testing.md §4). Inert in normal dev use.
    port: Number(process.env.VITE_PORT || 9000),
    // 'minibini-vite' is the docker-compose container name; the Vite dev
    // server inside that container is what nginx proxies to in deploys.
    allowedHosts: ['moose', 'moose.local', 'minibini.me', 'minibini-vite'],
    proxy: {
      // 127.0.0.1, not localhost: Node 17+ resolves localhost dual-stack and
      // its happy-eyeballs race intermittently aborts proxy connects with a
      // fast AggregateError ETIMEDOUT against a healthy IPv4-only runserver.
      // In Docker, docker-compose.yml sets VITE_API_TARGET to the django
      // container (http://minibini-django:9000). This file is the ONLY vite
      // config — there are deliberately no per-environment copies, because a
      // copied config silently drifted (missing alias + portal entry) and
      // broke the image build.
      '/api': process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
    },
  },
});
