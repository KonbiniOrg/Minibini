// Fee-removal plan Task 10 — the fee-less surfaces. The jobs.Fee model is
// deleted (fee-removal Tasks 1-9): the task-surface Add Work picker footer
// offers only Add Task / Add Material, a plain estimate hand-line (no atom
// source) crystallizes into NOTHING at acceptance, and the invoice edit
// view's uncovered-work pool has no Fees group — its subtitle names tasks,
// materials, and expenses only.
//
// Built fresh (job + draft estimate + one plain hand line) rather than
// hunted from the seed: no seeded job carries an accepted estimate whose
// only line is a plain hand-line, and the "acceptance created no task"
// assertion needs a job guaranteed to start with zero tasks — same "build
// it" precedent as estimate-gate-and-live-picker.spec.js and
// invoice-skeleton/seeded-invoice.spec.js (whose open/accept dance this
// mirrors, deliverable included).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-nofee-${Date.now().toString(36)}`;

test('fee-less surfaces: picker offers Task/Material only; a plain hand line reaches the invoice with no Fees section anywhere', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  // A NON-deposit category: a deposit AC would make every seeded line a
  // deposit line, flipping the draft into a deposit invoice — which hides
  // the uncovered-work section this spec asserts on.
  const category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit);
  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });

  await test.step('Add Work picker footer offers Add Task and Add Material — and no Add Fee', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    await page.getByRole('button', { name: 'Add Work' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('button', { name: 'Add Task', exact: true })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Add Material', exact: true })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Add Fee' })).toHaveCount(0);
    await dialog.getByRole('button', { name: 'Close' }).click();
  });

  const lineDescription = `${stamp} plain design retainer`;
  await test.step('API: draft estimate + one plain hand line (AC assigned), opened and accepted', async () => {
    const estimate = await api.post('/api/estimates/', { job: job.job_id });
    await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
      description: lineDescription, qty: '1', units: 'ea', price: '250.00',
      accounting_category: category.id,
    });
    // mark-open's send-gate requires a non-empty Deliverables list.
    await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
      description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
    });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
  });

  await test.step('Acceptance crystallized nothing: the job still has zero tasks', async () => {
    const tasks = await api.get(`/api/jobs/${job.job_id}/tasks/`);
    expect((tasks.results || tasks).length).toBe(0);
  });

  await test.step('The task list shows no Fees section and no rows for the plain line', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    await page.reload(); // same-fragment goto doesn't renavigate a hash router
    await expect(page.locator('table.task-tree-table')).toBeVisible();
    await expect(page.getByText('Fees', { exact: true })).toHaveCount(0);
    await expect(page.locator('table.task-tree-table tbody tr')).toHaveCount(0);
  });

  await test.step('Start Invoice: the fresh draft seeds the plain line from the agreement', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();
    await expect(
      page.locator('table.line-items-table tr').filter({ hasText: lineDescription })
    ).toBeVisible();
  });

  await test.step('Uncovered work reads the fee-less copy and shows no Fees group', async () => {
    const section = page.locator('.uncovered-work-section');
    await expect(section.getByText(
      'Tasks, materials, and expenses from this job not yet on this invoice.'
    )).toBeVisible();
    await expect(section.getByText('Fees', { exact: true })).toHaveCount(0);
    await expect(section.getByText('[fee]')).toHaveCount(0);
  });

  await api.dispose();
});
