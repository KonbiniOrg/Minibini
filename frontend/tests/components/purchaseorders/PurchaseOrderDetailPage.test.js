import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByText, findAllByText } from '@testing-library/svelte';

const { qsRef } = vi.hoisted(() => ({ qsRef: { value: '' } }));
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({
  push: vi.fn(),
  querystring: { subscribe: (fn) => { fn(qsRef.value); return () => {}; } },
  link: () => {},
}));
vi.mock('@/stores/permissions.js', () => ({
  canManageFinancials: { subscribe: (fn) => { fn(true); return () => {}; } },
}));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
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
  qsRef.value = '';
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/history/')) return Promise.resolve([]);
    if (url.includes('/accounting-categories/')) return Promise.resolve({ results: [] });
    return Promise.resolve(PO);
  });
  api.delete.mockResolvedValue({ message: 'PO deleted.' });
  vi.stubGlobal('confirm', () => true);
  clearMessage();
});

describe('PurchaseOrderDetailPage accounting categories', () => {
  it('loads accounting categories from the unfiltered endpoint (no exclude_fallback param)', async () => {
    render(PurchaseOrderDetailPage, { props: { params: { id: '7' } } });
    await vi.waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/api/accounting-categories/?page_size=100');
    });
  });
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

describe('PurchaseOrderDetailPage one-shot material prefill', () => {
  it('does not re-send material_id on a second line', async () => {
    qsRef.value = 'prefill_material=9&default_job=3';
    const PO_DRAFT = {
      po_id: 7, po_number: 'PO-7', status: 'draft', business_name: 'Acme',
      created_date: '2026-06-20T00:00:00Z', line_items: [],
    };
    api.get.mockImplementation((url) => {
      if (url.includes('/history/')) return Promise.resolve([]);
      if (url.includes('/accounting-categories/')) return Promise.resolve({ results: [] });
      if (url.includes('/api/jobs/3/')) return Promise.resolve({ job_id: 3, job_number: 'J-1' });
      if (url.includes('/api/jobs/')) return Promise.resolve({ results: [] });
      if (url.includes('/api/materials/9/')) return Promise.resolve({
        material_id: 9, quantity: '2', inventory_item: 5, description: 'Bolt',
        unit_cost: '1.00', accounting_category: null });
      if (url.includes('/api/inventory/5/')) return Promise.resolve({
        inventory_item_id: 5, code: 'B', description: 'Bolt', units: 'ea',
        purchase_price: '1.00', accounting_category: null });
      if (url.includes('/api/inventory/')) return Promise.resolve({
        results: [{ inventory_item_id: 5, code: 'B', description: 'Bolt' }] });
      return Promise.resolve(PO_DRAFT);
    });
    api.post.mockResolvedValue({});

    const { container } = render(PurchaseOrderDetailPage, { props: { params: { id: '7' } } });

    // The prefilled add form auto-opens; submit the first line.
    await fireEvent.click(await findByText(container, 'Add'));
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    // First line carried the material_id from the "order this material" prefill.
    expect(api.post.mock.calls[0][1]).toHaveProperty('material_id', 9);

    // Reopen the form for a second line and fill it manually.
    await fireEvent.click(await findByText(container, 'Add Line Item'));
    await fireEvent.input(container.querySelector('#description'), { target: { value: 'Nut' } });
    await fireEvent.input(container.querySelector('#qty'), { target: { value: '4' } });
    await fireEvent.input(container.querySelector('#price'), { target: { value: '0.50' } });
    await fireEvent.click(await findByText(container, 'Add'));

    await vi.waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    // The fix: the one-shot prefill was cleared, so no stale material_id.
    expect(api.post.mock.calls[1][1]).not.toHaveProperty('material_id');
  });
});

describe('PurchaseOrderDetailPage global overlay messages', () => {
  it('raises the global error overlay when delete fails (no local overlay markup)', async () => {
    api.delete.mockRejectedValue(Object.assign(new Error('Conflict'), {
      status: 409,
      data: { detail: 'This purchase order is referenced.' },
    }));

    const { container } = render(PurchaseOrderDetailPage, { props: { params: { id: '7' } } });
    const deletes = await findAllByText(container, 'Delete');
    const poDelete = deletes.find(el => !el.closest('table'));
    await fireEvent.click(poDelete);
    const confirmBtn = await findByText(container, 'Confirm');
    await fireEvent.click(confirmBtn);

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({
        kind: 'error',
        text: 'This purchase order is referenced.',
      });
    });
    // The page no longer carries its own overlay markup.
    expect(container.querySelector('.error-overlay')).toBeNull();
  });

  it('raises the global success overlay after a status action', async () => {
    vi.stubGlobal('prompt', () => '');
    api.post.mockResolvedValue({});

    const { container } = render(PurchaseOrderDetailPage, { props: { params: { id: '7' } } });
    await fireEvent.click(await findByText(container, 'Mark as Issued'));

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({
        kind: 'success',
        text: 'Purchase order issued.',
      });
    });
  });
});
