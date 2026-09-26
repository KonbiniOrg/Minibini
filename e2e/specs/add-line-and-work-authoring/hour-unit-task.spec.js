// The hour-unit arc (.superpowers/sdd/hour-unit-plan): elapsed_time schemes
// are pinned to unit 'hour' (apps/core/units.py HOUR_UNIT); WorkItemForm
// collapses est_qty and est_worker_time into a single "Estimated hours"
// input for hour-unit schemes; the backend pair-fills est_qty from
// est_worker_time (and vice versa) so a task built this way already carries
// an est_worker_time by the time it reaches Assign — no separate
// worker-time prompt. This spec walks the whole arc end to end.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-hu-${Date.now().toString(36)}`;

test('hour-unit task: single Estimated-hours input, one estimate shown, assign needs no worker-time prompt', async ({ page }) => {
  // Built fresh rather than hunted from the seed — a full-suite run must not
  // be able to land this on a job or scheme another spec already mutated
  // (the deposit-creation LATER note:
  // e2e/specs/deposits/deposit-creation.spec.js).
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });
  const users = await api.get('/api/auth/users/');
  const worker = users.find((u) => u.username === personas.worker.username);
  await api.dispose();

  // Rate schemes are config, not a job/financials write — configtime (which
  // carries can_manage_config) creates it, matching rate-scheme-modal.spec.js.
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  const scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp} scheme`, description: '', algorithm: 'elapsed_time', rate: '90',
    unit_label: 'hour', modifiers: [], accounting_category: (cats.results || cats)[0].id,
  });
  // Backend pins elapsed_time schemes to 'hour' regardless of payload.
  expect(scheme.unit_label).toBe('hour');
  await configApi.dispose();
  test.skip(!worker, 'seed gap: the worker persona user is missing from /api/auth/users/');

  const taskName = `${stamp} task`;

  await test.step('Manual task on the hour-unit scheme: single "Estimated hours" input, no qty spinner', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    await page.getByRole('button', { name: 'Add Work' }).click();
    // The picker's freeform lane: "Add Task" opens WorkItemForm in manual mode.
    await page.getByLabel('Add line').getByRole('button', { name: 'Add Task' }).click();

    await page.getByLabel('Rate Scheme *').selectOption({ label: scheme.name });
    await page.getByLabel('Name *').fill(taskName);

    await expect(page.getByText('Estimated qty')).toHaveCount(0);
    const hoursField = page.getByLabel('Estimated hours');
    await expect(hoursField).toBeVisible();
    await hoursField.fill('2:00');

    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('Task list shows the 2h estimate and the Est Qty with its unit inline', async () => {
    const row = page.locator('tr', { hasText: taskName });
    await expect(row).toBeVisible();
    await expect(row.getByText('2h', { exact: true })).toBeVisible();
    // Hour-unit tasks show Est Qty like every other unit, even though it
    // restates Est Time (backend pair-fills them) — the old
    // duplicate-suppression '-' read as missing data (RM 2026-08-06).
    await expect(row.getByText('2.00 hour', { exact: true }).first()).toBeVisible();
    await page.getByRole('button', { name: taskName }).click();
  });

  await test.step('Task detail shows both Est Time and Est Qty chips (pair-filled, both visible)', async () => {
    await expect(page.getByRole('heading', { name: taskName })).toBeVisible();
    await expect(page.getByText('Est Time')).toBeVisible();
    await expect(page.getByText('2h 0m')).toBeVisible();
    await expect(page.getByText('Est Qty')).toBeVisible();
  });

  await test.step('Assign to a worker: no worker-time prompt (est_worker_time already pair-filled)', async () => {
    const assigneeChip = page.locator('.stat-chip', {
      has: page.locator('.stat-chip-header', { hasText: 'Assignee' }),
    });
    await assigneeChip.getByRole('button', { name: 'Unassigned' }).click();

    const assignDialog = page.getByRole('dialog');
    await expect(assignDialog.getByRole('heading', { name: `Assign Task: ${taskName}` })).toBeVisible();
    // The duration field only renders when the task has no est_worker_time —
    // assert it stays absent through the pick, not just before it.
    await expect(assignDialog.getByText('Estimated worker time')).toHaveCount(0);
    await assignDialog.getByLabel('Assignee').selectOption({ label: `${worker.name} (${worker.username})` });
    await expect(assignDialog.getByText('Estimated worker time')).toHaveCount(0);

    await assignDialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(assigneeChip.getByRole('button', { name: worker.name })).toBeVisible();
  });
});
