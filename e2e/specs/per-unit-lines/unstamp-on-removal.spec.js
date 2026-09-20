// per-unit-lines spec — "un-stamp on removal" (RM decision 2026-09-19):
// removing a per-unit claim from a draft estimate line now restores the
// claimed atom to its one-unit snapshot instead of leaving it stranded at
// the stamped whole-job total (which used to double on re-bundling).
//
// Built fresh via the API (contact + a dedicated entered_qty/non-hour rate
// scheme so amounts are deterministic), same arrange idiom as
// plan-first.spec.js/drift-revert.spec.js: the bundle itself is arranged
// directly through line-items-from-atoms (bundling the gesture is
// plan-first's flow under test, not this one); only the remove-atom gesture
// on the estimate page, and its effect on the Tasks page, go through the UI.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';
import { gotoTasksPage, taskTreeRow } from '../../lib/bundling.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-perunit-unstamp-${Date.now().toString(36)}`;
let scheme;
let category;
let unit;

test.beforeAll(async () => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);
  const units = await configApi.get('/api/settings/units/');
  unit = units.find((u) => u !== 'none' && u !== 'hour') || units[0];
  scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp}-scheme`, description: '', algorithm: 'entered_qty',
    rate: '20.00', unit_label: unit, accounting_category: category.id, modifiers: [],
  });
  await configApi.dispose();
});

test('unstamp-on-removal: removing a per-unit claim restores the atom to its one-unit value', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });

  // Pool atom: a task with est_qty 2 (the one-unit value this bundle will
  // stamp to 20 = 2 x qty 10).
  const task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task`, rate_scheme: scheme.rate_scheme_id, est_qty: '2.00',
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });

  const bundleDescription = `${stamp} bundled per-unit line`;
  const bundled = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: task.task_id }],
    overrides: { description: bundleDescription, qty: '10', units: unit, price: '20.00' },
    per_unit: true,
  });
  const taskSource = bundled.sources.find((s) => s.source_type === 'task');
  expect(taskSource.per_unit_qty).toBe('2.00');
  expect(taskSource.expected_total).toBe('20.00');

  await test.step('Stamped at bundle time: the task reads the whole-job total (20), not the one-unit value', async () => {
    await gotoTasksPage(page, job.job_id);
    await expect(taskTreeRow(page, task.name).getByText('estimated')).toBeVisible();

    const check = await apiAs(personas.finjobs);
    const taskDetail = await check.get(`/api/tasks/${task.task_id}/`);
    await check.dispose();
    expect(Number(taskDetail.est_qty)).toBeCloseTo(20, 2);
  });

  await test.step('Remove the claim from the line on the estimate page', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    const atomRow = page.locator('tr.doc-atom-row').filter({ hasText: task.name });
    await expect(atomRow).toBeVisible();
    await atomRow.getByRole('button', { name: 'Remove from this line' }).click();

    // The claim was the line's only atom — the line itself is deleted.
    const editTable = page.locator('table.line-items-table');
    await expect(editTable.locator('tbody tr').filter({ hasText: bundleDescription })).toHaveCount(0);
  });

  await test.step('Back on the Tasks page, the task shows its one-unit value again and is unclaimed', async () => {
    await gotoTasksPage(page, job.job_id);
    await expect(taskTreeRow(page, task.name).getByText('estimated')).toHaveCount(0);

    const check = await apiAs(personas.finjobs);
    const taskDetail = await check.get(`/api/tasks/${task.task_id}/`);
    await check.dispose();
    expect(Number(taskDetail.est_qty)).toBeCloseTo(2, 2);
  });

  await api.dispose();
});
