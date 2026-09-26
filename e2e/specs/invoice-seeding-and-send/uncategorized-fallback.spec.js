// Phase 3 (nullable AC + fallback), Task 9 — a Task's own accounting
// category can be nulled out (cleared post-create; creation always stamps
// one from the picked RateScheme — apps/api/tasks/serializers.py
// MONEY_FIELDS, writable by CanManageJobOrPM/can_manage_financials only).
// The estimate/CO wizards carry that null through unchanged (Base
// WizardService._resolve_line_category is the identity hook there), so a
// line built from a null-AC atom is itself uncategorized. Only at invoice
// authoring time — seeding from the agreement, restoring a removed line, or
// copy-from-estimate — does InvoiceWizardService stamp the configured
// fallback AccountingCategory onto it (apps/invoicing/services.py
// InvoiceService.resolve_line_category / _agreement_category_id). The
// stamped line is flagged `used_fallback_ac` and the invoice Edit view
// (InvoiceEditView.svelte) renders the amber "uncategorized → {name} ·
// taxable|non-taxable" chip; correcting the line's AC through the Edit…
// modal (LineItemModal) clears it since the flag is a live AC-id comparison,
// not a sticky provenance mark. Since the fallback stamp gives every seeded
// line a REAL (if wrong) category, the send gate is never tripped by
// fallback-stamped lines — a manager corrects them at their own pace.
//
// This spec also exercises the Settings → Accounting page's "Fallback
// Accounting Category" block (FallbackCategorySetting.svelte, Task 2's UI
// surface) end to end: a configtime persona picks a category there and
// saves it, and that's the value the rest of the flow depends on.
//
// Built fresh (job + 2 tasks + accepted estimate), same precedent as
// invoice-skeleton/seeded-invoice.spec.js — an ENTERED_QTY task's line can
// be authored from atoms without completing any work first, and nulling a
// task's AC needs a task this spec controls end to end.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-fbac-${Date.now().toString(36)}`;

