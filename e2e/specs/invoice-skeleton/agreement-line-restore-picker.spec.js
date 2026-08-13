// better-fees skeleton phase fix-wave — the "Add from agreement…" restore
// picker (GET /api/invoices/{id}/remaining-agreement-lines/ +
// POST .../restore-line/) is the PERSISTENT alternative to the session-only
// in-table restore path that seeded-invoice.spec.js once exercised: struck rows
// lives only in InvoiceEditView's local `removedRefs` state, so a reload (or
// a mode flip) loses it. This spec proves the server-backed picker survives
// exactly that: remove a seeded line, reload the page to kill the
// session-local struck row, then bring the line back via the picker instead.
//
// Sibling file (not appended to seeded-invoice.spec.js) so the reload here
// can't interact with that spec's own remove/restore/customer-mode/send-gate
// steps, which all assume one continuous page session.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-restore-${Date.now().toString(36)}`;

test('Add from agreement picker: remove a line, reload, restore it from the picker', async ({ page }) => {
  const api = await apiAs(personas.finjobs);

  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });

  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const scheme = (schemes.results || schemes)
    .find((s) => s.algorithm === 'entered_qty' && s.is_active !== false);
  test.skip(!scheme, 'seed gap: no active entered_qty rate scheme');

  const taskName = `${stamp} task`;
  const task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: taskName, rate_scheme: scheme.rate_scheme_id, est_qty: '3',
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  const line = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: task.task_id }],
  });

  // mark-open's send-gate requires a non-empty Deliverables list.
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
  await api.dispose();

  await test.step('Start Invoice auto-seeds the one agreement line', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();
  });

  // Scoped to the line's own row (carries a BackingChip), not the nested
  // AtomChildRow underneath it — same convention as seeded-invoice.spec.js.
  const lineRow = () => page.locator('table.line-items-table tr')
    .filter({ hasText: line.description }).filter({ has: page.locator('.backing-chip') });
  const addFromAgreementBtn = () => page.getByRole('button', { name: /Add from agreement/ });

  await test.step('No picker button while the invoice already carries every agreement line', async () => {
    await expect(lineRow()).toBeVisible();
    await expect(addFromAgreementBtn()).toHaveCount(0);
  });

  await test.step('Remove the line: no struck row — the picker button appears immediately (RM 2026-08-12)', async () => {
    await lineRow().getByRole('button', { name: 'Remove from invoice' }).click();
    await expect(lineRow()).toHaveCount(0);
    await expect(page.locator('tr.doc-offdoc')).toHaveCount(0);
    await expect(addFromAgreementBtn()).toBeVisible();
  });

  await test.step('The picker lists the removed line and adds it back on this invoice', async () => {
    await addFromAgreementBtn().click();
    const dialog = page.getByRole('dialog', { name: 'Add from agreement' });
    await expect(dialog).toBeVisible();
    const pickerRow = dialog.locator('tr').filter({ hasText: line.description });
    await expect(pickerRow).toBeVisible();

    await pickerRow.getByRole('button', { name: 'Add to this invoice' }).click();
    await expect(pickerRow).toHaveCount(0);

    await dialog.getByRole('button', { name: 'Close' }).click();
    await expect(dialog).toBeHidden();
  });

  await test.step('The line is back on the invoice and the picker button is gone again', async () => {
    await expect(lineRow()).toBeVisible();
    await expect(addFromAgreementBtn()).toHaveCount(0);
  });

  const finalApi = await apiAs(personas.finjobs);
  const finalInvoice = await finalApi.get(`/api/invoices/?job=${job.job_id}`);
  await finalApi.dispose();
  const draft = (finalInvoice?.results || finalInvoice || []).find((i) => i.status === 'draft');
  expect(draft).toBeTruthy();
  expect(draft.line_items.some((li) => li.description === line.description)).toBe(true);
});
