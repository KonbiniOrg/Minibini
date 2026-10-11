// Reply / Reply All open the composer as a modal over the email
// (2026-10-10; it used to render inline above the message). Sending is
// live SMTP — exempt, see change-orders/send-gate.spec.js — so this
// covers open, mode switch, and cancel.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

test('Reply opens the composer modal prefilled; Reply All retitles it; Cancel closes', async ({ page }) => {
  await page.goto('/#/email');
  await page.getByRole('link', { name: 'Re: Estimate 08008-1' }).click();
  const panel = page.getByRole('complementary');

  await panel.getByRole('button', { name: 'Reply', exact: true }).click();
  const reply = page.getByRole('dialog', { name: 'Reply' });
  await expect(reply).toBeVisible();
  await expect(reply.getByLabel('To *')).not.toHaveValue('');

  // The mode toggle lives inside the modal (the panel's buttons are behind
  // the overlay while composing).
  await reply.getByRole('button', { name: 'Reply All' }).click();
  await expect(page.getByRole('dialog', { name: 'Reply All' })).toBeVisible();

  await page.getByRole('dialog', { name: 'Reply All' }).getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
