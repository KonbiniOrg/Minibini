import { mergeConfig, defineConfig } from 'vitest/config';
import { svelteTesting } from '@testing-library/svelte/vite';
import viteConfig from './vite.config.js';

// Test config = production vite config + test-only layers. By merging
// vite.config.js we inherit `resolve.alias` (and the svelte plugin) from the
// single source of truth, so module resolution can never diverge between
// `vite build` and the test runner. Only genuinely test-specific settings
// (jsdom, setup files, the testing plugin, include globs) live here.
export default mergeConfig(
  viteConfig,
  defineConfig({
    plugins: [svelteTesting()],
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./tests/setup.js'],
      include: ['tests/**/*.{test,spec}.js'],
    },
  }),
);
