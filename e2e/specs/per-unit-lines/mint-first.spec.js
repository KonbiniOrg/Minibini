// per-unit-lines spec (.superpowers/sdd/2026-09-16-per-unit-lines-plan) — Task 9,
// the "mint-first" journey: a plain accepted hand line with qty > 1 is
// answered by minting a BRAND NEW task through the acceptance checklist's
// "Generate work..." gesture (Task 5), choosing the one-unit interpretation
// on that first mint. The submitted "Estimated qty" is read as PER UNIT of
// the line's own qty and multiplied before the Task is created (atoms are
// born with totals, never restamped) -- then, with every line on the
// checklist answered, the job auto-releases straight to in_progress.
//
// A dedicated entered_qty/non-hour preset is set as the shop's
// default_rate_scheme so the mint modal's Rate Scheme preselects and the
// "Estimated qty" field is visible without an extra picking step -- same
// arrange idiom as specs/estimating-structure/mint-and-release.spec.js and
// specs/add-line-and-work-authoring/stamped-task-money.spec.js.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-perunit-mint-${Date.now().toString(36)}`;
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
  await configApi.patch('/api/settings/', { default_rate_scheme: String(scheme.rate_scheme_id) });
  await configApi.dispose();
});

test.afterAll(async () => {
  const configApi = await apiAs(personas.configtime);
  await configApi.patch('/api/settings/', { default_rate_scheme: '' });
  await configApi.dispose();
});

test('mint-first: Generate work with the one-unit choice multiplies into a stamped task, completing the checklist and auto-releasing the job', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });

  const handLineDescription = `${stamp} hand line`;
  await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
    description: handLineDescription, qty: '10', units: scheme.unit_label, price: '50.00',
    accounting_category: category.id,
  });

  // mark-open's send-gate requires a non-empty Deliverables list.
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
  const editTable = page.locator('table.line-items-table');
  const lineRow = (desc) => editTable.locator('tbody tr').filter({
    has: page.locator('td.preserve-breaks', { hasText: desc }),
  });

  await test.step('Accept: the checklist banner counts the one unanswered hand line', async () => {
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
    await page.reload();
    await expect(page.locator('.doc-warning')).toHaveText(
      '1 line(s) need a work decision — the job starts automatically when all are answered.'
    );
  });

  const taskName = `${stamp} minted task`;
  await test.step('Generate work…: the first mint against this line offers the one-unit-or-whole-line choice, one-unit checked by default', async () => {
    const row = lineRow(handLineDescription);
    await row.getByRole('button', { name: 'Generate work…' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Add Manual Task' })).toBeVisible();
    await expect(dialog.getByLabel('Name *')).toHaveValue(handLineDescription);

    const oneUnitRadio = dialog.getByRole('radio', { name: /one unit — multiply by quantity/i });
    await expect(oneUnitRadio).toBeChecked();
    await expect(dialog.getByRole('radio', { name: /the whole line/i })).not.toBeChecked();

    await dialog.getByLabel('Name *').fill(taskName);
    // The prefilled "Estimated qty" mirrors the line's own qty (10) — clear
    // it and enter a PER-UNIT value instead (5), which the server multiplies
    // by the line's qty before the Task is created.
    await dialog.getByLabel('Estimated qty').fill('5');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dialog).toBeHidden();
  });

  await test.step('The task is born with the multiplied total (5 x 10 = 50), never the raw per-unit value', async () => {
    const check = await apiAs(personas.finjobs);
    const tasks = await check.get(`/api/jobs/${job.job_id}/tasks/`);
    const minted = (tasks.results || tasks).find((t) => t.name === taskName);
    expect(minted).toBeTruthy();
    expect(Number(minted.est_qty)).toBeCloseTo(50, 2);
    await check.dispose();

    await page.goto(`/#/jobs/${job.job_id}/tasks/${minted.task_id}`);
    await expect(page.getByRole('heading', { name: taskName })).toBeVisible();
    const estQtyChip = page.locator('.stat-chip', {
      has: page.locator('.stat-chip-header', { hasText: 'Est Qty' }),
    });
    await expect(estQtyChip).toContainText('50');
  });

  await test.step('The checklist is now empty and the job auto-released to in_progress', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await expect(page.locator('.doc-warning')).toHaveCount(0);
    await expect(lineRow(handLineDescription).getByRole('button', { name: 'Generate work…' })).toHaveCount(0);

    await expect.poll(async () => {
      const check = await apiAs(personas.finjobs);
      const detail = await check.get(`/api/jobs/${job.job_id}/`);
      await check.dispose();
      return detail.status;
    }).toBe('in_progress');

    const pill = page.locator('.job-header select');
    await expect(pill).toHaveValue('in_progress');
    await expect(pill.locator('option:checked')).toHaveText('In Progress');
  });

  await api.dispose();
});
