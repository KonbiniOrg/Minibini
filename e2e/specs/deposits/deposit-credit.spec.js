// docs/ui-flows/Deposits.md §2-3 — a paid, unclaimed deposit's DEP PAID
// banner on the board, the draft panel's "Unapplied deposit credit" notice
// (Task 22), pulling its credit into a follow-up invoice as a negative
// "Less deposit" line (which also clears the notice), and the claim
// lifecycle (the banner clears while the claiming draft is live; discarding
// the draft releases it). QBO is unreachable in e2e, so the PAID deposit
// invoice (INV-E2E-DEP-1, on seeded job 08026) is seeded directly
// (fixtures/playwright/seed.json) — send/pay are not driven here. The
// send-time unapplied-deposit-credit confirm (also Task 22) is likewise not
// e2e-reachable — sending requires a real QBO push, unavailable in this
// env — and is covered by Vitest only
// (frontend/tests/routes/invoices/InvoiceSendPage.test.js).
//
// UPDATED for the better-fees skeleton phase (Task 13 retired the old
// Reconcile-wizard toggle): the invoice document now has ONE merged Edit
// view (line-items table + "Uncovered work" pool + a dedicated "Deposit
// credits" section) instead of a separate lines view / Reconcile wizard —
// no "Reconcile"/"Back to lines" toggle to drive, and pulling a deposit
// credit is a direct one-click "Apply to this invoice" button (no
// checkbox + "Add Here"). See frontend/src/components/invoices/
// InvoiceEditView.svelte's deposit-credits-section.
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

// The deposit credit row in the Edit view's "Deposit credits" section
// (InvoiceEditView.svelte) — only rendered while the credit is still
// unclaimed ('available'); once claimed it disappears from here entirely
// and shows up as a "Less deposit" line in the main table instead.
function depositCreditRow(page) {
  return page.locator('.deposit-credits-section tr').filter({ hasText: 'Deposit credit — INV-E2E-DEP-1' });
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

  await test.step('Start a second invoice: the new draft shows the "Unapplied deposit credit" notice', async () => {
    // The job already carries the seeded paid deposit invoice, so the panel
    // lands on it (not the empty "no invoices yet" state) — a second invoice
    // is started via the subnav's "+ New invoice" trailing action.
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: '+ New invoice' }).click();
    await expect(page.getByText(/Unapplied deposit credit .* INV-E2E-DEP-1/)).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();
  });

  await test.step('The Edit view shows a "Deposit credits" section with the credit row', async () => {
    await expect(page.getByRole('heading', { name: 'Deposit credits' })).toBeVisible();
    const row = depositCreditRow(page);
    await expect(row).toContainText('Deposit on 08026');
    // The pool amount is already the deduction VALUE (negative) — same
    // number the resulting "Less deposit" line below will carry.
    await expect(row).toContainText('$-5000.00');
  });

  await test.step('Pulling it ("Apply to this invoice") creates a negative "Less deposit" line', async () => {
    await depositCreditRow(page).getByRole('button', { name: 'Apply to this invoice' }).click();
    // Claimed — the atom is no longer 'available', so it drops out of the
    // Deposit credits section (InvoiceEditView filters that section to
    // state === 'available'); the section itself disappears once it was
    // the only credit on the job.
    await expect(depositCreditRow(page)).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Deposit credits' })).toHaveCount(0);

    // Scoped to the row carrying a BackingChip — the parent line row, not
    // its own nested AtomChildRow underneath (same description substring,
    // no chip) — so the locator stays a strict-mode-safe single match.
    const row = page.locator('tr', { hasText: 'Less deposit (INV-E2E-DEP-1)' })
      .filter({ has: page.locator('.backing-chip') });
    await expect(row).toBeVisible();
    await expect(row).toContainText('$-5000.00');
    // Its BackingChip reads the dedicated deposit-credit classification.
    await expect(row.locator('.backing-chip')).toHaveText('deposit credit');
    // Now applied — the notice from the earlier step is gone.
    await expect(page.getByText(/Unapplied deposit credit/)).toHaveCount(0);
  });

  await test.step('Reloading still shows the credit as claimed (persisted, not local-only)', async () => {
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Deposit credits' })).toHaveCount(0);
    const row = page.locator('tr', { hasText: 'Less deposit (INV-E2E-DEP-1)' })
      .filter({ has: page.locator('.backing-chip') });
    await expect(row).toBeVisible();
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
