// Accounting Categories manager on Settings → Accounting: the delete guard.
// Unreferenced categories (mistakes/typos) get a Delete button; referenced
// ones don't — they retire via the Active checkbox instead. This spec
// creates its own throwaway category and deletes it, so it self-cleans and
// stays collision-free across reruns.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.configtime.storageState });

test('unreferenced category gets a Delete button; referenced does not', async ({ page }) => {
  const name = `e2e-delcat-${Date.now().toString(36)}`;
  const code = name.slice(-20).toUpperCase();

  await page.goto('/#/settings');
  await expect(page.getByRole('group', { name: 'Accounting Categories' })).toBeVisible();

  // A seeded, heavily-referenced category (estimate/invoice lines, fees,
  // rate schemes) must show no Delete button.
  const seededRow = page.locator('tr', { hasText: 'Service' }).first();
  await expect(seededRow).toBeVisible();
  await expect(seededRow.getByRole('button', { name: 'Delete' })).toHaveCount(0);
  await expect(seededRow.getByRole('button', { name: 'Edit' })).toBeVisible();

  // Create a throwaway, unreferenced category.
  await page.getByRole('button', { name: 'Add category' }).click();
  await page.getByLabel('Code *').fill(code);
  await page.getByLabel('Name *').fill(name);
  await page.getByRole('button', { name: 'Create' }).click();

  const row = page.locator('tr', { hasText: name });
  await expect(row).toBeVisible();
  await expect(row.getByRole('button', { name: 'Delete' })).toBeVisible();

  // Delete it — confirm() dialog, accept.
  page.once('dialog', (d) => {
    expect(d.message()).toContain(name);
    d.accept();
  });
  await row.getByRole('button', { name: 'Delete' }).click();

  await expect(page.locator('tr', { hasText: name })).toHaveCount(0);
  await expect(page.getByText(`Deleted "${name}"`)).toBeVisible();
});

test('cancelling the confirm dialog leaves the category in place', async ({ page }) => {
  const name = `e2e-delcat-cancel-${Date.now().toString(36)}`;
  const code = name.slice(-20).toUpperCase();

  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Add category' }).click();
  await page.getByLabel('Code *').fill(code);
  await page.getByLabel('Name *').fill(name);
  await page.getByRole('button', { name: 'Create' }).click();

  const row = page.locator('tr', { hasText: name });
  await expect(row).toBeVisible();

  page.once('dialog', (d) => d.dismiss());
  await row.getByRole('button', { name: 'Delete' }).click();
  await expect(row).toBeVisible();

  // Clean up for real, via the accept path, so the run stays collision-free.
  page.once('dialog', (d) => d.accept());
  await row.getByRole('button', { name: 'Delete' }).click();
  await expect(page.locator('tr', { hasText: name })).toHaveCount(0);
});
