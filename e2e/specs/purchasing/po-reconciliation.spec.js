// docs/ui-flows/Purchasing.md §1-§8 — the outsourced-work / service-PO flow
// (task-owned-money Phase 5, spec §7 of docs/plans/2026-08-02-task-owned-money.md):
// a PO line linked to a top-level flat task (task-link picker), issue,
// receive-all, the awaiting-reconciliation nudge (badge + list filter),
// PO-level reconciliation (bill total, vendor ref, per-line final price,
// an invoice-only appended line + the persisted-line removal notice), the
// resulting task-rate prompt (accept updates the task's rate; decline is a
// no-op — resolved independently on a second line of the SAME po, the
// "cheapest arrangement" for exercising both branches), and the invoice
// wizard's live (uncached) read of the task's rate afterward.
//
// One continuous test: every section after §1 depends on state built by the
// one before it (same PO, same two tasks), so test.step() mirrors the doc's
// section numbers rather than splitting into independent test()s.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-por-${Date.now().toString(36)}`;

const rateChipOf = (page) => page.locator('.stat-chip', {
  has: page.locator('.stat-chip-header', { hasText: 'Rate' }),
});

// The global success/error toast (MessageOverlay.svelte) sits at --z-toast
// (1000), ABOVE even a modal (--z-modal-nested: 900), and never
// auto-dismisses or clears on SPA navigation (stores/messages.js has no
// route hook) — so it silently intercepts pointer events on whatever comes
// next (a later button, or a modal that opens moments later, e.g. the
// rate-prompt dialog right after reconcile's own success toast) until
// dismissed. Idempotent: a no-op when no overlay is showing.
async function dismissOverlay(page) {
  // A short bounded wait, not a `.count()` snapshot: the toast can still be
  // mid-render (a microtask behind the assertion that preceded this call),
  // so an immediate count() races it and reads 0. A short click-timeout
  // both waits for a late-arriving toast and is a clean no-op when none
  // shows at all.
  try {
    await page.getByRole('button', { name: 'Dismiss message' }).click({ timeout: 3000 });
  } catch {
    // no overlay showing — nothing to dismiss
  }
}

test.use({ storageState: personas.finjobs.storageState });

