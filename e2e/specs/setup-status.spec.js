// Gradual-setup gates against the seeded DB. The e2e environment has no
// email credentials, so the Email gate genuinely fails here — giving this
// spec a live greyed-entry + callout to assert. Everything else is set up.
// The QBO pull flows are backend+Vitest territory (no QBO connection).
import { expect, test } from '@playwright/test';
import { apiAs } from '../fixtures/api.js';
import { personas } from '../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

test('setup status: only email is unavailable on the seeded DB', async ({ page }) => {
  const resp = await page.request.get('/api/setup/status/');
  expect(resp.ok()).toBeTruthy();
  const data = await resp.json();
  for (const [area, state] of Object.entries(data.areas)) {
    if (area === 'email') {
      expect(state.available).toBe(false);
      expect(state.message).toContain('Settings');
    } else {
      expect(state.available, `area ${area}`).toBe(true);
      expect(state.message).toBe('');
    }
  }
});

test('sidebar greys exactly the email entry, with its callout on hover', async ({ page }) => {
  await page.goto('/');
  // The sidebar is a pull-out that animates on hover — physical hover
  // fights Playwright's stability check, so dispatch the event directly.
  await page.locator('.sidebar').dispatchEvent('mouseenter');
  const nav = page.getByRole('navigation');
  for (const label of ['Jobs', 'Purchasing', 'Catalog']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible();
  }
  const emailEntry = nav.locator('.nav-disabled', { hasText: 'Email' });
  await expect(emailEntry).toBeVisible();
  await expect(nav.locator('.nav-disabled')).toHaveCount(1);
  await emailEntry.dispatchEvent('mouseenter');
  await expect(page.getByRole('tooltip')).toContainText('email service');
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
