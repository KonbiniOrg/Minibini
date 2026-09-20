// bundling-in-task-view (.superpowers/sdd/2026-09-19-bundling-in-task-view-plan)
// — Task 7, upgraded 2026-09-20 (RM: selection allowed before the estimate
// exists). TasksPanel resolves an estimate-context layer with three states:
// no live estimate (B — checkboxes already render off a client-derived
// fallback, no pool exists yet to claim from; the toolbar button reads
// "Start Estimate" at zero selection or "Start Estimate & Bundle N into a
// line…" once something's checked — one click creates the draft AND opens
// the bundle modal seeded with the survivors), a live DRAFT estimate (bundle
// checkboxes + CTA + context line, A), and anything else — a non-draft live
// estimate, or a job past draft/submitted — where none of that renders (C).
// Tasks 3-6 built the underlying selection/bundle gesture and are already
// covered by per-unit-lines/estimating-structure specs; this file's job is
// the state-gating surface: the B->A transition (ending in one real bundle,
// verified via an API read) and two distinct ways to land in state C (a
// straight-to-accepted job, and a job stuck on "approved" behind an
// unanswered work decision — job.status past draft/submitted is what
// actually gates the offer, not the estimate's own status, so both are
// worth covering separately per canOfferEstimate's
// `['draft', 'submitted'].includes(job?.status)` clause).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';
import { gotoTasksPage, taskTreeRow, checkBundleRow } from '../../lib/bundling.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-startest-${Date.now().toString(36)}`;
let scheme;
let category;

test.beforeAll(async () => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);
  const units = await configApi.get('/api/settings/units/');
  const unit = units.find((u) => u !== 'none' && u !== 'hour') || units[0];
  scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp}-scheme`, description: '', algorithm: 'entered_qty',
    rate: '20.00', unit_label: unit, accounting_category: category.id, modifiers: [],
  });
  await configApi.dispose();
});

test('State B -> A: selection is available before the estimate exists; one click starts it and ' +
     'opens the bundle modal; the bundle lands on the estimate', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job B`, contact: contact.contact_id });
  expect(job.status).toBe('draft');

  const taskA = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task A`, rate_scheme: scheme.rate_scheme_id, est_qty: '2.00',
  });
  const taskB = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task B`, rate_scheme: scheme.rate_scheme_id, est_qty: '3.00',
  });

  const bundleDescription = `${stamp} bundled line`;

  await test.step('No estimate yet: checkboxes already render (there is nothing to claim yet, so ' +
                   'every row is selectable) and the button reads plain "Start Estimate" at zero selection', async () => {
    await gotoTasksPage(page, job.job_id);
    // Positive anchor first — the page actually loaded the two seeded
    // tasks, so the checks below aren't vacuous.
    await expect(taskTreeRow(page, taskA.name)).toBeVisible();
    await expect(taskTreeRow(page, taskB.name)).toBeVisible();

    await expect(taskTreeRow(page, taskA.name).locator('input[type="checkbox"]')).toBeVisible();
    await expect(taskTreeRow(page, taskB.name).locator('input[type="checkbox"]')).toBeVisible();
    await expect(page.getByText(/Bundling into estimate/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Start Estimate' })).toBeVisible();
  });

  let draft;
  await test.step('Selecting task A relabels the button; one click both starts the estimate and opens the bundle modal seeded with it', async () => {
    await checkBundleRow(page, taskA.name);
    const bundleBtn = page.getByRole('button', { name: 'Start Estimate & Bundle 1 into a line…' });
    await expect(bundleBtn).toBeVisible();
    await bundleBtn.click();

    // The modal only opens once the create + context-reload round-trip has
    // finished, so waiting for it first guarantees the draft already exists
    // server-side by the time the API check below runs.
    const modal = page.getByRole('dialog');
    await expect(modal).toContainText('Bundle into line');
    await expect(modal).toContainText(taskA.name);

    const check = await apiAs(personas.finjobs);
    const estimates = await check.get(`/api/estimates/?job=${job.job_id}&page_size=100`);
    await check.dispose();
    draft = (estimates.results || estimates).find((e) => e.status === 'draft');
    expect(draft).toBeTruthy();
  });

  await test.step('Complete the bundle in the modal', async () => {
    const modal = page.getByRole('dialog');
    await modal.getByLabel('Description').fill(bundleDescription);
    // One-unit is the modal default; a single-atom bundle seeds price to
    // the atom's own amount (2 x $20 = $40) but leaves qty empty — fill it.
    await modal.getByLabel(/Quantity/).fill('1');
    await modal.getByRole('button', { name: 'Create line' }).click();
    await expect(modal).toBeHidden();

    await expect(page.getByText(`Line added to estimate ${draft.estimate_number} (draft).`)).toBeVisible();
    await expect(taskTreeRow(page, taskA.name).getByText('estimated')).toBeVisible();
    // Task B, never selected, is still a plain available pool atom in state A.
    await expect(taskTreeRow(page, taskB.name).locator('input[type="checkbox"]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start Estimate' })).toHaveCount(0);
  });

  await test.step('API read confirms the bundled line: description, per-unit sourcing, and the claimed task', async () => {
    const check = await apiAs(personas.finjobs);
    const estDetail = await check.get(`/api/estimates/${draft.estimate_id}/`);
    const line = estDetail.line_items.find((li) => li.description === bundleDescription);
    expect(line).toBeTruthy();
    expect(line.per_unit).toBe(true);
    expect(Number(line.qty)).toBeCloseTo(1, 2);
    expect(Number(line.price)).toBeCloseTo(40, 2); // 2.00 est_qty x $20 rate
    expect(line.sources).toHaveLength(1);
    expect(line.sources[0].source_type).toBe('task');
    expect(line.sources[0].source_pk).toBe(taskA.task_id);
    await check.dispose();
  });

  await api.dispose();
});

