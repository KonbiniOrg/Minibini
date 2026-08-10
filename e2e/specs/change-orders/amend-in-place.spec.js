// docs/ui-flows/Change-Orders.md §2-§6 — the CO amend-in-place surface
// (COEditView, the amended-agreement table, and its Views modes/acceptance
// crystallization). .superpowers/sdd/2026-08-09-co-amend-in-place-plan
// Task 11. co-room-and-diff.spec.js owns entry gating + JobShell chrome;
// this file owns the amended-agreement editing surface itself.
//
// Every job here is built fresh via the API (contact + rate-scheme + tasks +
// estimate), same idiom as
// specs/invoice-skeleton/agreement-line-restore-picker.spec.js — the shapes
// needed (several distinct atom-backed lines, one already billed on a live
// invoice, one task completed before a CO strikes its line) are precise
// enough that hunting the seed for a match would be more fragile than
// building them, and nothing here touches fixtures/playwright/seed.json.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

// Mirrors COEditView's own footer formatters exactly (frontend/src/
// components/changeorders/COEditView.svelte fmtTotal/fmtDelta) — NOT
// lib/taskTotals.fmtMoney, which renders 0 as '-' instead of '$0.00'.
function fmtTotal(n) { return `$${Number(n ?? 0).toFixed(2)}`; }
function fmtDelta(n) {
  const v = Number(n ?? 0);
  if (v === 0) return fmtTotal(0);
  return (v > 0 ? '+' : '-') + `$${Math.abs(v).toFixed(2)}`;
}
function fmtParen(n) { return `(${fmtTotal(n)})`; }
// COCustomerView's own fmtSigned (frontend/src/components/changeorders/
// COCustomerView.svelte) — minus-only, unlike COEditView's fmtDelta above
// which also prefixes a '+' for positive deltas.
function fmtSigned(n) {
  const v = Number(n ?? 0);
  return `${v < 0 ? '-' : ''}$${Math.abs(v).toFixed(2)}`;
}

// A job with an accepted estimate whose lines are one-atom-per-line (task
// name === line description, so UI text and API rows can be cross-checked
// without knowing prices up front). `taskNames` each get their own estimate
// line; any task NOT in `taskNames` is created but left off the estimate —
// that's the "uncovered work" atom for the source-pool tests.
async function buildJob(api, { stamp, taskNames, extraTaskNames = [] }) {
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const scheme = (schemes.results || schemes)
    .find((s) => s.algorithm === 'entered_qty' && s.is_active !== false);
  if (!scheme) return null;

  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });

  const tasks = {};
  for (const name of [...taskNames, ...extraTaskNames]) {
    tasks[name] = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
      name: `${stamp} ${name}`, rate_scheme: scheme.rate_scheme_id, est_qty: '2',
    });
  }

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  const lines = {};
  for (const name of taskNames) {
    lines[name] = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
      atoms: [{ type: 'task', id: tasks[name].task_id }],
    });
  }

  // mark-open's send-gate requires a non-empty Deliverables list.
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

  return { job, estimate, tasks, lines };
}

