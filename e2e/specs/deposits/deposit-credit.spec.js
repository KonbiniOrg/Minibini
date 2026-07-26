// docs/ui-flows/Deposits.md §2-3 — a paid, unclaimed deposit's DEP PAID
// banner on the board, pulling its credit into a follow-up invoice as a
// negative "Less deposit" line, and the claim lifecycle (the banner clears
// while the claiming draft is live; discarding the draft releases it). QBO
// is unreachable in e2e, so the PAID deposit invoice (INV-E2E-DEP-1, on
// seeded job 08026) is seeded directly (fixtures/playwright/seed.json) —
// send/pay are not driven here.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

let job;

test.beforeAll(async () => {
  const jobs = await loadBackdrop();
  job = jobs.find((j) => j.job_number === '08026');
});

// The seeded chip for this job, matched on its exact job-number text (not a
// substring) so it can't collide with another job's number.
function jobChip(page) {
  return page.locator('.job-chip').filter({ has: page.getByText(job.job_number, { exact: true }) });
}

// The deposit credit row in the reconcile pool, in either its selectable
// ("available", a <label>) or claimed ("claimed_by_current", a <span>) state
// — WizardAtomRow renders one or the other, but both carry this text.
function depositCreditRow(page) {
  return page.locator('label, span').filter({ hasText: 'Deposit credit — INV-E2E-DEP-1' });
}

async function discardDraft() {
  const api = await apiAs(personas.finjobs);
  try {
    const resp = await api.get(`/api/invoices/?job=${job.job_id}`);
    const list = resp?.results || resp || [];
    for (const inv of list.filter((i) => i.status === 'draft')) {
      await api.del(`/api/invoices/${inv.invoice_id}/?confirm=true`);
    }
  } finally {
    await api.dispose();
  }
}

test('§2-3 Deposit credit: board banner, pulling the credit, claim lifecycle', async ({ page }) => {
  test.skip(!job, 'seed gap: no seeded deposit job (job_number 08026)');

  await test.step('Board: the paid, unclaimed deposit shows DEP PAID on hover', async () => {
    await page.goto('/#/jobs/board');
    const chip = jobChip(page);
    await expect(chip).toBeVisible();
    await chip.hover();
    const popup = page.locator('.chip-popup');
    await expect(popup.locator('.deposit-banner')).toHaveText('DEP PAID');
  });

  await test.step('Start a second invoice and open Reconcile', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    // The job already carries the seeded paid deposit invoice, so the panel
    // lands on it (not the empty "no invoices yet" state) — a second invoice
    // is started via the subnav's "+ New invoice" trailing action.
    await page.getByRole('button', { name: '+ New invoice' }).click();
    await page.getByRole('button', { name: 'Reconcile' }).click();
    await expect(page.getByRole('heading', { name: 'Tasks and Materials' })).toBeVisible();
  });

  await test.step('Reconcile shows a "Deposit credits" group with the credit row', async () => {
    await expect(page.getByText('Deposit credits', { exact: true })).toBeVisible();
    const row = depositCreditRow(page);
    await expect(row).toContainText('[deposit]');
    await expect(row).toContainText('$5,000.00 credit');
  });

  await test.step('Pulling it (Add Here) creates a negative "Less deposit" line', async () => {
    await depositCreditRow(page).locator('input[type="checkbox"]').check();
    await page.getByRole('button', { name: 'Add Here' }).click();
    await page.getByRole('button', { name: 'Back to lines' }).click();
    const row = page.locator('tr', { hasText: 'Less deposit (INV-E2E-DEP-1)' });
    await expect(row).toBeVisible();
    await expect(row).toContainText('$-5000.00');
  });

  // Re-opening the pool is a fresh mount (loadAll() re-fetches source-pool
  // from the server), which is what makes this deterministic — the group's
  // has_billable_atoms only recomputes server-side. With the sole deposit
  // credit now claimed, the group collapses to its "no billable items" empty
  // state (apps/invoicing/services.py get_source_pool) rather than rendering
  // a distinct "claimed" row — that's how the shipped UI represents "the
  // credit shows as claimed" here (nothing left available to add).
  await test.step('Re-opening the pool shows the credit as claimed (nothing left to add)', async () => {
    await page.getByRole('button', { name: 'Reconcile' }).click();
    await expect(page.getByText('Deposit credits (no billable items)')).toBeVisible();
  });

  await test.step('While claimed by this live draft, the board DEP PAID banner clears', async () => {
    await page.goto('/#/jobs/board');
    const chip = jobChip(page);
    await chip.hover();
    const popup = page.locator('.chip-popup');
    await expect(popup.locator('.job-card')).toBeVisible();
    await expect(popup.locator('.deposit-banner')).toHaveCount(0);
  });

  await test.step('Cleanup: discard the draft — DEP PAID returns (claim released)', async () => {
    await discardDraft();

    // Already on the board's hash route from the previous step — goto() to
    // the identical URL is a no-op in a hash router, so force a real reload
    // to re-fetch /api/jobs/board/approved/ with the claim released.
    await page.reload();
    const chip = jobChip(page);
    await chip.hover();
    const popup = page.locator('.chip-popup');
    await expect(popup.locator('.deposit-banner')).toHaveText('DEP PAID');
  });
});
