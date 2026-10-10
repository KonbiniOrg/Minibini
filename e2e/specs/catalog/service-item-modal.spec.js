// Service item create/edit is a modal over the catalog list (2026-10-10,
// closing LATER.md "Service Item edit should be a modal" — matches
// RateSchemeManager, its sibling manager).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

test('Add Service Item → modal → Save lands the row; Edit reopens it', async ({ page }) => {
  await page.goto('/#/catalog/service-items');
  await page.getByRole('button', { name: 'Add Service Item' }).click();
  const dialog = page.getByRole('dialog', { name: 'New service item' });
  await expect(dialog).toBeVisible();
  const name = `${stamp} modal item`;
  await dialog.getByLabel('Name *').fill(name);
  await dialog.getByLabel('Rate Scheme').selectOption({ label: 'CAD (elapsed_time)' }); // required server-side
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const row = page.getByRole('row', { name: new RegExp(name) });
  await expect(row).toBeVisible();

  await row.getByRole('button', { name: 'Edit' }).click();
  const edit = page.getByRole('dialog', { name: 'Edit service item' });
  await expect(edit.getByLabel('Name *')).toHaveValue(name);
  await edit.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
