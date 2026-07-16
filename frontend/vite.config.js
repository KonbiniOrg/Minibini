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
    allowedHosts: ['moose', 'moose.local', 'minibini.me'],
    proxy: {
      '/api': process.env.VITE_API_TARGET || 'http://localhost:8000',
    },
  },
});
