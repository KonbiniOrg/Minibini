// docs/ui-flows/Change-Orders.md §1 (enter the CO room — Create Change Order
// gating) and §2 (the CO page as a job-workspace panel: JobShell chrome,
// full-code subnav, diff grids, inline deliverable add). Post-extraction
// regression coverage for the 2026-07-19 JobShell-panel move.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { findJobWithEstimate, loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;
let jobs;
const used = new Set();

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

async function jobDetail(jobId) {
  const api = await apiAs(personas.finjobs);
  const detail = await api.get(`/api/jobs/${jobId}/`);
  await api.dispose();
  return detail;
}

test('§1 Enter the CO room — Create Change Order gating', async ({ page }) => {
  const hit = await findJobWithEstimate(jobs, {
    jobStatus: 'in_progress', estimateStatus: 'accepted', used,
  });
  test.skip(!hit, 'seed gap: no in_progress job with an accepted estimate');
  const { job, estimate } = hit;

  await test.step('Create Change Order is offered on the accepted estimate (no COs yet)', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await expect(page.getByRole('button', { name: 'Create Change Order' })).toBeVisible();
  });

  await test.step('Guard: creation is refused while the job is not on hold', async () => {
    const api = await apiAs(personas.finjobs);
    const resp = await api.postRaw('/api/change-orders/', { job: job.job_id });
    expect(resp.status()).toBe(400);
    expect(await resp.text()).toContain('on hold');
    await api.dispose();
  });

  await test.step('Hold the job; Create Change Order lands in the CO room', async () => {
    await page.goto(`/#/jobs/${job.job_id}`);
    await page.getByRole('combobox').first().selectOption('__hold');
    await page.getByLabel('Reason for hold').fill('e2e: opening the CO room');
    await page.getByRole('button', { name: 'Confirm Hold' }).click();
    await expect.poll(async () => (await jobDetail(job.job_id)).on_hold).toBe(true);

    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await page.getByRole('button', { name: 'Create Change Order' }).click();
    await page.waitForURL(new RegExp(`#/jobs/${job.job_id}/change-order/\\d+$`));
    // The CO page titles itself with the full CO number.
    await expect(page.getByText(`${estimate.estimate_number}-CO1`).first()).toBeVisible();
  });

  await test.step('Create Change Order is gone once the job has a change order', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await page.reload(); // same-fragment goto doesn't renavigate a hash router
    await expect(page.getByText(`Estimate: ${estimate.estimate_number}`)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create Change Order' })).toHaveCount(0);
  });
});

test('§2 The CO page — JobShell chrome, full-code subnav, diff grids, inline deliverable add', async ({ page }) => {
  // Own job + CO via API: this test is about the CO *page*, not the entry
  // flow (§1 above owns that), so setup goes through fixtures/api.js.
  const hit = await findJobWithEstimate(jobs, {
    jobStatus: 'in_progress', estimateStatus: 'accepted', used,
  });
  test.skip(!hit, 'seed gap: no second in_progress job with an accepted estimate');
  const { job, estimate } = hit;
  const api = await apiAs(personas.finjobs);
  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: 'e2e: CO panel smoke' });
  const co = await api.post('/api/change-orders/', { job: job.job_id });
  await api.dispose();

  await page.goto(`/#/jobs/${job.job_id}/change-order/${co.change_order_id}`);

  await test.step('JobShell chrome renders around the CO document', async () => {
    await expect(
      page.getByRole('heading', { level: 1, name: new RegExp(`JOB #.*${job.job_number.replace(/^JOB-/, '')}`) })
    ).toBeVisible();
    await expect(page.getByRole('button', { name: /job context/i })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Job sections' })).toBeVisible();
  });

  await test.step('Subnav pills carry the full document codes', async () => {
    const subnav = page.getByRole('navigation', { name: 'Documents' });
    // Estimates read {estimate_number}-{version}, not a bare v2.
    await expect(subnav.locator('.doc-subnav-link', {
      hasText: `${estimate.estimate_number}-${estimate.version}`,
    }).first()).toBeVisible();
    await expect(subnav.locator('.doc-subnav-link', {
      hasText: co.change_order_number,
    })).toBeVisible();
  });

  await test.step('Both diff grids render', async () => {
    await expect(page.getByRole('heading', { name: 'Deliverables' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Line items' })).toBeVisible();
    await expect(page.locator('table.diff-table')).toHaveCount(2);
  });

  await test.step('+ New deliverable → fill → Add lands a green added row', async () => {
    await page.getByRole('button', { name: '+ New deliverable' }).click();
    const editRow = page.locator('tr.row-editing');
    await editRow.locator('input').first().fill('2'); // qty
    await editRow.getByPlaceholder('Description').fill(`${stamp} extra bracket`);
    await editRow.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.locator('tr.row-added')).toContainText(`${stamp} extra bracket`);
  });
});
