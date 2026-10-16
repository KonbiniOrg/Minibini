// The shared Pager keeps Previous / Next in fixed positions: on page 1 Previous
// is present but disabled (not removed), so Next does not jump when the user
// moves to page 2. The e2e seed has well over 25 contacts + businesses.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.worker.storageState });

test('contacts list pager keeps Next in place between page 1 and page 2', async ({ page }) => {
  await page.goto('/#/contacts');
  await expect(page.locator('table.data-table tbody tr').first()).toBeVisible();

  const pager = page.locator('.pager');
  const prev = pager.getByRole('button', { name: 'Previous' });
  const next = pager.getByRole('button', { name: 'Next' });
  // Document (not viewport) coordinates: the click scrolls the pager into view.
  const pos = (loc) => loc.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + window.scrollX, y: r.top + window.scrollY };
  });

  await expect(prev).toBeDisabled();
  await expect(next).toBeEnabled();
  await expect(pager).toContainText(/Page 1 of \d+/);
  const before = await pos(next);

  await next.click();
  await expect(pager).toContainText(/Page 2 of \d+/);
  await expect(prev).toBeEnabled();
  const after = await pos(next);
  expect(after.x).toBe(before.x);
  expect(after.y).toBe(before.y);

  await prev.click();
  await expect(pager).toContainText(/Page 1 of \d+/);
  await expect(prev).toBeDisabled();
});
