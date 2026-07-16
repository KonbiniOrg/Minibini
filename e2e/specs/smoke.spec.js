// Platform smoke test: proves the seeded DB, both webServers, and the saved
// persona sessions work together.
import { expect, test } from '@playwright/test';
import { personas } from '../fixtures/personas.js';

test.describe('platform smoke', () => {
  test.use({ storageState: personas.worker.storageState });

  test('worker persona is logged in against the seeded stack', async ({ page }) => {
    // The saved session works at the API level (page.request shares cookies).
    const me = await page.request.get('/api/auth/me/');
    expect(me.ok()).toBeTruthy();
    expect((await me.json()).username).toBe(personas.worker.username);

    // …and at the page level: straight to the app, no login form.
    await page.goto('/');
    await expect(page.getByRole('banner')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Log In' })).toHaveCount(0);
  });
});
