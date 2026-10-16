// View-mode column seam on the Contacts & Businesses list (DataTable): with no
// lite-content decisions made yet, both densities show the same six columns,
// and flipping the sidebar toggle re-renders in place without a refetch flash
// (docs/plans/2026-10-08-view-mode-seams.md §4.3).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.worker.storageState });

const ALL = ['Name', 'Type', 'Business', 'Email', 'Phone', 'Tags'];

test.beforeEach(async ({ page }) => {
  // Pin density to lite regardless of what the saved session carries.
  await page.addInitScript(() => localStorage.setItem('minibini_view_mode', 'lite'));
});

test('density toggle keeps the contacts list columns and rows', async ({ page }) => {
  await page.goto('/#/contacts');
  const table = page.locator('table.data-table');
  await expect(table).toBeVisible();

  await test.step('Lite: all six headers, at least one row', async () => {
    await expect(table.getByRole('columnheader')).toHaveText(ALL);
    await expect(table.locator('tbody tr').first()).toBeVisible();
  });

  await test.step('Toggle FULL in the sidebar → same headers, rows still there', async () => {
    // The sidebar is a pull-out that animates on hover — dispatch the event
    // directly (same approach as specs/setup-status.spec.js).
    await page.locator('.sidebar').dispatchEvent('mouseenter');
    await page.getByRole('button', { name: 'FULL' }).click();
    await expect(page.locator('body')).toHaveAttribute('data-view-mode', 'full');
    await expect(table.getByRole('columnheader')).toHaveText(ALL);
    await expect(table.locator('tbody tr').first()).toBeVisible();
  });

  await test.step('Toggle LITE → unchanged', async () => {
    await page.locator('.sidebar').dispatchEvent('mouseenter');
    await page.getByRole('button', { name: 'LITE' }).click();
    await expect(page.locator('body')).toHaveAttribute('data-view-mode', 'lite');
    await expect(table.getByRole('columnheader')).toHaveText(ALL);
  });
});
