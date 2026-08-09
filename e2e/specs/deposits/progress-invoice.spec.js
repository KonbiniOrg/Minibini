// Spec §7.2 deposit-path relabel (better-fees) — once a job carries a live
// invoice (any status but cancelled), the advance-money action reads "Add
// Progress Invoice" instead of "Add Deposit Invoice": same gesture, same
// unseeded draft + deposit-rail line, words only. And the resulting
// all-deposit draft withholds the agreement machinery — no "Uncovered work"
// pool, no "Add from agreement…" (RM 2026-08-09: advance money bills against
// the job as a whole, never against atoms).
//
// Uses seeded job 08026 (fixtures/playwright/seed.json), which carries the
// PAID deposit invoice INV-E2E-DEP-1 — a live invoice with no open draft —
// the exact precondition for the progress relabel (same seed job as
// deposit-credit.spec.js; workers:1 keeps their draft lifecycles serial).
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

test('§7.2 progress invoice: relabel on a live-invoiced job, unseeded all-deposit draft withholds agreement offerings', async ({ page }) => {
  test.skip(!job, 'seed gap: no seeded deposit job (job_number 08026)');

  await test.step('A job with a live invoice offers "Add Progress Invoice" (not "Add Deposit Invoice")', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await expect(page.getByRole('button', { name: 'Add Progress Invoice' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Add Deposit Invoice' })).toHaveCount(0);
  });

  await test.step('Modal: progress heading, amount 1000, Create navigates to the new draft', async () => {
    await page.getByRole('button', { name: 'Add Progress Invoice' }).click();
    const modal = page.getByRole('dialog', { name: 'Add Progress Invoice' });
    await expect(modal.getByRole('heading', { name: 'Add Progress Invoice' })).toBeVisible();
    await modal.getByLabel('Amount').fill('1000');
    await modal.getByRole('button', { name: 'Create' }).click();
    await expect(modal).toBeHidden();
  });

  await test.step('The draft carries one deposit-rail line with the progress-billing description', async () => {
    const row = page.locator('tr', { hasText: `Progress billing on ${job.job_number}` })
      .filter({ has: page.locator('.backing-chip') });
    await expect(row).toBeVisible();
    await expect(row.locator('.backing-chip')).toHaveText('deposit');
    await expect(row).toContainText('$1000.00');
  });

  await test.step('The all-deposit draft withholds Uncovered work and Add from agreement', async () => {
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Uncovered work' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Add from agreement/ })).toHaveCount(0);
  });

  await test.step('Cleanup: discard the draft', async () => {
    await discardDraft();
  });
});
