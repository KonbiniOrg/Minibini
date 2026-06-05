// Registers @testing-library/jest-dom matchers (toBeInTheDocument,
// toHaveAttribute, …) on expect, globally for every test file.
// Component cleanup between tests is handled automatically by the
// svelteTesting() plugin in vitest.config.js.
import '@testing-library/jest-dom';
import { afterEach } from 'vitest';

// localStorage / sessionStorage shim.
//
// Node 22+ ships an experimental WebStorage global that shadows jsdom's
// localStorage with a non-functional stub (`localStorage.getItem is not a
// function`). Rather than depend on Node/jsdom version quirks, install a small
// deterministic in-memory Storage so any code reading these at import time or
// at runtime (e.g. stores/viewMode.js, jobs/JobDetail.svelte's sessionStorage)
// behaves consistently. Cleared after each test for isolation.
class MemoryStorage {
  #map = new Map();
  get length() { return this.#map.size; }
  key(i) { return Array.from(this.#map.keys())[i] ?? null; }
  getItem(k) { return this.#map.has(k) ? this.#map.get(k) : null; }
  setItem(k, v) { this.#map.set(String(k), String(v)); }
  removeItem(k) { this.#map.delete(k); }
  clear() { this.#map.clear(); }
}

Object.defineProperty(globalThis, 'localStorage', {
  value: new MemoryStorage(), writable: true, configurable: true,
});
Object.defineProperty(globalThis, 'sessionStorage', {
  value: new MemoryStorage(), writable: true, configurable: true,
});

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
