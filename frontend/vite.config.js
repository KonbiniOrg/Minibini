import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'path';

export default defineConfig({
  plugins: [svelte()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        portal: resolve(__dirname, 'portal/index.html'),
      },
    },
  },
  server: {
    port: 9000,
    allowedHosts: ['moose', 'moose.local'],
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
