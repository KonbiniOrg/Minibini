// QBO-primary invoicing (2026-07-21): QBO assigns invoice numbers at push,
// so a fresh draft has no number — it displays the placeholder identity
// "Draft — {job_number}" everywhere an invoice number would show. The
// push/send itself is not e2e-reachable (no QBO connection in this env);
// this spec covers the draft-side UI only.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

let jobs;

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

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

test('a fresh draft invoice shows the Draft placeholder, not a number', async ({ page }) => {
  const job = await findInvoicelessJob(['approved', 'in_progress']);
  test.skip(!job, 'seed gap: no invoice-less billable job');

  await page.goto(`/#/jobs/${job.job_id}/invoice`);
  await page.getByRole('button', { name: 'Start Invoice' }).click();

  // The panel titles the draft with its placeholder identity.
  await expect(
    page.getByText(`Invoice: Draft — ${job.job_number}`)
  ).toBeVisible();

  // Clean up: discard the draft so the seed stays invoice-less for reruns.
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