test('Amend-in-place gestures: remove/undo, replace with inherited atoms, add from the pool, billed-on gating, customer + reorder modes', async ({ page }) => {
  const stamp = `e2e-amend-${Date.now().toString(36)}`;
  const api = await apiAs(personas.finjobs);

  const built = await buildJob(api, {
    stamp, taskNames: ['Remove', 'Replace', 'Billed'], extraTaskNames: ['Uncovered'],
  });
  test.skip(!built, 'seed gap: no active entered_qty rate scheme');
  const { job, tasks, lines } = built;

  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: 'e2e: amend-in-place gestures' });
  const co = await api.post('/api/change-orders/', { job: job.job_id });

  // A live (draft) invoice claiming the "Billed" line DIRECTLY — seed:false
  // + restore-line targets exactly that one agreement line, so auto-seeding
  // can't also grab the "Remove"/"Replace" lines the gesture steps below
  // still need untouched.
  const invoice = await api.post('/api/invoices/', { job: job.job_id, seed: false });
  await api.post(`/api/invoices/${invoice.invoice_id}/restore-line/`, {
    estimate_line_id: lines.Billed.line_item_id,
  });

  const categories = await api.get('/api/accounting-categories/?page_size=100');
  test.skip(!(categories.results || categories).length, 'seed gap: no accounting categories');

  const apiBase = `/api/change-orders/${co.change_order_id}`;
  const amended = async () => api.get(`${apiBase}/amended-agreement/`);
  const agreementRowFor = (payload, lineItemId) =>
    payload.rows.find((r) => r.kind === 'agreement' && r.line.estimate_line_id === lineItemId);

  await page.goto(`/#/jobs/${job.job_id}/change-order/${co.change_order_id}`);
  const editTable = page.locator('table.co-edit-table');
  const plainRow = (desc) =>
    editTable.locator('tbody > tr:not(.co-authored):not(.co-struck-original)').filter({ hasText: desc });
  const struckRow = (desc) => editTable.locator('tr.co-struck-original').filter({ hasText: desc });
  const authoredRow = (desc) => editTable.locator('tr.co-authored').filter({ hasText: desc });

  await test.step('Remove via CO strikes the row in place (parenthesized amount, revised total drops); Undo restores it', async () => {
    const before = await amended();
    const originalRow = agreementRowFor(before, lines.Remove.line_item_id);

    await expect(plainRow(lines.Remove.description)).toBeVisible();
    await plainRow(lines.Remove.description).getByRole('button', { name: 'Remove via CO' }).click();

    const struck = struckRow(lines.Remove.description);
    await expect(struck).toBeVisible();
    await expect(struck).toContainText(fmtParen(originalRow.line.amount));
    await expect(struck.getByRole('button', { name: 'Undo' })).toBeVisible();

    const afterRemove = await amended();
    expect(Number(afterRemove.revised_total)).toBeLessThan(Number(before.revised_total));
    await expect(editTable.locator('tfoot')).toContainText(fmtTotal(afterRemove.revised_total));

    await struck.getByRole('button', { name: 'Undo' }).click();
    await expect(struckRow(lines.Remove.description)).toHaveCount(0);
    await expect(plainRow(lines.Remove.description)).toBeVisible();

    const afterUndo = await amended();
    expect(afterUndo.revised_total).toBe(before.revised_total);
    await expect(editTable.locator('tfoot')).toContainText(fmtTotal(afterUndo.revised_total));
  });

  await test.step('Replace… opens a prefilled modal; saving shows a tinted CO row over the struck original with "inherited from line N" children and footer totals', async () => {
    const before = await amended();
    const originalRow = agreementRowFor(before, lines.Replace.line_item_id);

    await plainRow(lines.Replace.description).getByRole('button', { name: /Replace/ }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Replace Line');
    const qtyVal = await dialog.getByLabel(/Quantity/).inputValue();
    const priceVal = await dialog.getByLabel(/^Price/).inputValue();
    expect(Number(qtyVal)).toBe(Number(originalRow.line.qty));
    expect(Number(priceVal)).toBe(Number(originalRow.line.price));

    const newPrice = (Number(originalRow.line.price) + 10).toFixed(2);
    await dialog.getByLabel(/^Price/).fill(newPrice);
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(dialog).toBeHidden();

    const after = await amended();
    const replacedRow = after.rows.find(
      (r) => r.kind === 'replaced' && r.original.estimate_line_id === lines.Replace.line_item_id);
    expect(replacedRow).toBeTruthy();

    const authored = authoredRow(lines.Replace.description);
    await expect(authored).toBeVisible();
    await expect(authored.locator('.co-badge')).toHaveText(`CO ${replacedRow.co_index}`);
    await expect(authored).toContainText(fmtTotal(replacedRow.line.amount));

    const stillStruck = struckRow(lines.Replace.description);
    await expect(stillStruck).toContainText(fmtParen(originalRow.line.amount));

    // The replaced line's own task claim rides along as an inherited child
    // row directly under it.
    const inheritedChild = editTable.locator('tbody tr')
      .filter({ hasText: tasks.Replace.name })
      .filter({ hasText: /inherited from line \d+/ });
    await expect(inheritedChild).toBeVisible();

    const tfoot = editTable.locator('tfoot');
    await expect(tfoot).toContainText(fmtTotal(after.original_total));
    await expect(tfoot).toContainText(fmtDelta(after.co_delta));
    await expect(tfoot).toContainText(fmtTotal(after.revised_total));
  });

  await test.step('"New line from selected" in Uncovered work adds a tinted CO add row carrying the atom', async () => {
    const pool = page.locator('.uncovered-work-section');
    const poolRow = pool.locator('tbody tr').filter({ hasText: tasks.Uncovered.name });
    await expect(poolRow).toBeVisible();
    await poolRow.locator('input[type="checkbox"]').check();

    const createRow = page.locator('tr.doc-newline');
    await expect(createRow).toBeVisible();
    await createRow.getByRole('button', { name: 'Create line' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Edit Line');
    await dialog.getByLabel(/Accounting Category/).selectOption({ index: 1 });
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(dialog).toBeHidden();

    const after = await amended();
    const addedRow = after.rows.find((r) => r.kind === 'added' && r.line.description === tasks.Uncovered.name);
    expect(addedRow).toBeTruthy();

    const authored = authoredRow(tasks.Uncovered.name);
    await expect(authored).toBeVisible();
    await expect(authored.locator('.co-badge')).toHaveText(`CO ${addedRow.co_index}`);

    // Claimed now, so it's gone from the still-uncovered pool.
    await expect(pool.locator('tbody tr').filter({ hasText: tasks.Uncovered.name })).toHaveCount(0);
  });

  await test.step('A line billed on a live invoice shows both gesture buttons disabled with "billed on …"', async () => {
    const row = plainRow(lines.Billed.description);
    await expect(row.getByRole('button', { name: 'Remove via CO' })).toBeDisabled();
    await expect(row.getByRole('button', { name: /Replace/ })).toBeDisabled();
    await expect(row).toContainText(`billed on ${invoice.display_number}`);
  });

  await test.step('Customer mode shows only the delta lines, with Change total / Revised agreement total', async () => {
    await page.locator('.doc-mode-bar').getByRole('button', { name: 'Customer', exact: true }).click();
    const view = page.locator('.co-customer-view');
    await expect(view).toBeVisible();

    await expect(view.locator('tbody tr').filter({ hasText: lines.Replace.description })).toBeVisible();
    await expect(view.locator('tbody tr').filter({ hasText: tasks.Uncovered.name })).toBeVisible();
    // Untouched agreement lines (the billed one) never appear — this is a
    // change document, not the whole agreement.
    await expect(view.locator('tbody tr').filter({ hasText: lines.Billed.description })).toHaveCount(0);

    const after = await amended();
    await expect(view).toContainText('Change total');
    await expect(view).toContainText(fmtSigned(after.co_delta));
    await expect(view).toContainText('Revised agreement total');
    await expect(view).toContainText(fmtTotal(after.revised_total));
  });

  await test.step('Reorder mode moves a CO line', async () => {
    await page.locator('.doc-mode-bar').getByRole('button', { name: 'Reorder', exact: true }).click();
    const view = page.locator('.doc-customer-view');
    await expect(view).toBeVisible();

    const before = await amended();
    const ordered = before.rows
      .filter((r) => r.kind === 'added' || r.kind === 'replaced')
      .sort((a, b) => a.co_index - b.co_index);
    expect(ordered.length).toBeGreaterThanOrEqual(2);
    const [first, second] = ordered;

    const firstRow = view.locator('tbody tr').filter({ hasText: first.line.description });
    await firstRow.getByRole('button', { name: '▼' }).click();

    await expect(async () => {
      const rowTexts = await view.locator('tbody tr').allTextContents();
      expect(rowTexts[0]).toContain(second.line.description);
      expect(rowTexts[1]).toContain(first.line.description);
    }).toPass();
  });

  await api.dispose();
});

test('Accepting a CO crystallizes the amendment: job un-holds, estimate reads "amended", billing shows the descope + CO provenance', async ({ page }) => {
  const stamp = `e2e-accept-${Date.now().toString(36)}`;
  const api = await apiAs(personas.finjobs);

  const built = await buildJob(api, { stamp, taskNames: ['Remove', 'Replace'] });
  test.skip(!built, 'seed gap: no active entered_qty rate scheme');
  const { job, estimate, tasks, lines } = built;

  // Complete the "Remove" task BEFORE the hold — task/material mutations
  // freeze once the job is on hold, and only a complete task survives CO
  // acceptance's retire-on-remove step (docs/ui-flows/Change-Orders.md §6:
  // "a task already complete is left alone").
  await api.post(`/api/tasks/${tasks.Remove.task_id}/complete/`, { add_qty: '1' });

  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: 'e2e: amend-in-place acceptance' });
  const co = await api.post('/api/change-orders/', { job: job.job_id });
  await api.post(`/api/change-orders/${co.change_order_id}/line-items/`, {
    action: 'remove', target_line_item: lines.Remove.line_item_id,
  });
  const replaceLine = await api.post(`/api/change-orders/${co.change_order_id}/line-items/`, {
    action: 'replace', target_line_item: lines.Replace.line_item_id,
    description: lines.Replace.description, qty: lines.Replace.qty, units: lines.Replace.units,
    price: (Number(lines.Replace.price) + 5).toFixed(2),
  });
  await api.patch(`/api/change-orders/${co.change_order_id}/`, { status: 'open' });

  async function jobDetail() {
    const a = await apiAs(personas.finjobs);
    const detail = await a.get(`/api/jobs/${job.job_id}/`);
    await a.dispose();
    return detail;
  }

  await test.step('Record Accepted: job un-holds and the estimate badge reads "amended"', async () => {
    await page.goto(`/#/jobs/${job.job_id}/change-order/${co.change_order_id}`);
    page.once('dialog', (d) => d.accept());
    await page.getByRole('button', { name: 'Record Accepted' }).click();
    // Terminal toolbar replaces the open one only once the PATCH lands.
    await expect(page.getByRole('button', { name: 'Start new change order' })).toBeVisible();

    await expect.poll(async () => (await jobDetail()).on_hold).toBe(false);

    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await expect(page.getByText(`Estimate: ${estimate.estimate_number}`)).toBeVisible();
    // Scoped to the toolbar's own status pill — DocSubnav also renders
    // .status-badge pills (class .doc-subnav-pill) for the version list.
    await expect(page.locator('.toolbar .status-badge')).toHaveText('amended');
  });

  await test.step('A new invoice: "descoped by CO-1" on the surviving atom, "CO-1 line N" provenance on the replacement', async () => {
    const freshCo = await api.get(`/api/change-orders/${co.change_order_id}/`);
    const suffix = /-CO(\d+)$/.exec(freshCo.change_order_number)?.[1];
    const shortLabel = `CO-${suffix}`;
    const replacedCoLine = freshCo.line_items.find((li) => li.line_item_id === replaceLine.line_item_id);

    const invoice = await api.post('/api/invoices/', { job: job.job_id });

    await page.goto(`/#/jobs/${job.job_id}/invoice/${invoice.invoice_id}`);
    await expect(page.getByRole('heading', { name: 'Uncovered work' })).toBeVisible();
    const struckRow = page.locator('.uncovered-work-section tr').filter({ hasText: tasks.Remove.name });
    await expect(struckRow.getByText(`descoped by ${shortLabel}`)).toBeVisible();

    const seededRow = page.locator('table.line-items-table tr').filter({ hasText: lines.Replace.description });
    await expect(seededRow.first()).toContainText(`${shortLabel} line ${replacedCoLine.line_number}`);
  });

  await api.dispose();
});
