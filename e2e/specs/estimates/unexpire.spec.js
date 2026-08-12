// docs/designs/estimates-and-prices.md §5.2b — EstimateService.unexpire.
// In-place reactivation: expired -> open on the SAME estimate, rejected ->
// submitted on the SAME job (no duplication). Gated on can_manage_jobs OR
// can_manage_financials — not the usual per-job PM scope.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-${Date.now().toString(36)}`;

// Build a job + estimate all the way to `expired` via the API, mirroring
// what the mark_estimates_expired sweep does to a lapsed live estimate.
// The flow under test is unexpiring, not authoring the estimate — so
// setup goes straight through the API (e2e-testing.md §2 layering rule).
async function expiredEstimate(api) {
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  const category = (cats.results || cats)[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} lapsed quote`, contact: contact.contact_id,
  });
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: 'One widget', qty_ordered: '1', units: 'each',
  });
  const est = await api.post('/api/estimates/', { job: job.job_id });
  await api.post(`/api/estimates/${est.estimate_id}/line-items/`, {
    description: 'Build widget', qty: '1', units: 'each', price: '250.00',
    accounting_category: category.id,
  });
  await api.patch(`/api/estimates/${est.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${est.estimate_id}/`, { status: 'expired' });
  return { job, estimateId: est.estimate_id };
}

test.describe('Unexpire — can_manage_jobs holder', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('reactivates the SAME estimate and job in place', async ({ page }) => {
    const api = await apiAs(personas.finjobs);
    const { job, estimateId } = await expiredEstimate(api);

    await test.step('The expired estimate offers Unexpire', async () => {
      await page.goto(`/#/jobs/${job.job_id}/estimate/${estimateId}`);
      await expect(page.locator('.toolbar .status-badge.status-expired')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Unexpire' })).toBeVisible();
    });

    await test.step('Clicking it flips the SAME estimate to open, in place', async () => {
      page.on('dialog', (d) => d.accept());
      await page.getByRole('button', { name: 'Unexpire' }).click();
      // Same URL throughout — no duplication, no navigation.
      await expect(page).toHaveURL(`http://localhost:9100/#/jobs/${job.job_id}/estimate/${estimateId}`);
      await expect(page.locator('select.status-open')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Unexpire' })).toHaveCount(0);
    });

    await test.step('The same job moved rejected -> submitted', async () => {
      const updatedJob = await api.get(`/api/jobs/${job.job_id}/`);
      expect(updatedJob.status).toBe('submitted');
      const updatedEst = await api.get(`/api/estimates/${estimateId}/`);
      expect(updatedEst.status).toBe('open');
      expect(updatedEst.closed_date).toBeNull();
    });

    await api.dispose();
  });
});

test.describe('Unexpire — neither atom', () => {
  test.use({ storageState: personas.worker.storageState });

  test('the button is hidden and the endpoint refuses', async ({ page }) => {
    const api = await apiAs(personas.finjobs); // seed setup needs a privileged actor
    const { job, estimateId } = await expiredEstimate(api);
    await api.dispose();

    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimateId}`);
    await expect(page.locator('.toolbar .status-badge.status-expired')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Unexpire' })).toHaveCount(0);

    const workerApi = await apiAs(personas.worker);
    const resp = await workerApi.postRaw(`/api/estimates/${estimateId}/unexpire/`);
    expect(resp.status()).toBe(403);
    await workerApi.dispose();
  });
});
