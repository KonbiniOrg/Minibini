// docs/ui-flows/Production-Lifecycle.md §11 — Approval & the status pill
// (2026-07-19 batch: value-controlled pill display, direct-approval gating
// on has_estimates, in-place header refresh on estimate acceptance).
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

// The job header's status pill — the only select inside the dark header band.
const pill = (page) => page.locator('.job-header select');

async function jobDetail(jobId) {
  const api = await apiAs(personas.finjobs);
  const detail = await api.get(`/api/jobs/${jobId}/`);
  await api.dispose();
  return detail;
}

test('§11 Approval & the status pill', async ({ page }) => {
  await test.step('Submitted job WITH an estimate: no direct Approved', async () => {
    const hit = await findJobWithEstimate(jobs, {
      jobStatus: 'submitted', estimateStatus: 'open', used,
    });
    test.skip(!hit, 'seed gap: no submitted job with an open estimate');
    await page.goto(`/#/jobs/${hit.job.job_id}`);
    await expect(pill(page)).toBeVisible();
    // Rejected is offered (proves the option list rendered)…
    await expect(pill(page).locator('option', { hasText: 'Rejected' })).toHaveCount(1);
    // …but Approved is not: approval flows from accepting the estimate.
    await expect(pill(page).locator('option', { hasText: 'Approved' })).toHaveCount(0);
  });

  // API-side setup: every seed job carries at least one estimate, so the
  // estimate-less shape is created here — the flow under test IS this job's
  // own status walk (e2e-testing.md §2 layering rule).
  let jobId;
  await test.step('Estimate-less submitted job: Approved is offered and works', async () => {
    const api = await apiAs(personas.finjobs);
    const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
    const created = await api.post('/api/jobs/', {
      name: `${stamp} pill walk`, contact: contact.contact_id,
    });
    jobId = created.job_id;
    await api.patch(`/api/jobs/${jobId}/`, { status: 'submitted' });
    await api.dispose();

    await page.goto(`/#/jobs/${jobId}`);
    await expect(pill(page).locator('option', { hasText: 'Approved' })).toHaveCount(1);
    await pill(page).selectOption({ label: 'Approved' });
    await expect.poll(async () => (await jobDetail(jobId)).status).toBe('approved');
    await expect(pill(page).locator('option:checked')).toHaveText('Approved');
  });

  await test.step('Release to floor: one gesture → In Progress, displayed truthfully', async () => {
    // On an approved job the pill names the act, not the resulting status.
    await expect(pill(page).locator('option', { hasText: 'Release to floor' })).toHaveCount(1);
    await pill(page).selectOption({ label: 'Release to floor' });
    await expect.poll(async () => (await jobDetail(jobId)).status).toBe('in_progress');
    // The pill DISPLAYS the real status — the selected-index regression
    // showed the option at the clicked index ("Work Complete") instead.
    await expect(pill(page)).toHaveValue('in_progress');
    await expect(pill(page).locator('option:checked')).toHaveText('In Progress');
  });
  // §11's in-flight disable is a millisecond window — covered by the
  // JobHeader unit tests (frontend/tests/components/jobs/JobHeader.test.js),
  // not raced here.
});

test('§11 Estimate acceptance refreshes the job header in place', async ({ page }) => {
  const hit = await findJobWithEstimate(jobs, {
    jobStatus: 'submitted', estimateStatus: 'open', used,
  });
  test.skip(!hit, 'seed gap: no submitted job with an open estimate');
  const { job, estimate } = hit;

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
  await expect(pill(page)).toHaveValue('submitted');

  // Accept via the ESTIMATE's own status pill (the document toolbar select).
  // No reload after this point — the assertion is that the page refreshes
  // its own job header.
  await page.locator('.toolbar select').selectOption('accepted');

  // Acceptance drives the job to approved; the header above updates in place.
  await expect(pill(page)).toHaveValue('approved');
  await expect(pill(page).locator('option:checked')).toHaveText('Approved');
  // The estimate's pill is now a terminal badge reading accepted.
  await expect(page.locator('.toolbar .status-badge')).toHaveText('accepted');
});
