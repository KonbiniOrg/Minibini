// per-unit-lines spec (.superpowers/sdd/2026-09-16-per-unit-lines-plan) —
// Task 8, the "split-materials" journey: when a one-unit bundle's selection
// carries at least one task AND at least one material, BundleModal offers
// "Split materials onto their own line" — checking it mints TWO sibling
// per-unit lines instead of one (a labor line claiming the task atoms, a
// materials line claiming the material atoms, description suffixed
// " — materials", same qty), both stamped at bundle time.
//
// Built fresh via the API (contact + a dedicated entered_qty/non-hour rate
// scheme), mirroring plan-first.spec.js's arrange idiom — the checkbox
// gesture itself, and the resulting two-line create, are exercised through
// the UI (that's the flow under test here).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';
import { gotoTasksPage, checkBundleRow, openBundleModal } from '../../lib/bundling.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-perunit-split-${Date.now().toString(36)}`;
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
    rate: '60.00', unit_label: unit, accounting_category: category.id, modifiers: [],
  });
  await configApi.dispose();
});

test('split-materials: checking the split box on a mixed one-unit bundle mints a labor line and a materials line', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });

  // Task per-unit amount: 0.75 x $60 = $45.00. Material per-unit amount:
  // 4 x $2.50 = $10.00. Selection total = $55.00.
  const task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} task`, rate_scheme: scheme.rate_scheme_id, est_qty: '0.75',
  });
  const material = await api.post(`/api/jobs/${job.job_id}/materials/`, {
    description: `${stamp} material`, quantity: '4.00', units: unit,
    unit_cost: '2.50', sell_price: '2.50', accounting_category: category.id,
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });

  const editTable = page.locator('table.line-items-table');
  // Exact text match (not the usual substring `hasText`): the materials
  // line's description is the labor line's description PLUS " — materials",
  // so a substring filter would match both rows for the labor description.
  const lineRow = (desc) => editTable.locator('tbody tr').filter({
    has: page.locator('td.preserve-breaks').getByText(desc, { exact: true }),
  });
  const fmt = (n) => `$${Number(n).toFixed(2)}`;
  const splitCheckbox = () => page.getByRole('dialog').getByLabel('Split materials onto their own line');

  await test.step('With only the task selected on the Tasks page, the split checkbox is absent — it needs both a task and a material', async () => {
    await gotoTasksPage(page, job.job_id);
    await checkBundleRow(page, task.name);
    await openBundleModal(page, 1);

    await expect(splitCheckbox()).toHaveCount(0);
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
  });

  const bundleDescription = `${stamp} split bundle`;
  const materialsDescription = `${bundleDescription} — materials`;

  await test.step('Selecting the material too and reopening: the checkbox appears; checking it re-seeds price to the task-only sum', async () => {
    await checkBundleRow(page, material.description);
    const modal = await openBundleModal(page, 2);

    const oneUnitRadio = modal.getByRole('radio', { name: /one unit — multiply by quantity/i });
    await expect(oneUnitRadio).toBeChecked();

    const priceInput = modal.getByLabel(/^Price/);
    await expect(priceInput).toHaveValue('55.00'); // full per-unit sum, unchecked

    await modal.getByLabel('Description').fill(bundleDescription);
    const qtyInput = modal.getByLabel(/Quantity/);
    await qtyInput.fill('10');

    await expect(splitCheckbox()).toBeVisible();
    await splitCheckbox().check();
    await expect(priceInput).toHaveValue('45.00'); // task-only per-unit sum

    await expect(page.getByTestId('bundle-line-total')).toContainText(fmt(450)); // 45 x 10
    await expect(page.getByTestId('bundle-split-materials-price')).toContainText(fmt(10));
    await expect(page.getByTestId('bundle-split-materials-price')).toContainText(fmt(100)); // 10 x 10
    await expect(page.getByTestId('bundle-split-combined-total')).toContainText(fmt(550)); // (45+10) x 10

    const preview = page.getByTestId('bundle-preview');
    await expect(preview).toBeVisible();
    await expect(preview).toContainText('→ 7.50'); // task: 0.75 x 10
    await expect(preview).toContainText('→ 40'); // material: 4 x 10

    await modal.getByRole('button', { name: 'Create line' }).click();
    await expect(modal).toBeHidden();
  });

  await test.step('Two sibling lines land on the estimate: labor (task claim) and materials (material claim)', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    const laborRow = lineRow(bundleDescription);
    await expect(laborRow).toBeVisible();
    const laborCells = laborRow.locator('td');
    await expect(laborCells.nth(2)).toContainText('10');
    await expect(laborCells.nth(3)).toContainText(fmt(45));
    await expect(laborCells.nth(4)).toContainText(fmt(450));

    const materialsRow = lineRow(materialsDescription);
    await expect(materialsRow).toBeVisible();
    const materialsCells = materialsRow.locator('td');
    await expect(materialsCells.nth(2)).toContainText('10');
    await expect(materialsCells.nth(3)).toContainText(fmt(10));
    await expect(materialsCells.nth(4)).toContainText(fmt(100));
  });

  await test.step('Both atoms are stamped to their whole-job totals (per-unit value x qty)', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks/${task.task_id}`);
    await expect(page.getByRole('heading', { name: task.name })).toBeVisible();
    const estQtyChip = page.locator('.stat-chip', {
      has: page.locator('.stat-chip-header', { hasText: 'Est Qty' }),
    });
    await expect(estQtyChip).toContainText('7.50');

    const check = await apiAs(personas.finjobs);
    const materialDetail = await check.get(`/api/materials/${material.material_id}/`);
    expect(Number(materialDetail.quantity)).toBeCloseTo(40, 2);
    await check.dispose();
  });

  await api.dispose();
});
