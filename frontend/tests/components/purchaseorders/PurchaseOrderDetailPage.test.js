import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByText, findAllByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  push: vi.fn(),
  querystring: { subscribe: (fn) => { fn(''); return () => {}; } },
  link: () => {},
}));
vi.mock('@/stores/permissions.js', () => ({
  canManageFinancials: { subscribe: (fn) => { fn(true); return () => {}; } },
}));

import { api } from '@/lib/api.js';
import PurchaseOrderDetailPage from '@/routes/purchaseorders/PurchaseOrderDetailPage.svelte';

const PO = {
  po_id: 7,
  po_number: 'PO-7',
  status: 'draft',
  business_name: 'Acme',
  created_date: '2026-06-20T00:00:00Z',
  line_items: [
    {
      line_item_id: 42, line_number: 1, description: 'Widget',
      qty: '5', price: '1.00', units: 'ea',
      material: { material_id: 9, consumption_state: 'pending',
                  job_number: 'J-1', quantity: '5' },
    },
  ],
};

beforeEach(() => {
  api.get.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/history/')) return Promise.resolve([]);
    if (url.includes('/accounting-categories/')) return Promise.resolve({ results: [] });
    return Promise.resolve(PO);
  });
  api.delete.mockResolvedValue({ message: 'PO deleted.' });
  vi.stubGlobal('confirm', () => true);
});

describe('PurchaseOrderDetailPage delete with sever', () => {
  it('sends sever decisions under the plural "sever_decisions" key', async () => {
    const { container } = render(PurchaseOrderDetailPage, { props: { params: { id: '7' } } });

    // Wait for load, then click the PO-level Delete button (not the per-line
    // Delete inside the line-items table).
    const deletes = await findAllByText(container, 'Delete');
    const poDelete = deletes.find(el => !el.closest('table'));
    await fireEvent.click(poDelete);

    // The sever dialog appears (the line has a pending linked material).
    const confirmBtn = await findByText(container, 'Confirm');
    await fireEvent.click(confirmBtn);

    expect(api.delete).toHaveBeenCalledTimes(1);
    const [url, body] = api.delete.mock.calls[0];
    expect(url).toContain('/api/purchase-orders/7/');
    // The bug: this was sent as singular `sever_decision`, which the backend
    // (reads `sever_decisions`) ignored → "sever decision required".
    expect(body).toHaveProperty('sever_decisions');
    expect(body).not.toHaveProperty('sever_decision');
    expect(body.sever_decisions).toHaveProperty('42');
  });
});
