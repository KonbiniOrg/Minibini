// Comment lines on the invoice surface: authored through the same Add Line
// picker comment mode (no AC step), stored zeroed/category-free, excluded
// from the invoice total, and EXEMPT from the pre-send categorization gate
// (tests/test_comment_line_items.py InvoiceCommentLineCategorizationTest).
//
// The gate proof runs at the API: send_invoice checks
// _assert_all_lines_categorized FIRST, before the QBO push — so a 400
// "No active QBO connection." (QBO is deliberately not connected in this
// env, docs/designs/e2e-testing.md §3) is positive proof the category gate
// let the comment through. The UI half of that journey is currently NOT
// drivable: InvoicePanel's client-side allLinesHaveCategory check has no
// is_comment exemption, so the Send Invoice link is blocked whenever a
// comment line exists — a post-merge UI gap (see the comment-lines e2e
// report); this spec asserts the backend contract and leaves the blocked
// link unasserted rather than enshrining the regression.
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
