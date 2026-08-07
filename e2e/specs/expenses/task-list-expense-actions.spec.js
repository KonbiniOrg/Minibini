// docs/ui-flows/Expenses.md §4 — the Task list's "Expenses" section now
// offers inline delete/reject, not just edit (2026-08-07). The flow under
// test is these two actions; expense creation is backdrop, done via the API
// (docs/designs/e2e-testing.md §2 layering rule).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

// A fresh job per test keeps its Expenses section to exactly the one row
// under test (no seed/other-test rows to disambiguate against).
async function freshJob(label) {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  const category = (cats.results || cats)[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} ${label}`, contact: contact.contact_id,
  });
  await api.dispose();
  return { jobId: job.job_id, categoryId: category.accounting_category_id ?? category.id };
}

async function makeExpense(jobId, categoryId, tag) {
  const api = await apiAs(personas.finjobs);
  const me = await api.get('/api/auth/me/');
  const exp = await api.post('/api/expenses/', {
    amount: '10.00',
    purchased_on: new Date().toISOString().slice(0, 10),
    accounting_category: categoryId,
    payment_method: 'personal',
    purchased_by: me.id,
    job: jobId,
    description: `${stamp} ${tag}`,
  });
  await api.dispose();
  return exp;
}

test('§4 delete an expense inline from the Task list', async ({ page }) => {
  const { jobId, categoryId } = await freshJob('delete');
  const exp = await makeExpense(jobId, categoryId, 'to-delete');

  await page.goto(`/#/jobs/${jobId}/tasks`);
  const row = page.getByRole('row', { name: new RegExp(exp.description) });
  await expect(row).toBeVisible();

  page.on('dialog', (d) => d.accept());
  await row.getByRole('button', { name: 'delete' }).click();

  await expect(page.getByRole('row', { name: new RegExp(exp.description) })).toHaveCount(0);

  const api = await apiAs(personas.finjobs);
  const list = await api.get(`/api/expenses/?job=${jobId}`);
  await api.dispose();
  expect((list.results || list).some((e) => e.id === exp.id)).toBe(false);
});

test('§4 reject a personal/submitted expense inline from the Task list', async ({ page }) => {
  const { jobId, categoryId } = await freshJob('reject');
  const exp = await makeExpense(jobId, categoryId, 'to-reject');

  await page.goto(`/#/jobs/${jobId}/tasks`);
  const row = page.getByRole('row', { name: new RegExp(exp.description) });
  await expect(row.getByRole('button', { name: 'reject' })).toBeVisible();

  page.on('dialog', (d) => d.accept());
  await row.getByRole('button', { name: 'reject' }).click();

  // Rejecting doesn't delete the row — the button just goes away (no longer
  // submitted), and it stays deletable (not invoiced/reimbursed).
  await expect(row.getByRole('button', { name: 'reject' })).toHaveCount(0);
  await expect(row.getByRole('button', { name: 'delete' })).toBeVisible();

  const api = await apiAs(personas.finjobs);
  const list = await api.get(`/api/expenses/?job=${jobId}`);
  await api.dispose();
  const updated = (list.results || list).find((e) => e.id === exp.id);
  expect(updated.status).toBe('rejected');
});
