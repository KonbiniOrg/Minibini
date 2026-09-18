// per-unit-lines spec (.superpowers/sdd/2026-09-16-per-unit-lines-plan) — Task
// 9 follow-up, the "drift-revert" journey: a per-unit bundle stamps its
// claimed atoms to whole-job totals at bundle time (per plan-first.spec.js);
// once stamped, a hand edit on the atom itself (never the line) can leave it
// disagreeing with the agreement `per_unit_qty x line qty` snapshot. The
// estimate edit view flags that with a "≠ agreement" badge on the drifted
// atom row (AtomChildRow); clicking it opens DriftModal, which spells out
// the agreement expectation vs. the atom's live value and offers "Revert to
// agreement" (POSTs restamp-atom) or Cancel — never a one-click revert.
//
// Built fresh via the API (contact + a dedicated entered_qty/non-hour rate
// scheme, same arrange idiom as plan-first/mint-first): the bundle itself is
// arranged directly through line-items-from-atoms (it's not the flow under
// test here — that's plan-first's job) and the hand edit is a plain API
// PATCH on the task, same idiom as the other specs' atom setup. Only the
// badge/modal/revert gestures themselves go through the UI.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-perunit-drift-${Date.now().toString(36)}`;
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

test('drift-revert: a hand edit drifts the stamped atom from its agreement; the badge opens a modal that reverts it back', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });

  // Pool atoms: a task (per-unit qty 2) and a material (per-unit qty 4).
  const task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task`, rate_scheme: scheme.rate_scheme_id, est_qty: '2.00',
  });
  const material = await api.post(`/api/jobs/${job.job_id}/materials/`, {
    description: `${stamp} material`, quantity: '4.00', units: unit,
    unit_cost: '5.00', sell_price: '5.00', accounting_category: category.id,
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });

  const bundleDescription = `${stamp} bundled per-unit line`;
  // Arrange the bundle directly through the API (the bundle GESTURE itself
  // is plan-first's flow under test, not this one) — one-unit interpretation,
  // qty 10: task stamps to est_qty 20, material stamps to quantity 40.
  const bundled = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: task.task_id }, { type: 'material', id: material.material_id }],
    overrides: { description: bundleDescription, qty: '10', units: unit, price: '60.00' },
    per_unit: true,
  });
  const taskSourceAtBundle = bundled.sources.find((s) => s.source_type === 'task');
  const materialSource = bundled.sources.find((s) => s.source_type === 'material');
  expect(taskSourceAtBundle.per_unit_qty).toBe('2.00');
  expect(taskSourceAtBundle.expected_total).toBe('20.00');
  expect(materialSource.per_unit_qty).toBe('4.00');
  expect(materialSource.expected_total).toBe('40.00');

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
  const atomRow = (desc) => page.locator('tr.doc-atom-row').filter({ hasText: desc });
  const badge = (desc) => atomRow(desc).getByRole('button', { name: '≠ agreement' });

  await test.step('Freshly stamped: neither atom row shows a drift badge', async () => {
    await expect(atomRow(task.name)).toBeVisible();
    await expect(badge(task.name)).toHaveCount(0);
    await expect(atomRow(material.description)).toBeVisible();
    await expect(badge(material.description)).toHaveCount(0);
  });

  let taskSrc;
  await test.step('Hand-editing the task directly (never the line) drifts it from the agreement', async () => {
    await api.patch(`/api/jobs/${job.job_id}/tasks/${task.task_id}/`, { est_qty: '999.00' });

    const check = await apiAs(personas.finjobs);
    const estDetail = await check.get(`/api/estimates/${estimate.estimate_id}/`);
    await check.dispose();
    const line = estDetail.line_items.find((li) => li.line_item_id === bundled.line_item_id);
    taskSrc = line.sources.find((s) => s.source_type === 'task');
    const matSrc = line.sources.find((s) => s.source_type === 'material');
    expect(taskSrc.drift).toBe(true);
    expect(taskSrc.qty).toBe('999.00');
    expect(matSrc.drift).toBe(false);

    await page.reload();
    await expect(badge(task.name)).toBeVisible();
    // The non-drifted material row shows no badge at all.
    await expect(atomRow(material.description)).toBeVisible();
    await expect(badge(material.description)).toHaveCount(0);
  });

  const dialog = () => page.getByRole('dialog', { name: 'Agreement drift' });

  await test.step('Clicking the badge shows the agreement expectation and the current value, with real numbers', async () => {
    await badge(task.name).click();
    await expect(dialog()).toBeVisible();
    await expect(dialog()).toContainText(`${task.name} does not match the agreement`);
    // Agreement: 2.00 <unit> per unit x 10.00 units = 20.00 <unit>.
    await expect(dialog()).toContainText(`${taskSrc.per_unit_qty} ${unit}`);
    await expect(dialog()).toContainText(`${bundled.qty} units`);
    await expect(dialog()).toContainText(`${taskSrc.expected_total} ${unit}`);
    // Currently on <task name>: 999.00 <unit>.
    await expect(dialog()).toContainText(`Currently on ${task.name}: ${taskSrc.qty} ${unit}`);
  });

  await test.step('Cancel closes the modal with no change — the drift and the hand-edited value persist', async () => {
    await dialog().getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog()).toBeHidden();
    await expect(badge(task.name)).toBeVisible();

    const check = await apiAs(personas.finjobs);
    const taskDetail = await check.get(`/api/tasks/${task.task_id}/`);
    await check.dispose();
    expect(taskDetail.est_qty).toBe('999.00');
  });

  await test.step('Reopening and choosing Revert to agreement resets the atom and clears the badge', async () => {
    await badge(task.name).click();
    await expect(dialog()).toBeVisible();
    await dialog().getByRole('button', { name: 'Revert to agreement' }).click();
    await expect(dialog()).toBeHidden();

    await expect(badge(task.name)).toHaveCount(0);
    // The atom row's own qty cell now shows the reverted per-unit total (20.00).
    await expect(atomRow(task.name).locator('td.text-right').first()).toContainText('20.00');

    const check = await apiAs(personas.finjobs);
    const taskDetail = await check.get(`/api/tasks/${task.task_id}/`);
    await check.dispose();
    expect(taskDetail.est_qty).toBe('20.00');
  });

  await api.dispose();
});
