// QBO import pulls Active=false: a business that is active in konbini but
// inactive in QBO shows as a "deactivate" suggestion (unchecked by default).
// Applying it flips the business locally; Reactivate reverses it. The seed
// snapshot's "Dormant Customer E2E" row matches seed business
// "Minor Catastrophe Productions" (pk 154, qbo_customer_id "e2e-inactive-1").
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

test('inactive QBO customer suggests deactivate, applies, and reactivates', async ({ page }) => {
  await page.goto('/#/contacts');
  const panel = page.locator('.qbo-panel');
  const row = panel.locator('tr', { hasText: 'Dormant Customer E2E' });
  await expect(row).toBeVisible();
  await expect(row.getByText('deactivate', { exact: true })).toBeVisible();
  await expect(row.getByRole('checkbox')).not.toBeChecked();

  await row.getByRole('checkbox').check();
  await panel.getByRole('button', { name: 'Apply selected' }).click();

  await page.goto(`/#/search?q=${encodeURIComponent('Minor Catastrophe')}`);
  await page.getByRole('link', { name: 'Minor Catastrophe Productions' }).first().click();
  await expect(page.locator('.customer-header').getByText('inactive')).toBeVisible();

  await page.getByRole('button', { name: 'Reactivate' }).click();
  await expect(page.locator('.customer-header').getByText('inactive')).toHaveCount(0);
});
