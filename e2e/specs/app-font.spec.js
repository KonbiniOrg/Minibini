// Inter is the app font in both entry points: the SPA and the customer
// portal. Asserts the face actually loads and that text and form controls
// render in it (a component-level font-family would silently opt out).
import { expect, test } from '@playwright/test';
import { personas } from '../fixtures/personas.js';

const INTER = /^"?Inter Variable"?/;

async function interLoaded(page) {
  return page.evaluate(async () => {
    await document.fonts.ready;
    return [...document.fonts].some((f) => f.family.replace(/"/g, '') === 'Inter Variable' && f.status === 'loaded');
  });
}

const fontOf = (locator) => locator.evaluate((el) => getComputedStyle(el).fontFamily);

test.describe('app font', () => {
  test.describe('SPA', () => {
    test.use({ storageState: personas.worker.storageState });

    test('text and buttons render in Inter', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByRole('banner')).toBeVisible();
      expect(await interLoaded(page)).toBe(true);
      expect(await fontOf(page.locator('body'))).toMatch(INTER);
      expect(await fontOf(page.getByRole('button').first())).toMatch(INTER);
    });
  });

  test.describe('customer portal', () => {
    // No session: the portal is public. Unknown links still render the
    // portal wrappers (not-found states), which is all a font check needs.
    test('document wrapper renders in Inter', async ({ page }) => {
      await page.goto('/portal/?token=no-such-token&doc=estimate');
      const main = page.locator('main.portal');
      await expect(main).toBeVisible();
      expect(await interLoaded(page)).toBe(true);
      expect(await fontOf(main)).toMatch(INTER);
    });

    test('not-found dispatcher renders in Inter', async ({ page }) => {
      await page.goto('/portal/?doc=bogus');
      const main = page.locator('main.portal');
      await expect(main).toContainText('could not be found');
      expect(await fontOf(main)).toMatch(INTER);
    });
  });
});
