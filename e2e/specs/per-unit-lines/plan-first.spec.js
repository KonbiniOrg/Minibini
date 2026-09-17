// per-unit-lines spec (.superpowers/sdd/2026-09-16-per-unit-lines-plan) — Task 9,
// the "plan-first" journey: two already-existing job atoms (tasks + a
// material, still unclaimed in the pool) get bundled into ONE estimate line
// under the one-unit interpretation (Task 4's minimal BundleModal addition,
// Task 3's bundle-time stamping). The values on the pool rows are read as
// PER UNIT of the line's own qty — the atoms are immediately stamped to the
// whole-job total (qty x per-unit value) at bundle time, well before
// acceptance — then the estimate is sent/accepted and the job auto-releases
// because the bundled line already carries claimed sources (answered).
//
// Built fresh via the API (contact + a dedicated entered_qty/non-hour rate
// scheme so amounts are deterministic), mirroring
// specs/estimating-structure/mint-and-release.spec.js's arrange idiom.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-perunit-plan-${Date.now().toString(36)}`;
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

test('plan-first: bundling pool atoms one-unit stamps their totals at bundle time; acceptance auto-releases the job', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });

  // Two tasks and a material, left OFF any estimate — the pool atoms the
  // bundle gesture will claim. Their qty/quantity are the PER-UNIT values
  // this journey reinterprets (amount = 2*20 + 3*20 + 4*5 = 120 total).
  const taskA = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task A`, rate_scheme: scheme.rate_scheme_id, est_qty: '2.00',
  });
  const taskB = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task B`, rate_scheme: scheme.rate_scheme_id, est_qty: '3.00',
  });
  const material = await api.post(`/api/jobs/${job.job_id}/materials/`, {
    description: `${stamp} material`, quantity: '4.00', units: scheme.unit_label,
    unit_cost: '5.00', sell_price: '5.00', accounting_category: category.id,
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  // mark-open's send-gate requires a non-empty Deliverables list.
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });

  const bundleDescription = `${stamp} bundled per-unit line`;

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
  const editTable = page.locator('table.line-items-table');
  // A line's OWN row, not a nested AtomChildRow/caption sibling (same
  // scoping caution as mint-and-release.spec.js).
  const lineRow = (desc) => editTable.locator('tbody tr').filter({
    has: page.locator('td.preserve-breaks', { hasText: desc }),
  });
  const fmt = (n) => `$${Number(n).toFixed(2)}`;

  await test.step('Select two tasks + a material from Unquoted work, open Bundle into line…', async () => {
    const pool = page.locator('.uncovered-work-section');
    await pool.locator('tbody tr').filter({ hasText: taskA.name }).locator('input[type="checkbox"]').check();
    await pool.locator('tbody tr').filter({ hasText: taskB.name }).locator('input[type="checkbox"]').check();
    await pool.locator('tbody tr').filter({ hasText: material.description }).locator('input[type="checkbox"]').check();

    const newlineRow = page.locator('tr.doc-newline');
    await expect(newlineRow).toBeVisible();
    await newlineRow.getByRole('button', { name: 'Bundle into line…' }).click();
    await expect(page.getByRole('dialog')).toContainText('Bundle into line');
  });

  let total;
  await test.step('One-unit interpretation is the default; price seeds to the per-unit sum, qty 10 shows the x10 line total', async () => {
    const modal = page.getByRole('dialog');
    const oneUnitRadio = modal.getByRole('radio', { name: /one unit — multiply by quantity/i });
    await expect(oneUnitRadio).toBeChecked();

    const totalText = await modal.locator('table.bundle-atoms tfoot td').last().innerText();
    total = Number(totalText.replace(/[^0-9.-]/g, ''));
    expect(total).toBeCloseTo(120, 2);

    const priceInput = modal.getByLabel(/^Price/);
    await expect(priceInput).toHaveValue(total.toFixed(2));

    const qtyInput = modal.getByLabel(/Quantity/);
    await qtyInput.fill('10');

    await expect(page.getByTestId('bundle-line-total')).toContainText(fmt(total * 10));
    // The preview table announces the coming atom stamps before Create.
    const preview = page.getByTestId('bundle-preview');
    await expect(preview).toBeVisible();
    await expect(preview).toContainText('→ 20');
    await expect(preview).toContainText('→ 30');

    await modal.getByLabel('Description').fill(bundleDescription);
    await modal.getByRole('button', { name: 'Create line' }).click();
    await expect(modal).toBeHidden();
  });

  await test.step('The line shows price = per-unit sum and amount = total x qty', async () => {
    const row = lineRow(bundleDescription);
    await expect(row).toBeVisible();
    const cells = row.locator('td');
    await expect(cells.nth(2)).toContainText('10');
    await expect(cells.nth(3)).toContainText(fmt(total));
    await expect(cells.nth(4)).toContainText(fmt(total * 10));
  });

  await test.step('Atoms are stamped to the whole-job total at bundle time — the task pane already shows it, before acceptance', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks/${taskA.task_id}`);
    await expect(page.getByRole('heading', { name: taskA.name })).toBeVisible();
    const estQtyChip = page.locator('.stat-chip', {
      has: page.locator('.stat-chip-header', { hasText: 'Est Qty' }),
    });
    await expect(estQtyChip).toContainText('20');

    const check = await apiAs(personas.finjobs);
    const taskBDetail = await check.get(`/api/tasks/${taskB.task_id}/`);
    expect(Number(taskBDetail.est_qty)).toBeCloseTo(30, 2);
    const materialDetail = await check.get(`/api/materials/${material.material_id}/`);
    expect(Number(materialDetail.quantity)).toBeCloseTo(40, 2);
    await check.dispose();
  });

  await test.step('Send + accept: the bundled line already has claimed sources, so the job auto-releases straight to in_progress', async () => {
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

    await expect.poll(async () => {
      const check = await apiAs(personas.finjobs);
      const detail = await check.get(`/api/jobs/${job.job_id}/`);
      await check.dispose();
      return detail.status;
    }).toBe('in_progress');

    await page.goto(`/#/jobs/${job.job_id}`);
    const pill = page.locator('.job-header select');
    await expect(pill).toHaveValue('in_progress');
    await expect(pill.locator('option:checked')).toHaveText('In Progress');
  });

  await api.dispose();
});
