// Inter is the app font: body sets var(--font-sans) and everything inherits
// it (app.css). A component that names its own sans face silently opts out
// of Inter, so the only font-family values allowed in the source are the app
// font, inherit, and monospace stacks (code-like fields, board figures).
import { describe, it, expect } from 'vitest';

const sources = import.meta.glob('/src/**/*.{svelte,css}', {
  query: '?raw', import: 'default', eager: true,
});

const allowed = (value) =>
  value === 'var(--font-sans)' || value === 'inherit' || /\bmonospace\b/.test(value);

describe('app font', () => {
  it('scans the frontend source', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
  });

  it('no component overrides Inter with another sans face', () => {
    const offenders = [];
    for (const [path, text] of Object.entries(sources)) {
      for (const m of text.matchAll(/font-family:\s*([^;}]+)/g)) {
        const value = m[1].trim();
        if (!allowed(value)) offenders.push(`${path}: font-family: ${value}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
