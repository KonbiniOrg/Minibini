// Per-checkout isolation so several checkouts can run e2e side by side
// (docs/designs/e2e-testing.md §4).
//   MINIBINI_SLOT unset  → the shared defaults: minibini_e2e on 8100/9100.
//   MINIBINI_SLOT=1..9   → minibini_e2e_s<N> on 81N0 (Django) / 91N0 (vite).
const raw = process.env.MINIBINI_SLOT || '';
if (raw && !/^[1-9]$/.test(raw)) {
  throw new Error(`MINIBINI_SLOT must be a single digit 1-9, got "${raw}"`);
}

export const slot = raw ? Number(raw) : 0;
export const dbName = slot ? `minibini_e2e_s${slot}` : 'minibini_e2e';
export const djangoPort = 8100 + slot * 10;
export const vitePort = 9100 + slot * 10;
export const baseURL = `http://localhost:${vitePort}`;
