// docs/ui-flows/Deposits.md §1 — creating a deposit invoice via the
// invoice panel's "Add Deposit Invoice" / "Make this a deposit invoice"
// button + modal (Task 21, 2026-07 — replaces the picker's "Add Deposit"
// entry; refined 2026-07-26 into three states — no draft / draft with no
// lines / draft with lines), and the DEPOSIT pill it earns on the invoices
// list. QBO is unreachable in e2e, so this covers only the draft-side
// creation UI — the seeded PAID deposit (deposit-credit.spec.js) covers the
// paid/claimed side.
//
// This spec drives Start Invoice first (rather than the one-step "no draft"
// path, already covered by Vitest) specifically to exercise state 2's
// browser-only behavior: the relabel to "Make this a deposit invoice" once
// an empty draft exists, and the in-place reload (no hash navigation) when
// the deposit line lands on the draft already being viewed.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

let jobs;

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

// Same shape as the invoice-seeding-and-send specs: an invoice-less billable
// job. The seeded deposit job (08026) already carries INV-E2E-DEP-1, so it's
// naturally excluded here.
async function findInvoicelessJob(statuses) {
  const api = await apiAs(personas.finjobs);
  try {
    for (const job of jobs.filter((j) => statuses.includes(j.status) && !j.on_hold)) {
      const resp = await api.get(`/api/invoices/?job=${job.job_id}`);
      const list = resp?.results || resp || [];
      if (list.length === 0) return job;
    }
    return null;
  } finally {
    await api.dispose();
  }
}

test('§1 Creating a deposit invoice: states 1→2→3', async ({ page }) => {
  const job = await findInvoicelessJob(['approved', 'in_progress']);
  test.skip(!job, 'seed gap: no invoice-less billable job');

  await test.step('State 1 (no draft): Add Deposit Invoice is offered next to Start Invoice', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await expect(page.getByRole('button', { name: 'Start Invoice' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add Deposit Invoice' })).toBeEnabled();
  });

  await test.step('Start Invoice creates an empty draft', async () => {
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByText(/^Invoice: /)).toBeVisible();
  });

  await test.step('State 2 (draft, no lines): the action relabels to "Make this a deposit invoice"', async () => {
    await expect(page.getByRole('button', { name: 'Make this a deposit invoice' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Add Deposit Invoice' })).toHaveCount(0);
  });

  const hashBeforeCreate = () => new URL(page.url()).hash;
  let hashBefore;

  await test.step('Modal: enter amount 2500, Create', async () => {
    hashBefore = hashBeforeCreate();
    await page.getByRole('button', { name: 'Make this a deposit invoice' }).click();
    const modal = page.getByRole('dialog', { name: 'Add Deposit Invoice' });
    await expect(modal.getByRole('heading', { name: 'Add Deposit Invoice' })).toBeVisible();
    await modal.getByLabel('Amount').fill('2500');
    await modal.getByRole('button', { name: 'Create' }).click();
    await expect(modal).toBeHidden();
  });

  await test.step('The line appears in place — no navigation (same draft was already open)', async () => {
    expect(hashBeforeCreate()).toBe(hashBefore);
    const row = page.locator('tr', { hasText: `Deposit on ${job.job_number}` });
    await expect(row).toBeVisible();
    await expect(row).toContainText('Customer Deposits');
    await expect(row).toContainText('$2500.00');
  });

  await test.step('State 3 (draft has lines): the deposit action is suppressed entirely', async () => {
    await expect(page.getByRole('button', { name: 'Make this a deposit invoice' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Add Deposit Invoice' })).toHaveCount(0);
  });

  await test.step('The invoices list shows the DEPOSIT pill', async () => {
    await page.goto('/#/invoices');
    await page.getByLabel('Status:').selectOption('draft');
    const listRow = page.locator('tr', {
      has: page.getByRole('link', { name: job.job_number, exact: true }),
    });
    await expect(listRow.locator('.deposit-pill')).toHaveText('DEPOSIT');
  });

  await test.step('Cleanup: discard the draft', async () => {
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
  });
});
