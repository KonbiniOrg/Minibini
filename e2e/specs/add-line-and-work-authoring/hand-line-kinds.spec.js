// task-owned-money Phase 2 (Task 10): the estimate line-add footer now offers
// three explicit kinds (Work / Material / Fee-Credit) via freeform_kind,
// replacing the retired is_material boolean (frontend/src/components/
// PriceListPicker.svelte's non-taskSurface footer + estimates/
// EstimateAddLineForm.svelte). This spec walks a Work hand-line (the preset
// dropdown prefills rate/unit/category) and a negative Fee/Credit hand-line
// (credit note, "-$" rendering) through estimate acceptance:
// apps/estimates/acceptance.py crystallizes the Work line into a flat Task
// (entered-qty, no RateScheme — money block present, provenance chip shows
// the "—" dash) and the Fee line into a Fee shown in the job's Fees section
// with its negative amount; both then show up in the invoice wizard's
// source pool (apps/invoicing/services.py get_source_pool), the credit
// rendering negative there too.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-hlk-${Date.now().toString(36)}`;

const schemeChipOf = (page) => page.locator('.stat-chip', {
  has: page.locator('.stat-chip-header', { hasText: 'Scheme' }),
});
const rateChipOf = (page) => page.locator('.stat-chip', {
  has: page.locator('.stat-chip-header', { hasText: 'Rate' }),
});

