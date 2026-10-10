// The Profile tab's password change is a modal behind a button
// (2026-10-10). A rejected change leaves the modal open; this never
// changes the persona's real password (later specs reuse its session and
// auth.setup logs it in again on the next run).
import { expect, test } from '@playwright/test';
import { E2E_PASSWORD, personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.worker.storageState });

test('Change password… opens the modal; a mismatched confirm is refused in place; Cancel closes', async ({ page }) => {
  await page.goto('/#/profile');
  await page.getByRole('button', { name: 'Change password…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Change password' });
  await expect(dialog).toBeVisible();

  await dialog.getByLabel('Current password').fill(E2E_PASSWORD);
  await dialog.getByLabel('New password', { exact: true }).fill('Mismatch-1');
  await dialog.getByLabel('Confirm new password').fill('Mismatch-2');
  await dialog.getByRole('button', { name: 'Change password' }).click();
  // Server refuses (confirm mismatch) — the modal stays, the password is unchanged.
  await expect(dialog).toBeVisible();

  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
