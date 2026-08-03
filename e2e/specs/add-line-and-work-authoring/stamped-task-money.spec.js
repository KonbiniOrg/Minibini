// task-owned-money Phase 1 (Task 12): manual task creation stamps a
// permanent copy of the picked preset's money fields onto the task server-
// side (Task.stamp_from_scheme). A non-manager (worker) picks the preset —
// that's open to everyone — but never sees an editable rate/unit/category
// input at create time, only a read-only preview and (if the scheme carries
// a modifier) a disabled checkbox: active_modifiers is a MONEY_FIELD.
// A manager/PM CAN edit the task's own stamped rate afterward, and doing so
// never disturbs the provenance (the Scheme chip keeps naming the preset it
// was stamped from). See frontend/src/components/WorkItemForm.svelte
// (effectiveCanManage / MONEY_FIELDS) and TaskDetailPage.svelte (stat chips).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-stm-${Date.now().toString(36)}`;

async function makeJobAndScheme(name) {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  const units = await configApi.get('/api/settings/units/');
  const unit = units.find((u) => u !== 'none' && u !== 'hour') || units[0];
  const scheme = await configApi.post('/api/rate-schemes/', {
    name, description: '', algorithm: 'entered_qty', rate: '18',
    unit_label: unit, accounting_category: (cats.results || cats)[0].id,
    modifiers: [{ key: 'rush', label: 'Rush', percent: 25 }],
  });
  await configApi.dispose();

  const jobsApi = await apiAs(personas.finjobs);
  const contact = (await jobsApi.get('/api/contacts/?page_size=1')).results[0];
  const job = await jobsApi.post('/api/jobs/', {
    name: `${name} job`, contact: contact.contact_id,
  });
  await jobsApi.dispose();
  return { job, scheme };
}

const schemeChipOf = (page) => page.locator('.stat-chip', {
  has: page.locator('.stat-chip-header', { hasText: 'Scheme' }),
});
const rateChipOf = (page) => page.locator('.stat-chip', {
  has: page.locator('.stat-chip-header', { hasText: 'Rate' }),
});

test.describe('worker creates a stamped task — no money inputs', () => {
  test.use({ storageState: personas.worker.storageState });

  test('picking a preset shows a read-only rate preview and a disabled modifier checkbox, no editable money fields', async ({ page }) => {
    const { job, scheme } = await makeJobAndScheme(`${stamp}-worker`);
    const taskName = `${stamp} worker task`;

    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    await page.getByRole('button', { name: 'Add Work' }).click();
    // The picker's freeform lane: "Add Task" opens WorkItemForm in manual mode.
    await page.getByLabel('Add line').getByRole('button', { name: 'Add Task' }).click();

    // Picking a preset IS open to a worker (stamp-only creation).
    await page.getByLabel('Rate Scheme *').selectOption({ label: scheme.name });
    await page.getByLabel('Name *').fill(taskName);

    // No editable rate/unit/category controls anywhere on the create form —
    // only the read-only preview text (money fields are server-stamped).
    await expect(page.getByText(`Rate: $${scheme.rate}/${scheme.unit_label}`)).toBeVisible();
    await expect(page.getByLabel('Rate', { exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Unit', { exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Accounting Category', { exact: true })).toHaveCount(0);

    // The scheme's modifier IS offered (a worker can activate it on the
    // task), but as a disabled checkbox: writing active_modifiers requires
    // CanManageJobOrPM/financials, which this persona lacks.
    const modifierCheckbox = page.getByRole('checkbox', { name: /Rush \(\+25%\)/ });
    await expect(modifierCheckbox).toBeVisible();
    await expect(modifierCheckbox).toBeDisabled();

    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // The stamping happened server-side regardless of who created the task —
    // task detail shows the preset's rate and provenance even though the
    // worker never touched a money field directly.
    await page.getByRole('button', { name: taskName }).click();
    await expect(page.getByRole('heading', { name: taskName })).toBeVisible();
    await expect(schemeChipOf(page)).toContainText(scheme.name);
    await expect(rateChipOf(page)).toContainText(`$${scheme.rate}/${scheme.unit_label}`);
  });
});

test.describe('PM edits the stamped rate', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('editing the task rate updates the Rate chip and keeps the Scheme provenance', async ({ page }) => {
    const { job, scheme } = await makeJobAndScheme(`${stamp}-pm`);
    const taskName = `${stamp} pm task`;

    const api = await apiAs(personas.finjobs);
    const task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
      name: taskName, description: '', rate_scheme: scheme.rate_scheme_id,
    });
    await api.dispose();

    await page.goto(`/#/jobs/${job.job_id}/tasks/${task.task_id}`);
    await expect(page.getByRole('heading', { name: taskName })).toBeVisible();
    await expect(schemeChipOf(page)).toContainText(scheme.name);
    await expect(rateChipOf(page)).toContainText(`$${scheme.rate}/${scheme.unit_label}`);

    await page.getByRole('button', { name: 'Edit Task' }).click();
    const newRate = (Number(scheme.rate) + 5).toFixed(2);
    await page.getByLabel('Rate', { exact: true }).fill(newRate);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // The task's own rate moved...
    await expect(rateChipOf(page)).toContainText(`$${newRate}/${scheme.unit_label}`);
    // ...but the provenance chip still names the original preset — editing
    // a task's stamped money never re-points or clears source_scheme.
    await expect(schemeChipOf(page)).toContainText(scheme.name);
  });
});