test('State C (accepted): an all-atom-sourced estimate accepts straight to in_progress — no offer, no bundling', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job C-accepted`, contact: contact.contact_id });
  const task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task C-accepted`, rate_scheme: scheme.rate_scheme_id, est_qty: '1.00',
  });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  // An atom-sourced line is always "answered" (EstimateLineItemSerializer.
  // get_needs_work_decision: obj.sources.exists() -> False) — acceptance
  // needs no mint/decline decision and the job auto-releases in one step.
  await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: task.task_id }],
    overrides: { description: `${stamp} atom line`, qty: '1', units: scheme.unit_label, price: '20.00' },
    per_unit: false,
  });
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

  const jobDetail = await api.get(`/api/jobs/${job.job_id}/`);
  expect(jobDetail.status).toBe('in_progress');
  const estDetail = await api.get(`/api/estimates/${estimate.estimate_id}/`);
  expect(estDetail.status).toBe('accepted');

  await gotoTasksPage(page, job.job_id);
  // Positive anchor: the page rendered the (now-crystallized) task tree
  // and the always-available toolbar action, so the absence checks below
  // are against a page that actually loaded.
  await expect(page.getByRole('button', { name: 'Add Work' })).toBeVisible();
  await expect(page.locator('table.task-tree-table')).toBeVisible();

  await expect(page.locator('table.task-tree-table input[type="checkbox"]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Bundle \d+ selected into a line/ })).toHaveCount(0);
  await expect(page.getByText(/Bundling into estimate/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Start Estimate' })).toHaveCount(0);

  await api.dispose();
});

test('State C (no room): job stuck on "approved" behind an unanswered work decision still offers nothing', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job C-approved`, contact: contact.contact_id });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  // A plain hand line (no atom sources, no catalog identity) always needs a
  // work decision — acceptance parks the job on "approved" instead of
  // auto-releasing (mirrors estimating-structure/mint-and-release.spec.js's
  // "approved-but-unanswered" seed).
  const handLine = await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
    description: `${stamp} unanswered hand line`, qty: '1', units: scheme.unit_label,
    price: '40.00', accounting_category: category.id,
  });
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

  const jobDetail = await api.get(`/api/jobs/${job.job_id}/`);
  expect(jobDetail.status).toBe('approved');
  const estDetail = await api.get(`/api/estimates/${estimate.estimate_id}/`);
  expect(estDetail.status).toBe('accepted');
  const line = estDetail.line_items.find((li) => li.line_item_id === handLine.line_item_id);
  expect(line.needs_work_decision).toBe(true);

  await gotoTasksPage(page, job.job_id);
  // Positive anchor: 'approved' isn't in jobLocked's terminal set, so the
  // ordinary toolbar action and the (empty but rendered) task tree still
  // show — confirms the page loaded before asserting the offer's absence.
  await expect(page.getByRole('button', { name: 'Add Work' })).toBeVisible();
  await expect(page.locator('table.task-tree-table')).toBeVisible();

  await expect(page.locator('table.task-tree-table input[type="checkbox"]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Bundle \d+ selected into a line/ })).toHaveCount(0);
  await expect(page.getByText(/Bundling into estimate/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Start Estimate' })).toHaveCount(0);

  await api.dispose();
});
