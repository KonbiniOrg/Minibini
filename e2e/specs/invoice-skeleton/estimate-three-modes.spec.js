// better-fees skeleton phase, Task 11/14 — the estimate document's merged
// Edit view (line-items table + Uncovered work pool in one surface, no more
// separate "reconcile wizard") and the three-mode bar (Edit / Customer /
// Reorder) that replaced the old two-mode lines/wizard toggle.
//
// This spec drives the estimator's core Edit-mode gesture end to end: tick
// two uncovered work rows, "Bundle into line…" (NewLineFromSelectedRow's
// placeholder-row button, Task 8) opens BundleModal; name the merged line
// there and Create, and see it come back with a "planned work" BackingChip
// (apps/api/estimates/serializers.py derive_estimate_backing rule 3 — an
// in-sync task-sourced line). A second, single-atom line ("Add as its own
// line") gives the doc two lines to exercise Reorder mode's up/down arrows
// on. Customer mode is asserted read-only (no checkboxes, no buttons).
//
// Built fresh (job + tasks + draft estimate) rather than hunted from the
// seed: the shape needs two job tasks with zero prior estimate claims on
// them, which the seed can't guarantee spec-to-spec (add-line-and-work-
// authoring's hour-unit-task.spec.js and estimate-gate-and-live-picker.spec.js
// set the same precedent for this kind of shape).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

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
  await expect(page.getByRole('heading', { name: 'Unquoted work' })).toBeVisible();

  await test.step('Edit mode: tick two uncovered work rows and create a merged line', async () => {
    const rowA = page.locator('tr').filter({ hasText: taskAName });
    const rowB = page.locator('tr').filter({ hasText: taskBName });
    await rowA.locator('input[type="checkbox"]').check();
    await rowB.locator('input[type="checkbox"]').check();

    await expect(page.getByText('＋ New line from selected')).toBeVisible();
    await page.getByRole('button', { name: 'Bundle into line…' }).click();

    const modal = page.getByRole('dialog');
    await expect(modal).toContainText('Bundle into line');
    await modal.getByLabel('Description').fill(mergedName);
    await modal.getByRole('button', { name: 'Create line' }).click();
    await expect(modal).toBeHidden();
  });

  // Scoped to rows carrying a BackingChip — the parent line row, never the
  // nested AtomChildRow underneath it (same description text, no chip) —
  // so each locator stays a strict-mode-safe single match.
  const lineRow = (text) => page.locator('table.line-items-table tr')
    .filter({ hasText: text }).filter({ has: page.locator('.backing-chip') });

  await test.step('The merged line shows the custom name and a "planned work" chip', async () => {
    const row = lineRow(mergedName);
    await expect(row).toBeVisible();
    await expect(row.locator('.backing-chip')).toHaveText('planned work');
  });

  await test.step('A single uncovered atom can be billed directly as its own line', async () => {
    const rowC = page.locator('tr').filter({ hasText: taskCName });
    await rowC.getByRole('button', { name: 'Add as its own line' }).click();
    await expect(page.getByRole('heading', { name: 'Edit Line Item' })).toBeVisible();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Edit Line Item' })).toHaveCount(0);

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
