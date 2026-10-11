// Email workspace against the seeded mailbox (fixtures added 2026-07-23:
// one thread per job lifecycle state, with replies to emailed estimates and
// invoices, plus one unlinked vendor invoice).
//
// Covers the Bill removal's retained breadcrumb: a vendor-invoice email is
// linked to its Purchase Order (the flow that replaced link-to-bill).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

// finjobs: can_manage_financials (email→PO actions) + can_manage_jobs.
test.use({ storageState: personas.finjobs.storageState });

test('inbox lists the seeded lifecycle emails', async ({ page }) => {
  await page.goto('/#/email');
  await expect(page.getByRole('heading', { name: /Inbox/ })).toBeVisible();
  // One thread per lifecycle state, newest first; spot-check across states.
  await expect(
    page.getByRole('link', { name: /Quote request — 18 separate letters/ })
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Re: Estimate 08008-1' })
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Re: Invoice 10337 for 08023' })
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: /Invoice MNH-20441/ })
  ).toBeVisible();
});

test('estimate reply is linked to its job', async ({ page }) => {
  await page.goto('/#/email');
  const row = page.getByRole('row', { name: /Re: Estimate 08008-1/ });
  await expect(row.getByRole('link', { name: '08008', exact: true })).toBeVisible();
});

test('vendor invoice email links to its PO (the bill-removal breadcrumb)', async ({ page }) => {
  // Open the unlinked vendor email from the inbox.
  await page.goto('/#/email');
  await page.getByRole('link', { name: /Invoice MNH-20441/ }).click();

  // No PO linked yet — the action panel offers Link existing (a button
  // that opens EmailLinkModal over the email, 2026-10-10).
  const panel = page.getByRole('complementary');
  const poSection = panel.locator('section', { has: page.getByRole('heading', { name: 'Purchase Order' }) });
  await expect(poSection).toBeVisible();
  await poSection.getByRole('button', { name: 'Link existing' }).click();

  // Link modal: pick PO0001 (Moore Newton Hardwoods) and submit.
  const dialog = page.getByRole('dialog', { name: 'Link to purchase order' });
  await expect(dialog).toBeVisible();
  await dialog.getByPlaceholder('Search purchase order…').fill('PO0001');
  await dialog.getByText(/PO0001 — Moore Newton Hardwoods/).click();
  await dialog.getByRole('button', { name: 'Link to purchase order' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);

  // Still on the detail page, the panel shows the linked PO.
  await expect(panel.getByRole('link', { name: /PO0001/ })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Disassociate' })).toBeVisible();

  // And the email is unlinked again so reruns within one seeded session
  // start from the seed state.
  await panel.getByRole('button', { name: 'Disassociate' }).click();
  await expect(poSection.getByRole('button', { name: 'Link existing' })).toBeVisible();
});
