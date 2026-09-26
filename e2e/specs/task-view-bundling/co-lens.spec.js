// Tasks-page CO lens (RM 2026-09-20): a held job's draft change order is a
// second bundling target on the Tasks page, alongside the draft-estimate
// lens covered by start-estimate-offer.spec.js. Two journeys:
//   1. A held job WITH a draft CO — the context line names it, checkboxes
//      render for pre-hold unclaimed work, and bundling posts to the CO.
//   2. A held job with NO draft CO — a passive hint link to the CO's home
//      (the accepted estimate page, where the CO gets explicitly created —
//      unlike an estimate, a change order is never auto-created), no
//      checkboxes.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';
import { gotoTasksPage, taskTreeRow, checkBundleRow, openBundleModal } from '../../lib/bundling.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-colens-${Date.now().toString(36)}`;
let scheme;
let category;

test.beforeAll(async () => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);
  await configApi.dispose();
});

// An accepted-estimate, held job: one task claimed on the estimate (so
// acceptance auto-releases without a work decision) and one task left
// unclaimed — created before the hold, so it's exactly the "pre-hold
// unclaimed work" the CO lens exists to cover.
async function buildHeldJobWithUnclaimedTask(api, { nameSuffix }) {
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const resolvedScheme = (schemes.results || schemes)
    .find((s) => s.algorithm === 'entered_qty' && s.is_active !== false);
  if (!resolvedScheme) return null;
  scheme = resolvedScheme;

  const job = await api.post('/api/jobs/', { name: `${stamp} job ${nameSuffix}`, contact: contact.contact_id });
  const claimedTask = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} claimed ${nameSuffix}`, rate_scheme: scheme.rate_scheme_id, est_qty: '1',
  });
  const unclaimedTask = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} unclaimed ${nameSuffix}`, rate_scheme: scheme.rate_scheme_id, est_qty: '2',
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: claimedTask.task_id }],
  });
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable ${nameSuffix}`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

  const jobDetail = await api.get(`/api/jobs/${job.job_id}/`);
  expect(jobDetail.status).toBe('in_progress'); // atom-sourced line auto-releases

  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: `e2e: co-lens ${nameSuffix}` });

  return { job, estimate, claimedTask, unclaimedTask };
}

test('State D: a draft CO on a held job shows the context line and checkboxes; ' +
     'bundling the pre-hold unclaimed task lands on the CO', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const built = await buildHeldJobWithUnclaimedTask(api, { nameSuffix: 'D' });
  test.skip(!built, 'seed gap: no active entered_qty rate scheme');
  const { job, unclaimedTask } = built;

  const co = await api.post('/api/change-orders/', { job: job.job_id });
  expect(co.status).toBe('draft');

  await gotoTasksPage(page, job.job_id);
  // Positive anchor: the page actually loaded the unclaimed task before the
  // context-line/checkbox assertions below.
  await expect(taskTreeRow(page, unclaimedTask.name)).toBeVisible();

  const contextLine = page.locator('p.estimate-context')
    .filter({ hasText: `Bundling into change order ${co.change_order_number} (draft)` });
  await expect(contextLine).toBeVisible();
  const viewLink = contextLine.getByRole('link', { name: 'view', exact: true });
  await expect(viewLink).toHaveAttribute('href', `#/jobs/${job.job_id}/change-order/${co.change_order_id}`);

  const checkbox = taskTreeRow(page, unclaimedTask.name).locator('input[type="checkbox"]');
  await expect(checkbox).toBeVisible();
  await expect(checkbox).toBeEnabled();

  const bundleDescription = `${stamp} co-bundled line`;
  await checkBundleRow(page, unclaimedTask.name);
  const modal = await openBundleModal(page, 1);
  await modal.getByLabel('Description').fill(bundleDescription);
  await modal.getByLabel(/Quantity/).fill('1');
  await modal.getByRole('button', { name: 'Create line' }).click();
  await expect(modal).toBeHidden();

  await expect(page.getByText(`Line added to change order ${co.change_order_number} (draft).`)).toBeVisible();
  await expect(taskTreeRow(page, unclaimedTask.name).getByText('on change order')).toBeVisible();

  const check = await apiAs(personas.finjobs);
  const coDetail = await check.get(`/api/change-orders/${co.change_order_id}/`);
  const line = coDetail.line_items.find((li) => li.description === bundleDescription);
  expect(line).toBeTruthy();
  expect(line.action).toBe('add');
  const pool = await check.get(`/api/change-orders/${co.change_order_id}/source-pool/`);
  const poolEntry = pool.atoms.find((a) => a.type === 'task' && a.id === unclaimedTask.task_id);
  expect(poolEntry.state).toBe('claimed_by_current');
  await check.dispose();

  await api.dispose();
});

test('Hint state: a held job with an accepted estimate but NO draft CO shows a link, ' +
     'never a create button, and it lands on the CO\'s home page', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const built = await buildHeldJobWithUnclaimedTask(api, { nameSuffix: 'hint' });
  test.skip(!built, 'seed gap: no active entered_qty rate scheme');
  const { job, unclaimedTask, estimate } = built;

  await gotoTasksPage(page, job.job_id);
  // Positive anchor: the unclaimed task is on the page (the tree loaded)
  // before asserting the hint/absence of checkboxes.
  await expect(taskTreeRow(page, unclaimedTask.name)).toBeVisible();

  await expect(page.getByText(/Bundling into change order/i)).toHaveCount(0);
  await expect(page.locator('table.task-tree-table input[type="checkbox"]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Bundle \d+ selected into a line/ })).toHaveCount(0);

  const hintLink = page.getByRole('link', { name: 'start a change order' });
  await expect(hintLink).toBeVisible();
  await expect(hintLink).toHaveAttribute('href', `#/jobs/${job.job_id}/estimate`);

  await hintLink.click();
  await expect(page).toHaveURL(new RegExp(`#/jobs/${job.job_id}/estimate$`));
  await expect(page.getByText(estimate.estimate_number, { exact: false })).toBeVisible();

  await api.dispose();
});
