// docs/ui-flows/Invoice-Seeding-and-Send.md §1 — the billable-jobs gate on
// Start Invoice (2026-07-19: gated to approved-and-beyond, honest refusal
// wording on jobs still in quoting).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

let jobs;

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

// The empty state only renders on a job with no invoices at all.
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

test('§1 Start Invoice — the billable-jobs gate', async ({ page }) => {
  await test.step('Draft job: Start Invoice hidden, not-yet-billable hint shows', async () => {
    const job = await findInvoicelessJob(['draft']);
    test.skip(!job, 'seed gap: no invoice-less draft job');
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await expect(
      page.getByText('No invoices yet. Invoicing becomes available once the job is approved.')
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start Invoice' })).toHaveCount(0);
  });

  await test.step('Approved (billable) job: Start Invoice is offered', async () => {
    const job = await findInvoicelessJob(['approved', 'in_progress']);
    test.skip(!job, 'seed gap: no invoice-less billable job');
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await expect(page.getByRole('button', { name: 'Start Invoice' })).toBeVisible();
  });
});
