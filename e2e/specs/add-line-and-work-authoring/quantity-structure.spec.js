// task-owned-money Phase 4 (spec §9, docs/plans/2026-08-03-task-owned-money-
// phase4-plan.md Task 8): quantity-bearing parent tasks with per-unit/
// per-batch subtasks. A manager builds a "Widgets" structure ad hoc (Add
// Task + two Add Subtask gestures — no template involved), exercising:
//   - the ALWAYS-visible inline derived-expectation line on the subtask form
//     (WorkItemForm.svelte, spec §9 rule 3) for a flag-true (×parent qty)
//     and a flag-false (fixed per batch) child;
//   - the parent's children table (expected-vs-logged) and non-startable
//     state (no Start Work; Complete withheld until every child is
//     terminal — TaskDetailPage.svelte / TaskActions.svelte, rule 1);
//   - a worker timeslip (blep) on the CHILD only — the parent has no blep
//     affordance;
//   - the completion offer once both children are terminal, and the
//     parent's own "quantity made" settle-up prompt;
//   - the estimate wizard (reconcile mode) source pool offering ONLY the
//     parent, priced via Task.derived_unit_price() (rule 4) — children
//     never appear;
//   - the Deliverables bridge (rule 7): "Add as Deliverable" from the
//     parent, and the passive mismatch badge (task est_qty vs the
//     deliverable's qty_ordered) appearing only once they diverge.
//
// The parent's own `rate` is nulled via a direct API PATCH after creation:
// that is how every real container-only parent gets into this state today
// (hand-line crystallization, the Deliverable->Task bridge) — the manual
// "Add Task" form always stamps a scheme's rate onto a NEW task, and once a
// task is terminal (as our parent becomes, at the very end) "Edit Task" no
// longer offers a way to clear it either. tests/test_quantity_structure.py's
// own backend fixtures null the rate the identical way (`parent.rate = None;
// parent.save()`) for the same reason — there is no first-class UI gesture
// for it (yet).
import { expect, test } from '@playwright/test';
import { apiAs, closeOpenSession } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-qs-${Date.now().toString(36)}`;

const rateChipOf = (page) => page.locator('.stat-chip', {
  has: page.locator('.stat-chip-header', { hasText: 'Rate' }),
});
const actualChipOf = (page) => page.locator('.stat-chip', {
  has: page.locator('.stat-chip-header', { hasText: 'Actual' }),
});
const deliverablesPanel = (page) => page.locator('.deliverables-panel');

test.afterEach(async () => {
  await closeOpenSession(personas.worker);
});

test('ad hoc widget structure: derived expectations, non-startable parent, blep, completion offer, wizard exclusion, deliverables bridge', async ({ page, browser }) => {
  const parentName = `${stamp} Widgets`;
  const laserName = `${stamp} Laser cutting`;
  const setupName = `${stamp} Setup`;

  // ── Scaffolding: job + rate schemes (config, not a job/financials write —
  // configtime creates schemes, matching hour-unit-task.spec.js /
  // hand-line-kinds.spec.js). Built fresh so a full-suite run can't land
  // this on data another spec already mutated. ──────────────────────────
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  const category = (cats.results || cats)[0];
  const parentScheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp} parent scheme`, description: '', algorithm: 'entered_qty',
    rate: '5.00', unit_label: 'ea', accounting_category: category.id, modifiers: [],
  });
  // Both children price at $2.00/min so the derived math is round:
  // per-unit (Laser, 15 min/ea) contributes 15*2=30.00/ea; per-batch (Setup,
  // 20 min flat) contributes 20*2=40.00, spread over the parent's 10 ea =
  // 4.00/ea. derived_unit_price = 30.00 + 4.00 = 34.00/ea.
  const childScheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp} child scheme`, description: '', algorithm: 'entered_qty',
    rate: '2.00', unit_label: 'min', accounting_category: category.id, modifiers: [],
  });
  await configApi.dispose();

  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });

  await test.step('Ad hoc build: Add Task creates the parent (10 ea, entered qty)', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    await page.getByRole('button', { name: 'Add Work' }).click();
    await page.getByLabel('Add line').getByRole('button', { name: 'Add Task' }).click();
    await page.getByLabel('Rate Scheme *').selectOption({ label: parentScheme.name });
    await page.getByLabel('Name *').fill(parentName);
    await page.getByLabel('Estimated qty').fill('10');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  // Container-only parent (see file header): no first-class UI path clears
  // a task's own rate, so this mirrors the backend's own test fixtures.
  const tasksResp = await api.get(`/api/jobs/${job.job_id}/tasks/`);
  const allTasks = tasksResp.results || tasksResp;
  const parentTask = allTasks.find((t) => t.name === parentName);
  await api.patch(`/api/jobs/${job.job_id}/tasks/${parentTask.task_id}/`, { rate: null });

  await page.goto(`/#/jobs/${job.job_id}/tasks/${parentTask.task_id}`);
  await expect(page.getByRole('heading', { name: parentName })).toBeVisible();

  await test.step('Add Subtask "Laser cutting" (per-unit, 15 min): checkbox defaults CHECKED, inline preview shows the ×parent-qty total', async () => {
    await page.getByRole('button', { name: 'Add Subtask' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Add Manual Task' })).toBeVisible();
    await dialog.getByLabel('Rate Scheme *').selectOption({ label: childScheme.name });
    await dialog.getByLabel('Name *').fill(laserName);
    await dialog.getByLabel('Estimated qty').fill('15');
    // Default is unit-keyed off the PARENT's own unit ('ea') — freely
    // overridable, but this is the every-day case: leave it checked.
    await expect(dialog.getByLabel(/scales with parent/i)).toBeChecked();
    await expect(dialog.locator('.derived-expectation'))
      .toContainText('15 min × 10 ea = 150 expected');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('Add Subtask "Setup" (per-batch, 20 min, flag OFF): expectation stays fixed regardless of parent qty', async () => {
    await page.getByRole('button', { name: 'Add Subtask' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Rate Scheme *').selectOption({ label: childScheme.name });
    await dialog.getByLabel('Name *').fill(setupName);
    await dialog.getByLabel('Estimated qty').fill('20');
    const scalesCheckbox = dialog.getByLabel(/scales with parent/i);
    await expect(scalesCheckbox).toBeChecked(); // same unit-keyed default...
    await scalesCheckbox.uncheck();             // ...freely overridable to a batch total
    await expect(dialog.locator('.derived-expectation'))
      .toContainText('20 min per batch — fixed regardless of parent quantity.');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('Children table: per-unit vs derived-total columns reflect the ×10 / ×1 split', async () => {
    const childrenTable = page.locator('.children-table');
    const laserRow = childrenTable.locator('tr', { hasText: laserName });
    await expect(laserRow.getByText('15.00 min', { exact: true })).toBeVisible();
    await expect(laserRow.getByText('150.00 min', { exact: true })).toBeVisible();
    const setupRow = childrenTable.locator('tr', { hasText: setupName });
    await expect(setupRow.getByText('20.00 min (batch)', { exact: true })).toBeVisible();
    // Setup's Per-unit Est cell ALSO reads "20.00 min" (before the "(batch)"
    // suffix) — scope the Expected-column assertion to avoid double-counting
    // that substring match.
    await expect(setupRow.locator('td').nth(3)).toHaveText('20.00 min');
  });

  await test.step('Parent is non-startable, prices from its children, and withholds Complete until they finish', async () => {
    await expect(page.getByRole('button', { name: 'Start Work' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Complete', exact: true })).toHaveCount(0);
    await expect(page.getByText(
      'Complete will be available once every subtask is complete or cancelled.'
    )).toBeVisible();
    await expect(rateChipOf(page)).toContainText('derived from children: $34.00/ea');
  });

  await test.step('Estimate wizard: source pool offers ONLY the parent, at the derived price — children never appear', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate`);
    await page.getByRole('button', { name: 'Start Estimate' }).click();
    await expect(page).toHaveURL(/#\/jobs\/\d+\/estimate\/\d+/);
    await page.getByRole('button', { name: 'Show Tasks & Materials' }).click();
    const parentAtom = page.locator('label', { hasText: parentName });
    await expect(parentAtom).toContainText('10 ea × $34.00 = $340.00');
    await expect(page.getByText(laserName)).toHaveCount(0);
    await expect(page.getByText(setupName)).toHaveCount(0);
  });

  await test.step('Deliverables bridge: "Add as Deliverable" copies the parent, no mismatch while qtys agree', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks/${parentTask.task_id}`);
    await page.getByRole('button', { name: 'Add as Deliverable' }).click();
    await expect(page.getByRole('button', { name: 'Add as Deliverable' })).toHaveCount(0);
    // The sidebar Deliverables panel (JobContextBand) owns its own fetch,
    // independent of the task page's — a reload is how a real user would
    // see it too (no live cross-panel refresh today).
    await page.reload();
    const panel = deliverablesPanel(page);
    const row = panel.locator('tr', { hasText: parentName });
    await expect(row.locator('td.num')).toHaveText('10');
    await expect(row.locator('td.units')).toHaveText('ea');
    await expect(row.getByRole('link', { name: parentName })).toBeVisible();
    await expect(panel.locator('.mismatch-badge')).toHaveCount(0);
  });

  await test.step('Mismatch badge appears once the parent\'s own est_qty diverges from the deliverable\'s ordered qty', async () => {
    await page.getByRole('button', { name: 'Edit Task' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Estimated qty').fill('12');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.reload();
    const badge = deliverablesPanel(page).locator('.mismatch-badge');
    await expect(badge).toBeVisible();
    await expect(badge).toHaveAttribute('title', 'Task estimates 12; this deliverable orders 10.');
  });

  // ── Worker blep on the CHILD, then completion → the parent's offer. ──
  const subtasksResp = await api.get(`/api/tasks/${parentTask.task_id}/subtasks/`);
  const laserTask = subtasksResp.find((t) => t.name === laserName);
  const setupTask = subtasksResp.find((t) => t.name === setupName);

  const workerCtx = await browser.newContext({ storageState: personas.worker.storageState });
  const workerPage = await workerCtx.newPage();
  await test.step('A worker timeslips (bleps) the CHILD — the parent offers no such affordance', async () => {
    await workerPage.goto(`http://localhost:9100/#/jobs/${job.job_id}/tasks/${laserTask.task_id}`);
    await workerPage.getByRole('button', { name: 'Start Work' }).click();
    await expect(workerPage.getByText('Working on:')).toBeVisible();
    // Confirmed earlier this same test that the PARENT never renders
    // "Start Work" at all — this is the child-only affordance that offer
    // was standing in contrast to. The open session is settled by the
    // child's own completion below (BlepService._close_open), and
    // afterEach's closeOpenSession is the hygiene backstop either way.
  });
  await workerCtx.close();

  await test.step('Completing both children settles their quantities', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks/${laserTask.task_id}`);
    await page.getByRole('button', { name: 'Complete', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Settle up quantity' })).toBeVisible();
    await expect(page.getByText('Entered so far: 0 min. Any more to add?')).toBeVisible();
    await page.getByLabel('Quantity (min)').fill('15');
    await page.getByRole('button', { name: 'Complete task' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Complete', exact: true })).toHaveCount(0);

    await page.goto(`/#/jobs/${job.job_id}/tasks/${setupTask.task_id}`);
    await page.getByRole('button', { name: 'Complete', exact: true }).click();
    await page.getByLabel('Quantity (min)').fill('20');
    await page.getByRole('button', { name: 'Complete task' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('Parent completion offer appears once both children are terminal; completing enters the quantity made', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks/${parentTask.task_id}`);
    await expect(page.getByText(
      'Complete will be available once every subtask is complete or cancelled.'
    )).toHaveCount(0);
    await page.getByRole('button', { name: 'Complete', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Settle up quantity' })).toBeVisible();
    await expect(page.getByText('Entered so far: 0 ea. Any more to add?')).toBeVisible();
    await page.getByLabel('Quantity (ea)').fill('9');
    await page.getByRole('button', { name: 'Complete task' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(actualChipOf(page)).toContainText('9.00 ea');
  });

  await api.dispose();
});

test('Deliverables bridge, reverse direction: "Create work structure" mints a scheme-less top-level task', async ({ page }) => {
  const deliverableDesc = `${stamp} Widget crates`;

  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} reverse-bridge job`, contact: contact.contact_id,
  });
  // Creating the Deliverable itself isn't the flow under test here (that's
  // covered by the Deliverables ui-flow); the bridge ACTION is, so the
  // deliverable is seeded directly, matching the layering rule.
  const deliverable = await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: deliverableDesc, qty_ordered: '7', units: 'ea',
  });

  await page.goto(`/#/jobs/${job.job_id}/tasks`);
  const panel = deliverablesPanel(page);
  const row = panel.locator('tr', { hasText: deliverableDesc });
  await row.getByRole('button', { name: 'Create work structure' }).click();
  await expect(row.getByRole('button', { name: 'Create work structure' })).toHaveCount(0);
  const link = row.getByRole('link', { name: deliverableDesc });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByRole('heading', { name: deliverableDesc })).toBeVisible();

  // Money-less by construction (rule 7): no Scheme/Rate/Category/Charge
  // chips at all (hasMoney gates on rate!=null || is_parent, neither true
  // here) — confirmed via the API rather than the UI's absence-of-evidence,
  // since a missing chip alone can't distinguish "money-less" from "still
  // loading".
  const fresh = await api.get(`/api/jobs/${job.job_id}/deliverables/${deliverable.id}/`);
  expect(fresh.source_task).not.toBeNull();
  const mintedTask = await api.get(`/api/jobs/${job.job_id}/tasks/${fresh.source_task}/`);
  expect(mintedTask.rate).toBeNull();
  expect(mintedTask.accounting_category).toBeNull();
  expect(mintedTask.est_qty).toBe('7.00');
  expect(mintedTask.unit_label).toBe('ea');
  await expect(page.getByText('Scheme')).toHaveCount(0);

  await api.dispose();
});
