// Where a login and a logout put you. Two different intents share one screen
// (App.svelte swaps LoginPage in over whatever page you were on), so the hash
// is what tells them apart: a deliberate logout clears it to '/', a session
// expiry leaves it naming the page you were interrupted on.
//
// These specs log in through the form instead of using a persona's saved
// storageState: logging out deletes that session server-side, which would
// leave e2e/.auth/worker.json pointing at a dead session for every later spec
// in the run. Each test burns only the session it created.
import { expect, test } from '@playwright/test';
import { E2E_PASSWORD, personas } from '../../fixtures/personas.js';

async function logIn(page) {
  await page.getByLabel('Username').fill(personas.worker.username);
  await page.getByLabel('Password').fill(E2E_PASSWORD);
  await page.getByRole('button', { name: 'Log In' }).click();
  // The app header (shift strip) only renders once authenticated.
  await expect(page.getByRole('banner')).toBeVisible();
}

test.describe('login / logout landing', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('logging out from a page leaves the browser at home', async ({ page }) => {
    await page.goto('/');
    await logIn(page);
    await page.evaluate(() => { window.location.hash = '/jobs/board'; });
    await expect(page.locator('.board')).toBeVisible();

    // The sidebar is a pull-out that animates on hover — physical hover is
    // unreliable here, so drive the handler directly (same trick as
    // setup-status.spec.js).
    await page.locator('.sidebar').dispatchEvent('mouseenter');
    await page.getByRole('button', { name: 'Logout' }).click();

    await expect(page.getByRole('heading', { name: 'Log In' })).toBeVisible();
    await expect(page).toHaveURL(/#\/$/);
  });

  test('an expired session returns to the page it interrupted', async ({ page, context }) => {
    await page.goto('/');
    await logIn(page);
    await page.evaluate(() => { window.location.hash = '/jobs/board'; });
    await expect(page.locator('.board')).toBeVisible();

    // Drop only the session cookie: a real expiry leaves csrftoken alone (its
    // lifetime is independent), and the login POST needs that token.
    const kept = (await context.cookies()).filter((c) => c.name !== 'sessionid');
    await context.clearCookies();
    await context.addCookies(kept);

    // Expiry surfaces on the next authenticated fetch — an in-app navigation
    // triggers one (App.svelte refreshes the bands on every route change).
    // The jobs list never loads under the dead session, which makes the
    // assertion after logging back in unambiguous.
    await page.evaluate(() => { window.location.hash = '/jobs'; });
    await expect(page.getByText('Your session expired')).toBeVisible();
    await expect(page).toHaveURL(/#\/jobs$/);

    await logIn(page);

    // Landed on the jobs list rather than Home, and its heading carries the
    // count — which only exists once the page has fetched for itself.
    await expect(page).toHaveURL(/#\/jobs$/);
    await expect(page.getByRole('heading', { name: /^Jobs \(\d+\)$/ })).toBeVisible();
  });
});
