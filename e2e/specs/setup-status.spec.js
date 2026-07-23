// Gradual-setup gates against the seeded DB, which is fully set up
// (including fake mail credentials seeded precisely so the Email area is
// reachable for the email specs). Greyed-entry/callout rendering is
// covered by Vitest against mocked gate states; the QBO pull flows are
// backend+Vitest territory (no QBO connection here).
import { expect, test } from '@playwright/test';
import { apiAs } from '../fixtures/api.js';
import { personas } from '../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

test('setup status: every area available on the seeded DB', async ({ page }) => {
  const resp = await page.request.get('/api/setup/status/');
  expect(resp.ok()).toBeTruthy();
  const data = await resp.json();
  for (const [area, state] of Object.entries(data.areas)) {
    expect(state.available, `area ${area}`).toBe(true);
    expect(state.message).toBe('');
  }
});

test('sidebar renders every entry as a live link (nothing greyed)', async ({ page }) => {
  await page.goto('/');
  // The sidebar is a pull-out that animates on hover — physical hover
  // fights Playwright's stability check, so dispatch the event directly.
  await page.locator('.sidebar').dispatchEvent('mouseenter');
  const nav = page.getByRole('navigation');
  for (const label of ['Jobs', 'Email', 'Purchasing', 'Catalog']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible();
  }
  await expect(nav.locator('.nav-disabled')).toHaveCount(0);
});

test('import pull reports the missing QBO connection gracefully', async () => {
  const api = await apiAs(personas.finjobs);
  try {
    const resp = await api.postRaw('/api/qbo/import/pull/', { area: 'contacts' });
    expect(resp.status()).toBe(400);
    expect((await resp.json()).detail).toBe('No active QBO connection.');
  } finally {
    await api.dispose();
  }
});
