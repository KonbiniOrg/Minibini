// Outsourced-work port (.superpowers/sdd/2026-09-21-outsourced-work-port-plan)
// — Task 7, rebuilt against this branch's current conventions (analysis §6/
// §7 of docs/plans/2026-09-21-phase5-port-analysis.md), NOT a copy of
// feature/fees' spec of the same name: vendor + job + two outsourced tasks
// (quoted sell rate typed at creation, §3.6c create-time money override) ->
// a PO with task-linked lines (the Task Link picker, TaskLinkPicker.svelte,
// is new UI on this branch) -> issue -> receive-all -> the
// awaiting-reconciliation badge + list filter -> complete both tasks
// (settle-up qty) -> reconcile (bill total, vendor ref, per-line finals on
// both linked lines, an invoice-only appended freight line, the
// persisted-removal notice) -> the resulting task-rate prompt (Accept on
// the task whose line got a final that should change its rate; Decline on
// the other, same "cheapest arrangement covering both branches" fees used)
// -> the CURRENT-branch final assertion: starting an invoice job-side
// AFTER the accept re-derives the backed line's price from the task's NEW
// rate (InvoiceService._rederive_price_from_actuals, apps/invoicing/
// services.py:568) — NOT "the invoice wizard reads the task rate live"
// (fees' framing; that read path doesn't exist here — seed_from_agreement
// always re-derives a claimed line's price from its atoms' CURRENT
// actuals at seed time, so any rate change made before the invoice exists
// lands in the seeded price for free).
//
// Ordering note (RM ruling 2026-09-21, resolves LATER.md "rate-prompt
// Accept fails on complete tasks"): both tasks complete BEFORE reconcile —
// the realistic ordering for outsourced work (receive -> complete task ->
// bill arrives -> reconcile -> accept the reprice). JobService.update_task
// now carves out exactly this rate-only write on a COMPLETE, uninvoiced,
// PO-linked task, so Accept's PATCH no longer needs the tasks left open as
// a workaround.
//
// One continuous test.step() flow (same convention as
// specs/task-view-bundling/co-lens.spec.js): every section after the first
// depends on state built by the one before it (same PO, same two tasks).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-por-${Date.now().toString(36)}`;

// The global success/error toast (MessageOverlay.svelte) sits at --z-toast
// (1000), ABOVE even a nested modal (--z-modal-nested: 900), and never
// auto-dismisses (stores/messages.js has no route hook or timeout) — so it
// silently intercepts pointer events on whatever comes next (here, the
// rate-prompt modal that opens in the very same tick as reconcile's own
// success toast) until dismissed. Same pattern as
// specs/invoice-skeleton/estimate-three-modes.spec.js.
async function dismissOverlay(page) {
  await page.getByRole('button', { name: 'Dismiss message' }).click();
}

