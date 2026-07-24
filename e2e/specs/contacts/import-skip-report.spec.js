// Contacts QBO import against the seeded snapshot (no live QBO needed —
// panels render from Configuration['qbo_import_snapshot']): a clean
// customer imports, a duplicate-email customer is skipped and reported,
// and the skipped row stays importable.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

test('partial commit imports the clean row and reports the skipped one', async ({ page }) => {
  await page.goto('/#/contacts');
  const panel = page.locator('.qbo-panel');
  await expect(panel.getByRole('heading',
    { name: 'Customers & vendors from QuickBooks' })).toBeVisible();
  await expect(panel.getByText('Zenith Imports E2E')).toBeVisible();
  await expect(panel.getByText('Dupmail Company E2E')).toBeVisible();

  await panel.getByRole('button', { name: 'Apply selected' }).click();

  // The skip report names the row and the conflict.
  await expect(panel.getByText("1 contact couldn't be imported:")).toBeVisible();
  await expect(panel.getByText(/Dupmail Company E2E: duplicate email with/))
    .toBeVisible();

  // The clean customer is now a konbini business (the list is paginated
  // alphabetically — jump to Z via the letter index).
  await page.getByRole('button', { name: 'Z', exact: true }).click();
  // The combined list links the business from both its own row and its
  // contact's row — either proves the import landed.
  await expect(page.getByRole('link', { name: 'Zenith Imports E2E' }).first())
    .toBeVisible();

  // Panel state after reload: imported row locked, skipped row still
  // checked and importable.
  const zenithRow = panel.locator('tr', { hasText: 'Zenith Imports E2E' });
  await expect(zenithRow.getByRole('checkbox')).toBeDisabled();
  const dupRow = panel.locator('tr', { hasText: 'Dupmail Company E2E' });
  await expect(dupRow.getByRole('checkbox')).toBeEnabled();
  await expect(dupRow.getByRole('checkbox')).toBeChecked();
});
