// Comment lines on the purchase-order surface: LineItemForm's manual mode
// carries a "Comment line (informational only — no charge)" checkbox that
// collapses qty/price/category (comment authoring IS implemented for POs on
// this branch); the stored line is zeroed and category-free
// (tests/test_comment_line_items.py PurchaseOrderCommentLineTest), the PO
// total is untouched, and receiving ignores the line entirely — its qty is
// 0, so it has nothing outstanding and never blocks "received in full"
// (PurchaseOrderReceivingService.receive_all only collects lines with
// remaining > 0). Flow idiom mirrors specs/purchasing/po-reconciliation.spec.js.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-cmtpo-${Date.now().toString(36)}`;

// Success toasts stack over later controls — dismiss between steps (same
// pattern as specs/purchasing/po-reconciliation.spec.js).
async function dismissOverlay(page) {
  await page.getByRole('button', { name: 'Dismiss message' }).click();
}

test('PO comment line: category-free authoring, informational row, no part in totals or receiving', async ({ page }) => {
  const api = await apiAs(personas.finjobs);

  const business = (await api.get('/api/businesses/?page_size=1')).results[0];
  test.skip(!business, 'seed gap: no Business to use as PO vendor');

  const po = await api.post('/api/purchase-orders/', { business: business.business_id });
  const realDesc = `${stamp} sheet stock`;
  await api.post(`/api/purchase-orders/${po.po_id}/line-items/`, {
    description: realDesc, qty: '2', units: 'none', price: '10.00',
  });

  const commentDesc = `${stamp} vendor lead time is 6 weeks`;

  await test.step('Add Line Item → Comment checkbox collapses qty/price/category; Add saves it', async () => {
    await page.goto(`/#/purchase-orders/${po.po_id}`);
    await expect(page.locator('tr', { hasText: realDesc })).toBeVisible(); // anchor: PO loaded

    await page.getByRole('button', { name: 'Add Line Item' }).click();
    // Anchor: the manual form is really open (qty/price present) before
    // the checkbox collapses them.
    await expect(page.getByLabel('Qty')).toBeVisible();
    await expect(page.getByLabel('Price')).toBeVisible();
    await page.getByLabel('Description').fill(commentDesc);
    await page.getByRole('checkbox', { name: /Comment line/ }).check();
    await expect(page.getByLabel('Qty')).toHaveCount(0);
    await expect(page.getByLabel('Price')).toHaveCount(0);
    await expect(page.getByLabel('Category')).toHaveCount(0);
    await page.getByRole('button', { name: 'Add', exact: true }).click();

    await expect(page.locator('tr', { hasText: commentDesc })).toBeVisible();
  });

  await test.step('Stored zeroed and category-free; the PO total is the real line alone', async () => {
    const detail = await api.get(`/api/purchase-orders/${po.po_id}/`);
    const commentLine = detail.line_items.find((li) => li.description === commentDesc);
    expect(commentLine).toBeTruthy();
    expect(commentLine.is_comment).toBe(true);
    expect(commentLine.accounting_category).toBeNull();
    expect(Number(commentLine.qty)).toBe(0);
    expect(Number(commentLine.price)).toBe(0);

    // Totals row: 2 × $10.00 from the real line, nothing from the comment.
    await expect(page.locator('tfoot tr', { hasText: 'Total' }).first()).toContainText('$20.00');
  });

  await test.step('Issue + Receive All: the real line receives in full; the comment has nothing to receive and never blocks it', async () => {
    page.once('dialog', (d) => d.accept());
    await page.getByRole('button', { name: 'Mark as Issued' }).click();
    await expect(page.locator('.status-badge')).toHaveText('issued');
    await dismissOverlay(page);

    await page.getByRole('button', { name: 'Receive All' }).click();
    await expect(page.locator('.status-badge')).toHaveText('received in full');
    await dismissOverlay(page);

    const detail = await api.get(`/api/purchase-orders/${po.po_id}/`);
    const realLine = detail.line_items.find((li) => li.description === realDesc);
    expect(Number(realLine.qty_received)).toBe(2); // anchor: receiving really ran
    const commentLine = detail.line_items.find((li) => li.description === commentDesc);
    expect(Number(commentLine.qty_received)).toBe(0);
  });

  await api.dispose();
});
