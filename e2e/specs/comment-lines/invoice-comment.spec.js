// Comment lines on the invoice surface: authored through the same Add Line
// picker comment mode (no AC step), stored zeroed/category-free, excluded
// from the invoice total, and EXEMPT from the pre-send categorization gate
// (tests/test_comment_line_items.py InvoiceCommentLineCategorizationTest).
//
// The gate is proven at BOTH layers. API: send_invoice checks
// _assert_all_lines_categorized FIRST, before the QBO push — so a 400
// "No active QBO connection." (QBO is deliberately not connected in this
// env, docs/designs/e2e-testing.md §3) is positive proof the category gate
// let the comment through. UI: InvoicePanel's client-side
// allLinesHaveCategory mirrors the backend filter's is_comment exemption
// (fixed 2026-09-22, this backfill), so the Send Invoice link stays
// available with a comment line present and the send flow is driven
// through to the documented no-QBO failure (same exemption pattern as
// invoice-skeleton/seeded-invoice.spec.js — the alert proves the gate was
// passed and the push was reached, not that an email was delivered).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-cmtinv-${Date.now().toString(36)}`;

test('invoice comment line: AC-free add form, excluded from the total, passes the pre-send categorization gate', async ({ page }) => {
  const api = await apiAs(personas.finjobs);

  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  const category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);
  test.skip(!category, 'seed gap: no usable accounting category');

  // Hand-approved estimate-less job — the minimal billable backdrop.
  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });
  await api.patch(`/api/jobs/${job.job_id}/`, { status: 'submitted' });
  await api.patch(`/api/jobs/${job.job_id}/`, { status: 'approved' });

  const invoice = await api.post('/api/invoices/', { job: job.job_id, seed: false });
  const realDesc = `${stamp} design retainer`;
  const realLine = await api.post(`/api/invoices/${invoice.invoice_id}/line-items/`, {
    description: realDesc, qty: '1', units: 'none', price: '150.00',
    accounting_category: category.id,
  });

  const commentDesc = `${stamp} see attached warranty terms`;

  const lineRow = (desc) => page.locator('table.line-items-table tbody tr').filter({
    has: page.locator('td.preserve-breaks', { hasText: desc }),
  });

  await test.step('Add Line Item → "Comment (no charge)": the follow-up form asks for a description only', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice/${invoice.invoice_id}`);
    await expect(lineRow(realDesc)).toBeVisible(); // anchor: the draft loaded

    await page.getByRole('button', { name: 'Add Line Item' }).click();
    const picker = page.getByRole('dialog');
    await picker.getByPlaceholder(/search/i).fill(commentDesc);
    await picker.getByRole('checkbox', { name: 'Comment (no charge)' }).check();
    await picker.getByRole('button', { name: 'Add Line', exact: true }).click();

    const form = page.getByRole('dialog');
    await expect(form.getByRole('heading', { name: 'Add Comment' })).toBeVisible();
    await expect(form.getByLabel('Description')).toHaveValue(commentDesc); // anchor
    await expect(form.getByLabel(/Accounting Category/)).toHaveCount(0);
    await expect(form.getByLabel(/Quantity/)).toHaveCount(0);
    await expect(form.getByLabel(/^Price/)).toHaveCount(0);
    await form.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await expect(lineRow(commentDesc)).toBeVisible();
  });

  await test.step('Stored zeroed and category-free; the invoice total is the real line alone', async () => {
    const detail = await api.get(`/api/invoices/${invoice.invoice_id}/`);
    const commentLine = detail.line_items.find((li) => li.description === commentDesc);
    expect(commentLine).toBeTruthy();
    expect(commentLine.is_comment).toBe(true);
    expect(commentLine.accounting_category).toBeNull();
    expect(Number(commentLine.qty)).toBe(0);
    expect(Number(commentLine.price)).toBe(0);

    expect(Number(realLine.price)).toBe(150); // anchor: the real line carries the money
    expect(Number(detail.total)).toBeCloseTo(150, 2);
  });

  await test.step('The Send affordance stays available with the comment present, and the send flow reaches the QBO push', async () => {
    // Positive anchor + regression guard for the client-side gate: the
    // blocked-state note must NOT appear, and Send Invoice is a real link.
    await expect(page.getByText('Assign an accounting category to every line before sending.')).toHaveCount(0);
    await page.getByRole('link', { name: 'Send Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Send Invoice' })).toBeVisible();
    await page.getByLabel('To *').fill('e2e-comment-send@example.invalid');
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Send Invoice' }).click();
    // No QBO connection in this env — the push fails server-side and the
    // invoice stays draft. Reaching THIS failure (surfaced as the form's
    // role="alert") proves the categorization gate let the comment line
    // through end-to-end; the API step below pins the exact error text.
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 15_000 });
  });

  await test.step('The pre-send categorization gate passes: send fails on the QBO connection, never on the comment\'s missing category', async () => {
    const resp = await api.postRaw(`/api/invoices/${invoice.invoice_id}/send/`, {
      to: 'e2e-comment-send@example.invalid',
    });
    expect(resp.ok()).toBe(false);
    const body = await resp.text();
    // The gate runs BEFORE the QBO push (send_invoice line order) — landing
    // on the connection error proves the category gate let the comment
    // line through.
    expect(body).toContain('No active QBO connection');
    expect(body).not.toMatch(/accounting category/i);
  });

  await api.dispose();
});
