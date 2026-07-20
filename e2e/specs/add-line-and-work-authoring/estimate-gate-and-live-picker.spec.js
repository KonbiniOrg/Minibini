// docs/ui-flows/Add-Line-and-Work-Authoring.md §1 (Start the estimate —
// the quoting-phase gate) and §3 (Add Work — the live cross-window picker).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { findJob, loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

test('§1 Start the estimate — the quoting-phase gate', async ({ page }) => {
  // The gate needs a job that advanced past quoting with no estimate ever —
  // a shape the seed lacks (every seed job has one), so it's built here via
  // the hand-approval path this same batch legitimized.
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} quoting gate`, contact: contact.contact_id,
  });

  await test.step('Quoting-phase job with no estimate: Start Estimate is offered', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate`);
    await expect(page.getByRole('button', { name: 'Start Estimate' })).toBeVisible();
    await expect(page.getByText('past the estimating phase')).toHaveCount(0);
  });

  await test.step('Past quoting (hand-approved, estimate-less): button hidden, hint shows', async () => {
    await api.patch(`/api/jobs/${job.job_id}/`, { status: 'submitted' });
    await api.patch(`/api/jobs/${job.job_id}/`, { status: 'approved' });
    await page.goto(`/#/jobs/${job.job_id}/estimate`);
    await page.reload(); // same-fragment goto doesn't renavigate a hash router
    await expect(
      page.getByText('No estimates. This job is past the estimating phase.')
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start Estimate' })).toHaveCount(0);
  });

  await test.step('The backend refuses the create too', async () => {
    const resp = await api.postRaw('/api/estimates/', { job: job.job_id });
    expect(resp.status()).toBe(400);
    expect(await resp.text()).toContain('past the estimating phase');
  });

  await api.dispose();
});

test('§3 Add Work — the picker finds a service item created in another window', async ({ page, context }) => {
  const jobs = await loadBackdrop();
  const job = findJob(jobs, { status: 'in_progress' });
  test.skip(!job, 'seed gap: no in_progress job for the tasks view');
  const itemName = `${stamp} bevel polishing`;

  await test.step('Window A: open the job tasks view (and leave it alone)', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    await expect(page.getByRole('button', { name: 'Add Work' })).toBeVisible();
  });

  await test.step('Window B: create a new Service Item in the catalog', async () => {
    const pageB = await context.newPage();
    await pageB.goto('/#/catalog/service-items');
    await pageB.getByRole('button', { name: 'Add Service Item' }).click();
    await pageB.getByLabel('Name *').fill(itemName);
    await pageB.getByLabel('Rate Scheme').selectOption({ label: 'CAD (elapsed_time)' });
    await pageB.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(pageB.getByRole('cell', { name: itemName })).toBeVisible();
    await pageB.close();
  });

  await test.step('Window A, WITHOUT reload: Add Work search finds the new item', async () => {
    await page.getByRole('button', { name: 'Add Work' }).click();
    await page.getByPlaceholder('Search services or materials…').fill(stamp);
    await page.getByRole('listbox').getByRole('button', { name: itemName }).click();
  });

  await test.step('The pick opens Add Task From Template, template selected, name prefilled', async () => {
    await expect(page.getByRole('heading', { name: 'Add Task From Template' })).toBeVisible();
    // The pick carries the full item — the mount-time template list never
    // heard of it, so a stale-list lookup would leave the select empty.
    await expect(
      page.getByLabel('Template *').locator('option:checked')
    ).toHaveText(itemName);
    await expect(page.getByLabel('Name *')).toHaveValue(itemName);
    // Close without saving — this step is about the form opening primed.
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
  });
});
