import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 9000,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