test('§1-§8 PO task-link -> issue -> receive -> reconcile -> rate prompt -> invoice wizard', async ({ page }) => {
  test.setTimeout(120_000);
  const api = await apiAs(personas.finjobs);

  // ---- Backdrop (not the flow under test): vendor business, job, a flat
  // task-applicable rate scheme. Same precedent as
  // specs/invoicing/uncategorized-fallback.spec.js and
  // specs/add-line-and-work-authoring/stamped-task-money.spec.js — job/scheme
  // setup is API-driven; the reconciliation flow itself is UI-driven below.
  const business = (await api.get('/api/businesses/?page_size=1')).results[0];
  test.skip(!business, 'seed gap: no Business to use as PO vendor');

  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} outsourced job`, contact: contact.contact_id,
  });
  await api.patch(`/api/jobs/${job.job_id}/`, { status: 'submitted' });
  await api.patch(`/api/jobs/${job.job_id}/`, { status: 'approved' });

  // A non-hour task-applicable scheme is guaranteed entered_qty (RateScheme.
  // clean() ties elapsed_time to unit_label='hour') -- same derivation as
  // uncategorized-fallback.spec.js.
  const schemesResp = await api.get('/api/rate-schemes/?task_applicable=true');
  const schemes = schemesResp.results || schemesResp;
  const flatScheme = schemes.find((s) => s.unit_label !== 'hour');
  test.skip(!flatScheme, 'seed gap: no non-hour task-applicable rate scheme');

  const task1Name = `${stamp} outsourced task 1 (accept)`;
  const task2Name = `${stamp} outsourced task 2 (decline)`;

  async function createTaskViaUI(name) {
    await page.goto(`/#/jobs/${job.job_id}/tasks`);
    await page.getByRole('button', { name: 'Add Work' }).click();
    await page.getByLabel('Add line').getByRole('button', { name: 'Add Task' }).click();
    await page.getByLabel('Rate Scheme *').selectOption({ label: flatScheme.name });
    await page.getByLabel('Name *').fill(name);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  }

  await test.step('Setup: two outsourced flat tasks on the job', async () => {
    await createTaskViaUI(task1Name);
    await createTaskViaUI(task2Name);
  });

  const detail = await api.get(`/api/jobs/${job.job_id}/`);
  const task1 = detail.tasks.find((t) => t.name === task1Name);
  const task2 = detail.tasks.find((t) => t.name === task2Name);
  expect(task1).toBeTruthy();
  expect(task2).toBeTruthy();

  const po = await api.post('/api/purchase-orders/', { business: business.business_id });

  const line1Desc = `${stamp} outsourced line 1`;
  const line2Desc = `${stamp} outsourced line 2`;

  async function addLineItemViaUI(description, taskName) {
    await page.getByRole('button', { name: 'Add Line Item' }).click();
    await page.getByLabel('Description').fill(description);
    await page.getByLabel('Qty').fill('1');
    await page.getByLabel('Price').fill('20.00');

    const picker = page.locator('.task-link-picker');
    await picker.getByPlaceholder('Search jobs…').fill(job.job_number);
    await page.getByRole('listbox').getByRole('button', { name: job.job_number }).click();
    const taskSelect = picker.getByLabel('Task');
    await expect(taskSelect).toBeEnabled();
    await expect(taskSelect.getByRole('option', { name: taskName })).toHaveCount(1);
    await taskSelect.selectOption({ label: taskName });

    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Add Line Item' })).toBeVisible();
  }

  await test.step('§1 Creating a PO and its line items: task-link picker links each line to a top-level task', async () => {
    await page.goto(`/#/purchase-orders/${po.po_id}`);
    await addLineItemViaUI(line1Desc, task1Name);
    await addLineItemViaUI(line2Desc, task2Name);

    const reloaded = await api.get(`/api/purchase-orders/${po.po_id}/`);
    const li1 = reloaded.line_items.find((li) => li.description === line1Desc);
    const li2 = reloaded.line_items.find((li) => li.description === line2Desc);
    expect(li1.task).toBe(task1.task_id);
    expect(li2.task).toBe(task2.task_id);
  });

  await test.step('§5 Awaiting-reconciliation nudge is absent before receiving', async () => {
    await page.goto('/#/purchase-orders');
    const row = page.locator('tr', { hasText: po.po_number });
    await expect(row).toBeVisible();
    await expect(row.getByText('Awaiting Reconciliation')).toHaveCount(0);
  });

  await test.step('§2 Issue: Mark as Issued', async () => {
    await page.goto(`/#/purchase-orders/${po.po_id}`);
    page.once('dialog', (d) => d.accept());
    await page.getByRole('button', { name: 'Mark as Issued' }).click();
    await expect(page.locator('.status-badge')).toHaveText('issued');
    await dismissOverlay(page);
  });

  await test.step('§3 Receive All', async () => {
    await page.getByRole('button', { name: 'Receive All' }).click();
    await expect(page.locator('.status-badge')).toHaveText('received in full');
    await dismissOverlay(page);
  });

  await test.step('§5 Awaiting-reconciliation badge shows on the list, and the filter finds it', async () => {
    await page.goto('/#/purchase-orders');
    const row = page.locator('tr', { hasText: po.po_number });
    await expect(row.getByText('Awaiting Reconciliation')).toBeVisible();

    await page.getByRole('checkbox', { name: 'Awaiting reconciliation only' }).check();
    await expect(page.locator('tr', { hasText: po.po_number })).toBeVisible();
  });

  let suggestedRateText;

  await test.step('§6 Reconcile: bill total, vendor ref, two higher final prices, an invoice-only line, and the variance display', async () => {
    await page.goto(`/#/purchase-orders/${po.po_id}`);

    await page.locator('#recon-bill-total').fill('78.00');
    await page.locator('#recon-vendor-ref').fill(`VEND-${stamp}`);

    const line1Row = page.locator('tr', { hasText: line1Desc });
    await line1Row.locator('input[type="number"]').fill('35.00');
    const line2Row = page.locator('tr', { hasText: line2Desc });
    await line2Row.locator('input[type="number"]').fill('28.00');

    await page.getByRole('button', { name: 'Add Invoice-Only Line' }).click();
    const freightRow = page.locator('tr', { has: page.getByRole('button', { name: 'Remove' }) });
    await expect(freightRow).toHaveCount(1);
    // .first() -- the row also has the invoice-only TaskLinkPicker's own
    // "Search jobs…" text input, which we leave untouched (no task link on
    // this line).
    await freightRow.locator('input[type="text"]').first().fill('Freight');
    const freightNumberInputs = freightRow.locator('input[type="number"]');
    await freightNumberInputs.nth(0).fill('1');   // qty
    await freightNumberInputs.nth(1).fill('15.00'); // price

    await page.getByRole('button', { name: 'Reconcile', exact: true }).click();

    // Variance = bill_total(78.00) - ordered_total(20.00 + 20.00, invoice_only
    // excluded) = 38.00.
    await expect(page.locator('p', { hasText: 'Variance:' })).toContainText('$38.00');
    // The success toast renders ABOVE the rate-prompt modal that opens in the
    // same tick (--z-toast > --z-modal-nested) -- dismiss it before the next
    // step reaches into the dialog.
    await dismissOverlay(page);
  });

  await test.step('§7 The task-rate prompt fires with one row per qualifying line', async () => {
    const dialog = page.getByRole('dialog', { name: 'Update task rates?' });
    await expect(dialog).toBeVisible();

    const row1 = dialog.locator('tr', { hasText: task1Name });
    const row2 = dialog.locator('tr', { hasText: task2Name });
    await expect(row1).toBeVisible();
    await expect(row2).toBeVisible();

    // Capture the suggested rate as displayed -- reused verbatim below rather
    // than recomputed, so this spec doesn't couple to the markup-percent
    // config's exact value.
    suggestedRateText = (await row1.locator('td').nth(2).textContent()).trim();
    expect(suggestedRateText).toMatch(/^\$[\d,]+\.\d{2}$/);

    await row1.getByRole('button', { name: 'Accept' }).click();
    await expect(row1.getByText('Updated.')).toBeVisible();

    await row2.getByRole('button', { name: 'Decline' }).click();
    await expect(row2.getByText('Declined.')).toBeVisible();

    await dialog.getByRole('button', { name: 'Close' }).click();
    await expect(dialog).toHaveCount(0);
  });

  await test.step('§7 Accept updated the task rate; Decline left the other task exactly as quoted (inversion)', async () => {
    await page.goto(`/#/jobs/${job.job_id}/tasks/${task1.task_id}`);
    await expect(rateChipOf(page)).toContainText(suggestedRateText);

    await page.goto(`/#/jobs/${job.job_id}/tasks/${task2.task_id}`);
    await expect(rateChipOf(page)).toContainText(`$${flatScheme.rate}/${flatScheme.unit_label}`);
  });

  await test.step('§6 A persisted invoice-only line shows the removal notice, and Re-add restores it', async () => {
    // Full navigation -- a fresh mount so ReconciliationSection re-seeds its
    // local state from the just-reloaded PO (the freight line now carries a
    // real line_item_id, i.e. it is genuinely "persisted", not still the
    // same-session draft row from §6 above).
    await page.goto(`/#/purchase-orders/${po.po_id}`);

    // The Freight line is a real PurchaseOrderLineItem, so it ALSO shows a
    // row in the main Line Items table above (excluded from receiving, but
    // not from that listing) -- an unscoped `tr:has-text('Freight')` would
    // be ambiguous between the two, AND wouldn't even match the invoice-only
    // row anyway ("Freight" lives in an <input value>, which `hasText`/
    // `toContainText` never see -- textContent excludes form-control
    // values). Only the Invoice-Only Lines row has a Remove button, so
    // filtering on that (same pattern already used above to find the
    // newly-added row pre-save) disambiguates unambiguously; the value
    // check below confirms it's genuinely the Freight row via .toHaveValue,
    // not text matching.
    const freightRow = page.locator('tr', { has: page.getByRole('button', { name: 'Remove' }) });
    await expect(freightRow).toBeVisible();
    await expect(freightRow.locator('input[type="text"]').first()).toHaveValue('Freight');
    await freightRow.getByRole('button', { name: 'Remove' }).click();

    await expect(page.getByText(/will be deleted when you save/)).toBeVisible();
    await expect(page.locator('tr', { has: page.getByRole('button', { name: 'Remove' }) })).toHaveCount(0);

    await page.getByRole('button', { name: 'Re-add' }).click();
    await expect(page.getByText(/will be deleted when you save/)).toHaveCount(0);
    await expect(page.locator('tr', { has: page.getByRole('button', { name: 'Remove' }) })).toBeVisible();
  });

  await test.step('§8 The invoice wizard offers the accepted task at its new (live-read) rate', async () => {
    // Completing the task isn't the flow under test -- task completion is
    // the billability gate (Purchasing.md §8), so it's API setup, same
    // precedent as uncategorized-fallback.spec.js's task completions.
    await api.post(`/api/tasks/${task1.task_id}/complete/`, { add_qty: '1' });

    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByText(`Invoice: Draft — ${job.job_number}`)).toBeVisible();

    await page.getByRole('button', { name: 'Reconcile' }).click();
    await expect(page.getByRole('heading', { name: 'Tasks and Materials' })).toBeVisible();

    const row = page.locator('label, span').filter({ hasText: task1Name }).first();
    await expect(row).toContainText(suggestedRateText);
  });

  await api.dispose();
});
