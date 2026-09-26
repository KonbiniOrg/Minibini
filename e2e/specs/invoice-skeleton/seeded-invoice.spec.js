// better-fees skeleton phase, Task 12/14 — a fresh invoice draft is
// auto-seeded from the job's agreement-of-record (compose_agreement) at
// creation time (apps.invoicing.services.InvoiceWizardService.open_for_job,
// seed=True by default) — no more separate "Apply everything"/"Copy from
// estimate" seed buttons the manager has to click. This spec drives that
// through the UI: Start Invoice on a job with an accepted estimate lands on
// a draft whose lines already carry the estimate's values, one line backed
// by a just-completed task showing the "actuals" BackingChip (its mirrored
// source is in sync with the line's price), a sibling line whose task is
// still untouched showing "estimate". It then exercises Remove + picker restore,
// confirms Customer mode strips all controls, and reaches the Send gate.
//
// Built fresh (job + 2 tasks + accepted estimate) rather than hunted from
// the seed: the "actuals" chip needs a task completed with actual qty
// EXACTLY equal to what the estimate line quoted, which only an
// ENTERED_QTY task lets us pin deterministically (add_qty), and no seeded
// accepted-estimate job carries a still-pending ENTERED_QTY single-task
// line (checked — the seed's accepted-estimate jobs are elapsed_time-only
// there) — same "build it" precedent as add-line-and-work-authoring's
// hour-unit-task.spec.js and estimate-gate-and-live-picker.spec.js.
//
// QBO is not connected in this env (docs/designs/e2e-testing.md §3 — the
// seed deliberately represents "not connected"), so the actual push is not
// e2e-reachable (same exemption as struck-from-agreement-badge.spec.js's
// deposit-credit send confirm) — the send step here proves the gate is
// reachable and asserts the documented failure mode, not a delivered email.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-seed-${Date.now().toString(36)}`;

test('seeded invoice: agreement-backed lines, actuals vs estimate backing, remove/restore, customer mode, send gate', async ({ page }) => {
  const api = await apiAs(personas.finjobs);

  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });

  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const scheme = (schemes.results || schemes)
    .find((s) => s.algorithm === 'entered_qty' && s.is_active !== false);
  test.skip(!scheme, 'seed gap: no active entered_qty rate scheme');

  const targetName = `${stamp} target task`;
  const otherName = `${stamp} other task`;
  const targetTask = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: targetName, rate_scheme: scheme.rate_scheme_id, est_qty: '4',
  });
  const otherTask = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: otherName, rate_scheme: scheme.rate_scheme_id, est_qty: '2',
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  const targetLine = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: targetTask.task_id }],
  });
  const otherLine = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: otherTask.task_id }],
  });

  // mark-open's send-gate requires a non-empty Deliverables list.
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

  // Complete the target task with add_qty == its own est_qty (nothing else
  // has touched the task since the line was created) — the mirrored source
  // then computes to EXACTLY the line's price*qty, so the invoice line
  // reads "in sync" (backing 'actuals') rather than 'edited'.
  await api.post(`/api/tasks/${targetTask.task_id}/complete/`, { add_qty: '4' });
  await api.dispose();

  await test.step('Start Invoice auto-seeds from the agreement — no seed buttons needed', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Apply everything' })).toHaveCount(0);
  });

  // Scoped to rows carrying a BackingChip — the parent line row, never the
  // nested AtomChildRow underneath it (same description text, no chip) —
  // so each locator stays a strict-mode-safe single match.
  const targetRow = () => page.locator('table.line-items-table tr')
    .filter({ hasText: targetLine.description }).filter({ has: page.locator('.backing-chip') });
  const otherRow = () => page.locator('table.line-items-table tr')
    .filter({ hasText: otherLine.description }).filter({ has: page.locator('.backing-chip') });

  await test.step('The completed task\'s line is pre-filled and backed by actuals', async () => {
    await expect(targetRow()).toBeVisible();
    await expect(targetRow().locator('.backing-chip')).toContainText('actuals');
  });

  await test.step('The untouched sibling line is pre-filled and still backed by the estimate', async () => {
    await expect(otherRow()).toBeVisible();
    await expect(otherRow().locator('.backing-chip')).toHaveText('estimate');
  });

  await test.step('Remove a line: it drops clean (no struck row); Add from agreement restores it', async () => {
    await otherRow().getByRole('button', { name: 'Remove from invoice' }).click();
    await expect(otherRow()).toHaveCount(0);
    await expect(page.locator('tr.doc-offdoc')).toHaveCount(0);

    await page.getByRole('button', { name: /Add from agreement/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Add from agreement' });
    await dialog.locator('tr').filter({ hasText: otherLine.description })
      .getByRole('button', { name: 'Add to this invoice' }).click();
    await dialog.getByRole('button', { name: 'Close' }).click();
    await expect(dialog).toBeHidden();
    await expect(otherRow()).toBeVisible();
  });

  await test.step('Customer mode shows the collapsed doc with no controls', async () => {
    await page.getByRole('button', { name: 'Customer' }).click();
    const view = page.locator('.doc-customer-view');
    await expect(view).toContainText(targetLine.description);
    await expect(view).toContainText(otherLine.description);
    await expect(view.getByRole('button')).toHaveCount(0);
    await expect(view.getByRole('checkbox')).toHaveCount(0);
    await page.locator('.doc-mode-bar').getByRole('button', { name: 'Edit' }).click();
  });

  await test.step('Send Invoice is reachable (every seeded line already carries a category)', async () => {
    await expect(page.getByText('Assign an accounting category to every line before sending.')).toHaveCount(0);
    await page.getByRole('link', { name: 'Send Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Send Invoice' })).toBeVisible();
    await page.getByLabel('To *').fill('e2e-invoice-send@example.invalid');
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Send Invoice' }).click();
    // No QBO connection in this env — the push fails server-side and the
    // invoice stays draft; this proves the gate is reachable, not that
    // delivery happened (see the file header note). FormMessage renders the
    // failure as role="alert".
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 15_000 });
  });

  const finalApi = await apiAs(personas.finjobs);
  const finalInvoice = await finalApi.get(`/api/invoices/?job=${job.job_id}`);
  await finalApi.dispose();
  const draft = (finalInvoice?.results || finalInvoice || []).find((i) => i.status === 'draft');
  expect(draft).toBeTruthy();
});