test('PO task-link -> issue -> receive -> reconcile -> rate prompt -> invoice actuals re-derivation', async ({ page }) => {
  test.setTimeout(120_000);
  const api = await apiAs(personas.finjobs);

  // ---- Backdrop (not the flow under test): vendor business, job, two
  // outsourced flat tasks with a quoted sell rate. Object creation that
  // isn't the flow under test is API-driven, same precedent as
  // specs/task-view-bundling/*.spec.js and specs/invoice-skeleton/
  // seeded-invoice.spec.js.
  const business = (await api.get('/api/businesses/?page_size=1')).results[0];
  test.skip(!business, 'seed gap: no Business to use as PO vendor');
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const job = await api.post('/api/jobs/', {
    name: `${stamp} outsourced job`, contact: contact.contact_id,
  });

  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const scheme = (schemes.results || schemes)
    .find((s) => s.algorithm === 'entered_qty' && s.is_active !== false);
  test.skip(!scheme, 'seed gap: no active entered_qty rate scheme');

  const task1Name = `${stamp} outsourced task 1 (accept)`;
  const task2Name = `${stamp} outsourced task 2 (decline)`;

  // §3.6c create-time money override: the quoted sell rate is typed at
  // task creation — the interim "outsourced work" authoring practice the
  // analysis (§8) names, ahead of any dedicated authoring surface.
  const task1 = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: task1Name, rate_scheme: scheme.rate_scheme_id, est_qty: '1', rate: '20.00',
  });
  const task2 = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: task2Name, rate_scheme: scheme.rate_scheme_id, est_qty: '1', rate: '20.00',
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  const line1 = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: task1.task_id }],
  });
  await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: task2.task_id }],
  });
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

  const jobDetail = await api.get(`/api/jobs/${job.job_id}/`);
  expect(jobDetail.status).toBe('in_progress'); // both lines atom-sourced -- auto-releases

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

  await test.step('Creating a PO and its line items: the Task Link picker links each line to a task', async () => {
    await page.goto(`/#/purchase-orders/${po.po_id}`);
    await addLineItemViaUI(line1Desc, task1Name);
    await addLineItemViaUI(line2Desc, task2Name);

    const reloaded = await api.get(`/api/purchase-orders/${po.po_id}/`);
    const li1 = reloaded.line_items.find((li) => li.description === line1Desc);
    const li2 = reloaded.line_items.find((li) => li.description === line2Desc);
    expect(li1.task).toBe(task1.task_id);
    expect(li2.task).toBe(task2.task_id);
  });

  await test.step('Awaiting-reconciliation badge is absent before receiving', async () => {
    await page.goto('/#/purchase-orders');
    const row = page.locator('tr', { hasText: po.po_number });
    await expect(row).toBeVisible();
    await expect(row.getByText('Awaiting Reconciliation')).toHaveCount(0);
  });

  await test.step('Issue: Mark as Issued', async () => {
    await page.goto(`/#/purchase-orders/${po.po_id}`);
    page.once('dialog', (d) => d.accept());
    await page.getByRole('button', { name: 'Mark as Issued' }).click();
    await expect(page.locator('.status-badge')).toHaveText('issued');
    await dismissOverlay(page);
  });

  await test.step('Receive All', async () => {
    await page.getByRole('button', { name: 'Receive All' }).click();
    await expect(page.locator('.status-badge')).toHaveText('received in full');
    await dismissOverlay(page);
  });

  await test.step('Complete both tasks (settle-up qty) before reconciling -- the realistic ordering for outsourced work: receive, complete, bill arrives, reconcile, accept the reprice (RM ruling 2026-09-21 -- JobService.update_task carves out exactly this rate write)', async () => {
    // add_qty matches each task's own est_qty exactly, so actual_qty pins
    // to 1 and compute_amount() (actual_qty x effective_rate) stays
    // deterministic for the final assertion below.
    await api.post(`/api/tasks/${task1.task_id}/complete/`, { add_qty: '1' });
    await api.post(`/api/tasks/${task2.task_id}/complete/`, { add_qty: '1' });
  });

  await test.step('Awaiting-reconciliation badge shows on the list, and the filter finds it', async () => {
    await page.goto('/#/purchase-orders');
    const row = page.locator('tr', { hasText: po.po_number });
    await expect(row.getByText('Awaiting Reconciliation')).toBeVisible();

    await page.getByRole('checkbox', { name: 'Awaiting reconciliation only' }).check();
    await expect(page.locator('tr', { hasText: po.po_number })).toBeVisible();
  });

  await test.step('Reconcile: bill total, vendor ref, per-line finals on both linked lines, an invoice-only line', async () => {
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
    // .first() -- the row also carries the invoice-only TaskLinkPicker's
    // own "Search jobs…" text input, left untouched (no task link on this
    // freight line).
    await freightRow.locator('input[type="text"]').first().fill('Freight');
    const freightNumberInputs = freightRow.locator('input[type="number"]');
    await freightNumberInputs.nth(0).fill('1');     // qty
    await freightNumberInputs.nth(1).fill('15.00'); // price

    await page.getByRole('button', { name: 'Reconcile', exact: true }).click();

    // Variance = bill_total(78.00) - ordered_total(20.00 + 20.00, invoice_only
    // excluded) = 38.00.
    await expect(page.locator('p', { hasText: 'Variance:' })).toContainText('$38.00');
    // The success toast renders ABOVE the rate-prompt modal that opens in
    // the same tick -- dismiss it before the next step reaches into the
    // dialog.
    await dismissOverlay(page);
  });

  let task1SuggestedRate;

  await test.step('The task-rate prompt fires with one row per finaled linked line: Accept on task1, Decline on task2', async () => {
    const dialog = page.getByRole('dialog', { name: 'Update task rates?' });
    await expect(dialog).toBeVisible();

    const row1 = dialog.locator('tr', { hasText: task1Name });
    const row2 = dialog.locator('tr', { hasText: task2Name });
    await expect(row1).toBeVisible();
    await expect(row2).toBeVisible();

    // Captured as displayed, not recomputed -- keeps this spec decoupled
    // from whether default_material_markup_percent is configured in this
    // seed (compute_rate_prompts: suggested_rate is final_price, marked up
    // only when that Configuration row exists).
    task1SuggestedRate = (await row1.locator('td').nth(2).textContent()).trim();
    expect(task1SuggestedRate).toMatch(/^\$[\d,]+\.\d{2}$/);

    await row1.getByRole('button', { name: 'Accept' }).click();
    await expect(row1.getByText('Updated.')).toBeVisible();

    await row2.getByRole('button', { name: 'Decline' }).click();
    await expect(row2.getByText('Declined.')).toBeVisible();

    await dialog.getByRole('button', { name: 'Close' }).click();
    await expect(dialog).toHaveCount(0);
  });

  await test.step('Accept PATCHed task1\'s rate; Decline left task2 exactly as quoted', async () => {
    const check = await apiAs(personas.finjobs);
    const t1 = await check.get(`/api/tasks/${task1.task_id}/`);
    const t2 = await check.get(`/api/tasks/${task2.task_id}/`);
    await check.dispose();
    expect(`$${Number(t1.rate).toFixed(2)}`).toBe(task1SuggestedRate);
    expect(Number(t2.rate)).toBe(20);
  });

  await test.step('A persisted invoice-only line shows the removal notice, and Re-add restores it; saving re-offers the (still safely closeable) rate prompt', async () => {
    // Full navigation -- a fresh mount so ReconciliationSection re-seeds
    // its local state from the just-reloaded PO (the freight line now
    // carries a real line_item_id -- genuinely "persisted", not still the
    // same-session draft row added in the Reconcile step above).
    await page.goto(`/#/purchase-orders/${po.po_id}`);

    const freightRow = page.locator('tr', { has: page.getByRole('button', { name: 'Remove' }) });
    await expect(freightRow).toBeVisible();
    await expect(freightRow.locator('input[type="text"]').first()).toHaveValue('Freight');
    await freightRow.getByRole('button', { name: 'Remove' }).click();

    await expect(page.getByText(/will be deleted when you save/)).toBeVisible();
    await expect(page.locator('tr', { has: page.getByRole('button', { name: 'Remove' }) })).toHaveCount(0);

    await page.getByRole('button', { name: 'Re-add' }).click();
    await expect(page.getByText(/will be deleted when you save/)).toHaveCount(0);
    await expect(page.locator('tr', { has: page.getByRole('button', { name: 'Remove' }) })).toBeVisible();

    await page.getByRole('button', { name: 'Update reconciliation' }).click();
    await dismissOverlay(page);

    // Both lines still carry a non-null final_price and neither task is
    // yet on a live invoice, so re-reconciling re-offers the rate prompt
    // (compute_rate_prompts has no "already decided" memory) -- closing it
    // untouched is itself a safe no-op, proving Accept/Decline earlier
    // aren't undone by simply re-viewing the prompt.
    const dialog = page.getByRole('dialog', { name: 'Update task rates?' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Close' }).click();
    await expect(dialog).toHaveCount(0);
  });

  await test.step('Starting an invoice AFTER the accept seeds the backed line already re-derived onto task1\'s NEW rate', async () => {
    const check = await apiAs(personas.finjobs);
    // task1 was already completed above (before reconcile, the realistic
    // ordering) -- just read back its now-accepted rate.
    const t1 = await check.get(`/api/tasks/${task1.task_id}/`);
    await check.dispose();
    // actual_qty(1) x effective_rate -- InvoiceService._rederive_price_from_actuals
    // re-derives the seeded line's price from exactly this computation.
    const expectedPrice = Number(t1.rate).toFixed(2);
    expect(`$${expectedPrice}`).toBe(task1SuggestedRate);

    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();

    // Scoped to the row carrying a BackingChip -- the parent line row, not
    // a nested AtomChildRow underneath it (same description text, no
    // chip) -- same disambiguation as specs/invoice-skeleton/
    // seeded-invoice.spec.js.
    const row = page.locator('table.line-items-table tr')
      .filter({ hasText: line1.description }).filter({ has: page.locator('.backing-chip') });
    await expect(row).toBeVisible();
    await expect(row.locator('.backing-chip')).toContainText('actuals');
    await expect(row).toContainText(`$${expectedPrice}`);
  });

  await api.dispose();
});
