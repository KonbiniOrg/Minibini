// better-fees skeleton phase, Task 11/14 — the estimate document's Edit view
// and the three-mode bar (Edit / Customer / Reorder) that replaced the old
// two-mode lines/wizard toggle. Composing new lines from job atoms moved to
// the Tasks page (bundling-in-task-view, Task 5) — the estimate's own Edit
// view is document-only now.
//
// This spec drives the estimator's core bundling gesture end to end from the
// Tasks page: tick two rows' bundle-selection checkboxes, "Bundle N selected
// into a line…" (TasksPanel's toolbar CTA) opens the shared BundleModal; name
// the merged line there and Create, and see it come back on the estimate
// with a "planned work" BackingChip (apps/api/estimates/serializers.py
// derive_estimate_backing rule 3 — an in-sync task-sourced line). A second,
// single-atom line (select one row, bundle it under the whole-line
// interpretation so it reproduces the old "Add as its own line" shape) gives
// the doc two lines to exercise Reorder mode's up/down arrows on. Customer
// mode is asserted read-only (no checkboxes, no buttons).
//
// Built fresh (job + tasks + draft estimate) rather than hunted from the
// seed: the shape needs two job tasks with zero prior estimate claims on
// them, which the seed can't guarantee spec-to-spec (add-line-and-work-
// authoring's hour-unit-task.spec.js and estimate-gate-and-live-picker.spec.js
// set the same precedent for this kind of shape).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';
import { gotoTasksPage, checkBundleRow, openBundleModal } from '../../lib/bundling.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-3mode-${Date.now().toString(36)}`;

test('three-mode estimate surface: merge into a new line, reorder it, customer view is read-only', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });

  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const scheme = (schemes.results || schemes)
    .find((s) => s.algorithm !== 'percentage' && s.is_active !== false);
  test.skip(!scheme, 'seed gap: no active non-percentage rate scheme');

  const taskAName = `${stamp} task A`;
  const taskBName = `${stamp} task B`;
  const taskCName = `${stamp} task C solo`;
  async function makeTask(name) {
    return api.post(`/api/jobs/${job.job_id}/tasks/`, {
      name, rate_scheme: scheme.rate_scheme_id, est_qty: '3',
    });
  }
  await makeTask(taskAName);
  await makeTask(taskBName);
  await makeTask(taskCName);

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  await api.dispose();

  const mergedName = `${stamp} merged planned work`;

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
  // getByText's RegExp form doesn't normalize the source's internal line
  // break inside the link text — getByRole's accessible-name computation
  // does, so use that instead.
  await expect(page.getByRole('link', { name: /compose lines from the tasks page/i })).toBeVisible();

  await test.step('Tasks page: tick two rows and bundle them into a merged line', async () => {
    await gotoTasksPage(page, job.job_id);
    await checkBundleRow(page, taskAName);
    await checkBundleRow(page, taskBName);
    const modal = await openBundleModal(page, 2);
    // One-unit is the modal's default (per-unit-lines spec) and leaves Qty
    // blank until a multiplier is typed; this test only cares that a merged
    // line lands, so "the whole line" seeds qty/price straight from the
    // atoms with no extra typing.
    await modal.getByRole('radio', { name: /the whole line/i }).check();
    await modal.getByLabel('Description').fill(mergedName);
    await modal.getByRole('button', { name: 'Create line' }).click();
    await expect(modal).toBeHidden();
    // The success overlay is a global fixed-position element that outlives
    // navigation — dismiss it now so it doesn't block the next step's click
    // on this same Tasks page.
    await page.getByRole('button', { name: 'Dismiss message' }).click();
  });

  // Scoped to rows carrying a BackingChip — the parent line row, never the
  // nested AtomChildRow underneath it (same description text, no chip) —
  // so each locator stays a strict-mode-safe single match.
  const lineRow = (text) => page.locator('table.line-items-table tr')
    .filter({ hasText: text }).filter({ has: page.locator('.backing-chip') });

  await test.step('The merged line shows the custom name and a "planned work" chip', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    const row = lineRow(mergedName);
    await expect(row).toBeVisible();
    await expect(row.locator('.backing-chip')).toHaveText('planned work');
  });

  await test.step('A single uncovered atom can be bundled into its own line from the Tasks page', async () => {
    await gotoTasksPage(page, job.job_id);
    await checkBundleRow(page, taskCName);
    const modal = await openBundleModal(page, 1);
    // The whole-line interpretation reproduces the old direct "Add as its
    // own line" shape: qty/price seed straight from the atom's own values,
    // no per-unit multiplier to type.
    await modal.getByRole('radio', { name: /the whole line/i }).check();
    await modal.getByRole('button', { name: 'Create line' }).click();
    await expect(modal).toBeHidden();
    await page.getByRole('button', { name: 'Dismiss message' }).click();

    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    const row = lineRow(taskCName);
    await expect(row).toBeVisible();
    await expect(row.locator('.backing-chip')).toHaveText('planned work');
  });

  await test.step('Reorder mode: the up/down arrows move a line', async () => {
    await page.getByRole('button', { name: 'Reorder' }).click();
    const rows = page.locator('.doc-customer-view tbody tr');
    await expect(rows.first()).toContainText(mergedName);
    await expect(rows.last()).toContainText(taskCName);

    await rows.first().getByRole('button', { name: '▼' }).click();

    await expect(rows.first()).toContainText(taskCName);
    await expect(rows.last()).toContainText(mergedName);
  });

  await test.step('Customer mode renders the collapsed doc with no controls', async () => {
    await page.getByRole('button', { name: 'Customer' }).click();
    await expect(page.getByRole('heading', { name: `Estimate ${estimate.estimate_number}-${estimate.version}` }))
      .toBeVisible();
    const view = page.locator('.doc-customer-view');
    await expect(view).toContainText(mergedName);
    await expect(view).toContainText(taskCName);
    await expect(view.getByRole('button')).toHaveCount(0);
    await expect(view.getByRole('checkbox')).toHaveCount(0);
  });
});
