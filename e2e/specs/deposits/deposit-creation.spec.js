// docs/ui-flows/Deposits.md §1 — creating a deposit invoice line via the
// picker's "Add Deposit" affordance, and the DEPOSIT pill it earns on the
// invoices list. QBO is unreachable in e2e, so this covers only the
// draft-side creation UI — the seeded PAID deposit (deposit-credit.spec.js)
// covers the paid/claimed side.
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

test('§1 Creating a deposit line', async ({ page }) => {
  const job = await findInvoicelessJob(['approved', 'in_progress']);
  test.skip(!job, 'seed gap: no invoice-less billable job');

  await test.step('Start Invoice → Add Line Item → picker → Add Deposit', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await page.getByRole('button', { name: 'Add Line Item' }).click();
    const picker = page.getByRole('dialog', { name: 'Add line' });
    await expect(picker.getByRole('button', { name: 'Add Deposit' })).toBeEnabled();
    await picker.getByRole('button', { name: 'Add Deposit' }).click();
  });

  await test.step('Description prefills "Deposit on {job_number}"; amount 2500; Add', async () => {
    const form = page.getByRole('dialog').filter({ hasText: 'Add Deposit' });
    await expect(form.getByLabel('Description')).toHaveValue(`Deposit on ${job.job_number}`);
    await form.getByLabel('Amount').fill('2500');
    await form.getByRole('button', { name: 'Add' }).click();
    await expect(form).toBeHidden();
  });

  await test.step('The line renders with the deposit category and amount', async () => {
    const row = page.locator('tr', { hasText: `Deposit on ${job.job_number}` });
    await expect(row).toBeVisible();
    await expect(row).toContainText('Customer Deposits');
    await expect(row).toContainText('$2500.00');
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
