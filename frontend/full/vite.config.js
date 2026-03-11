import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'path';

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    alias: {
      '$shared': path.resolve(__dirname, '../shared'),
    },
  },
  server: {
    port: 9000,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