test('null-AC task line seeds the uncategorized→fallback chip; correcting it via Edit clears the chip; the send gate stays clear', async ({ page, browser }) => {
  const api = await apiAs(personas.finjobs);

  // ── Categories: the fallback needs to differ from the category the
  // rate scheme (and so both tasks, before either is nulled) is stamped
  // with — otherwise the untouched "clean" line would coincidentally read
  // as fallback-stamped (used_fallback_ac is a bare AC-id comparison, not
  // provenance) even though it was never routed through the fallback.
  const catData = await api.get('/api/accounting-categories/');
  const activeCats = (catData.results || catData)
    .filter((c) => c.is_active !== false && !c.is_deposit);

  // If the seed (or a prior run, within this same fresh-DB run) already
  // configured a fallback, re-save that same value on the Settings page —
  // still exercises the UI surface — rather than picking a fresh one.
  const configApi0 = await apiAs(personas.configtime);
  const existingSettings = await configApi0.get('/api/settings/');
  await configApi0.dispose();
  const existingFallbackId = existingSettings.fallback_accounting_category
    ? Number(existingSettings.fallback_accounting_category) : null;
  const fallbackCat = activeCats.find((c) => c.id === existingFallbackId) || activeCats[0];
  const taskCat = activeCats.find((c) => c.id !== fallbackCat?.id);
  test.skip(!fallbackCat || !taskCat, 'seed gap: need 2+ active non-deposit accounting categories');

  // ── Step 1 (configtime, via the Settings page — UI coverage for Task 2):
  // designate the fallback accounting category.
  const configCtx = await browser.newContext({ storageState: personas.configtime.storageState });
  const configPage = await configCtx.newPage();
  await test.step('Settings → Accounting: designate the fallback accounting category', async () => {
    await configPage.goto('http://localhost:9100/#/settings');
    const fieldset = configPage.getByRole('group', { name: 'Fallback Accounting Category' });
    await expect(fieldset).toBeVisible();
    await fieldset.locator('#fallback-accounting-category').selectOption({ label: fallbackCat.name });
    await fieldset.getByRole('button', { name: 'Save' }).click();
    await expect(fieldset.getByText('Fallback accounting category saved.')).toBeVisible();
  });
  await configCtx.close();

  const configApi = await apiAs(personas.configtime);
  const settingsAfterSave = await configApi.get('/api/settings/');
  expect(Number(settingsAfterSave.fallback_accounting_category)).toBe(fallbackCat.id);

  // ── Step 2 (finjobs, API): job + two tasks stamped from an entered_qty
  // scheme whose own accounting_category is taskCat (deliberately not the
  // fallback) — then null out ONE task's AC post-create (money-writer path;
  // finjobs qualifies via can_manage_financials).
  const units = await configApi.get('/api/settings/units/');
  const unit = units.find((u) => u !== 'none' && u !== 'hour') || units[0];
  const scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp} scheme`, description: '', algorithm: 'entered_qty', rate: '25',
    unit_label: unit, accounting_category: taskCat.id, modifiers: [],
  });
  await configApi.dispose();

  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });

  const flaggedTaskName = `${stamp} flagged task`;
  const cleanTaskName = `${stamp} clean task`;
  const flaggedTask = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: flaggedTaskName, rate_scheme: scheme.rate_scheme_id, est_qty: '3',
  });
  const cleanTask = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: cleanTaskName, rate_scheme: scheme.rate_scheme_id, est_qty: '2',
  });
  expect(flaggedTask.accounting_category).toBe(taskCat.id);

  const clearedTask = await api.patch(`/api/jobs/${job.job_id}/tasks/${flaggedTask.task_id}/`, {
    accounting_category: null,
  });
  expect(clearedTask.accounting_category).toBeNull();

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  const flaggedLine = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: flaggedTask.task_id }],
  });
  const cleanLine = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: cleanTask.task_id }],
  });
  // Sanity on the estimate side, before invoice seeding ever touches it:
  // the wizard carries the task's null AC straight onto the line, and
  // leaves the untouched task's real category alone.
  expect(flaggedLine.accounting_category).toBeNull();
  expect(cleanLine.accounting_category).toBe(taskCat.id);

  // mark-open's send-gate requires a non-empty Deliverables list.
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
  await api.dispose();

  // Rows scoped to the BackingChip — the parent line row, never the nested
  // AtomChildRow underneath it (same description text, no chip) — same
  // precedent as invoice-skeleton/seeded-invoice.spec.js.
  const flaggedRow = () => page.locator('table.line-items-table tr')
    .filter({ hasText: flaggedTaskName }).filter({ has: page.locator('.backing-chip') });
  const cleanRow = () => page.locator('table.line-items-table tr')
    .filter({ hasText: cleanTaskName }).filter({ has: page.locator('.backing-chip') });

  await test.step('Start Invoice auto-seeds from the agreement — the null-AC line lands fallback-stamped', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();

    await expect(flaggedRow()).toBeVisible();
    await expect(cleanRow()).toBeVisible();

    const taxability = fallbackCat.taxable ? 'taxable' : 'non-taxable';
    await expect(flaggedRow().locator('.uncategorized-chip'))
      .toHaveText(`uncategorized → ${fallbackCat.name} · ${taxability}`);
    await expect(cleanRow().locator('.uncategorized-chip')).toHaveCount(0);
  });

  await test.step('Correcting the flagged line\'s AC via Edit… clears the chip', async () => {
    await flaggedRow().getByRole('button', { name: /^Edit/ }).click();
    const modal = page.getByRole('dialog');
    await expect(modal.getByRole('heading', { name: 'Edit Line Item' })).toBeVisible();
    await modal.getByLabel(/Accounting Category/)
      .selectOption({ label: `${taskCat.code} - ${taskCat.name}` });
    await modal.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await expect(flaggedRow().locator('.uncategorized-chip')).toHaveCount(0);
    await expect(cleanRow().locator('.uncategorized-chip')).toHaveCount(0);
  });

  await test.step('API: the corrected line moved to taskCat; the untouched line kept its own AC; nothing is left uncategorized (the send gate is not the blocker)', async () => {
    const finalApi = await apiAs(personas.finjobs);
    const invoicesResp = await finalApi.get(`/api/invoices/?job=${job.job_id}`);
    const draft = (invoicesResp.results || invoicesResp).find((i) => i.status === 'draft');
    expect(draft).toBeTruthy();
    const detail = await finalApi.get(`/api/invoices/${draft.invoice_id}/`);
    await finalApi.dispose();

    const flaggedInvLine = detail.line_items.find((li) => li.description === flaggedTaskName);
    const cleanInvLine = detail.line_items.find((li) => li.description === cleanTaskName);

    expect(flaggedInvLine.accounting_category).toBe(taskCat.id);
    expect(flaggedInvLine.used_fallback_ac).toBe(false);
    expect(cleanInvLine.accounting_category).toBe(taskCat.id);
    expect(cleanInvLine.used_fallback_ac).toBe(false);

    // Send is not e2e-reachable (no QBO connection in this env, same
    // exemption as invoice-skeleton/seeded-invoice.spec.js) — the send
    // gate specifically checks for a null accounting_category on any
    // line, so proving every line now carries a real one is the
    // equivalent assertion that fallback-stamped lines never block it.
    expect(detail.line_items.every((li) => li.accounting_category != null)).toBe(true);
  });
});
