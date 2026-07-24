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

  // No PO linked yet — the action panel offers Link existing.
  const panel = page.getByRole('complementary');
  await expect(panel.getByRole('heading', { name: 'Purchase Order' })).toBeVisible();
  await panel.locator('a[href$="/associate-po"]', { hasText: 'Link existing' }).click();

  // Associate page: pick PO0001 (Moore Newton Hardwoods) and submit.
  await expect(
    page.getByRole('heading', { name: 'Select Purchase Order' })
  ).toBeVisible();
  await page.getByPlaceholder('Search purchase order…').fill('PO0001');
  await page.getByText(/PO0001 — Moore Newton Hardwoods/).click();
  await page.getByRole('button', { name: 'Associate Email with PO' }).click();

  // Back on the detail page, the panel shows the linked PO.
  await expect(panel.getByRole('link', { name: /PO0001/ })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Disassociate' })).toBeVisible();

  // And the email is unlinked again so reruns within one seeded session
  // start from the seed state.
  await panel.getByRole('button', { name: 'Disassociate' }).click();
  await expect(panel.locator('a[href$="/associate-po"]', { hasText: 'Link existing' })).toBeVisible();
});