test('estimate hand-lines: Work preset prefill, negative Fee/Credit, crystallization, invoice pool', async ({ page }) => {
  const workDesc = `${stamp} work line`;
  const feeDesc = `${stamp} credit line`;

  // A task-applicable preset is config, not a job/financials write —
  // configtime creates it (matches stamped-task-money.spec.js's
  // makeJobAndScheme). Built fresh, not hunted from the seed, so a
  // full-suite run can't land this on data another spec already mutated.
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  const category = (cats.results || cats)[0];
  const units = await configApi.get('/api/settings/units/');
  const unit = units.find((u) => u !== 'none' && u !== 'hour') || units[0];
  const scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp} scheme`, description: '', algorithm: 'entered_qty', rate: '45.00',
    unit_label: unit, accounting_category: category.id, modifiers: [],
  });
  await configApi.dispose();

  const setupApi = await apiAs(personas.finjobs);
  const contact = (await setupApi.get('/api/contacts/?page_size=1')).results[0];
  const job = await setupApi.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });
  // mark_open (below) refuses to send an estimate for a job with no
  // Deliverables — not the flow under test, so seeded via API.
  await setupApi.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: 'Finished piece', qty_ordered: '1', units: 'each',
  });
  const estimate = await setupApi.post('/api/estimates/', { job: job.job_id });
  await setupApi.dispose();

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
  await expect(page.getByText(`Estimate: ${estimate.estimate_number}`)).toBeVisible();

  await test.step('Add Work: the three-button footer offers "Add Work", and the preset dropdown stamps rate/unit', async () => {
    await page.getByRole('button', { name: 'Add line' }).click();
    const picker = page.getByLabel('Add line');
    await expect(picker.getByRole('button', { name: 'Add Work' })).toBeVisible();
    await expect(picker.getByRole('button', { name: 'Add Material' })).toBeVisible();
    await expect(picker.getByRole('button', { name: 'Add Fee-Credit' })).toBeVisible();
    await picker.getByRole('button', { name: 'Add Work' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByLabel('Preset')).toBeVisible();
    await dialog.getByLabel('Preset').selectOption({ label: scheme.name });

    // Picking the preset stamps its rate/unit into the still-editable fields
    // (EstimateAddLineForm's effect on rateSchemeId) — no scheme id is sent
    // on save, only the stamped values.
    await expect(dialog.getByLabel('Units')).toHaveValue(scheme.unit_label);
    await expect(dialog.getByLabel('Rate', { exact: true })).toHaveValue(String(scheme.rate));

    await dialog.getByLabel('Description').fill(workDesc);
    await dialog.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('The Work line appears with a Work badge and the stamped rate', async () => {
    const row = page.locator('tr', { hasText: workDesc });
    await expect(row).toBeVisible();
    await expect(row).toContainText('Work');
    await expect(row).toContainText(`$${scheme.rate}`);
  });

  await test.step('Add Fee/Credit: a negative amount shows the credit note and renders "-$" formatted', async () => {
    await page.getByRole('button', { name: 'Add line' }).click();
    const picker = page.getByLabel('Add line');
    await picker.getByRole('button', { name: 'Add Fee-Credit' }).click();

    const dialog = page.getByRole('dialog');
    // Preset picking is a Work-only affordance.
    await expect(dialog.getByLabel('Preset')).toHaveCount(0);
    await dialog.getByLabel('Description').fill(feeDesc);
    const amountField = dialog.getByLabel('Amount (negative for a credit)');
    await expect(dialog.getByText('This will appear as a credit.')).toHaveCount(0);
    await amountField.fill('-60');
    await expect(dialog.getByText('This will appear as a credit.')).toBeVisible();
    await dialog.getByLabel('Accounting Category').selectOption({ label: `${category.code} - ${category.name}` });

    await dialog.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('The Fee/Credit line renders with a Fee/Credit badge and "-$60.00"', async () => {
    const row = page.locator('tr', { hasText: feeDesc });
    await expect(row).toBeVisible();
    await expect(row).toContainText('Fee/Credit');
    await expect(row).toContainText('-$60.00');
  });

  await test.step('Accept the estimate (API — the pill-driven accept UI itself is covered by production-lifecycle/approval-and-pill.spec.js)', async () => {
    const acceptApi = await apiAs(personas.finjobs);
    await acceptApi.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await acceptApi.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
    await acceptApi.dispose();
  });

  let task;
  let fee;
  await test.step('Acceptance crystallized the Work line into a flat Task and the Fee line into a Fee', async () => {
    const readApi = await apiAs(personas.finjobs);
    const jobDetail = await readApi.get(`/api/jobs/${job.job_id}/`);
    await readApi.dispose();
    task = (jobDetail.tasks || []).find((t) => t.name === workDesc);
    fee = (jobDetail.fees || []).find((f) => f.description === feeDesc);
    expect(task, 'the Work hand-line should crystallize into a Task').toBeTruthy();
    expect(fee, 'the Fee hand-line should crystallize into a Fee').toBeTruthy();
  });

  await test.step('Task detail: the money block is present; the provenance chip shows the dash (no scheme, entered-qty flat task)', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks/${task.task_id}`);
    await expect(page.getByRole('heading', { name: workDesc })).toBeVisible();
    await expect(schemeChipOf(page)).toContainText('—');
    await expect(rateChipOf(page)).toContainText(`$${scheme.rate}/${scheme.unit_label}`);
  });

  await test.step("The credit Fee appears in the job's Fees section with a negative amount", async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    const feeRow = page.locator('tr.fee-row', { hasText: feeDesc });
    await expect(feeRow).toBeVisible();
    await expect(feeRow).toContainText('-$60.00');
  });

  await test.step('Invoice wizard: both the crystallized task and the credit fee are offered, the credit negative in the pool', async () => {
    // Completed via API so the task is truly billable (checkbox enabled),
    // not just present — the flow under test here is the pool's rendering,
    // not task completion (covered elsewhere).
    const taskApi = await apiAs(personas.finjobs);
    await taskApi.post(`/api/tasks/${task.task_id}/complete/`, { add_qty: '1' });
    await taskApi.dispose();

    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await page.getByRole('button', { name: 'Reconcile' }).click();

    // The crystallized task's own pool group is headed by its name and
    // holds its own atom row.
    await expect(page.locator('strong', { hasText: workDesc })).toBeVisible();
    const taskAtomRow = page.locator('label', { hasText: workDesc });
    await expect(taskAtomRow.getByRole('checkbox')).toBeEnabled();

    // The Fees group holds the credit atom, rendering its negative amount.
    await expect(page.getByText('Fees', { exact: true })).toBeVisible();
    const feeAtomRow = page.locator('label', { hasText: feeDesc });
    await expect(feeAtomRow.getByRole('checkbox')).toBeEnabled();
    await expect(feeAtomRow).toContainText('-$60.00');
  });
});
