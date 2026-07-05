import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, f) => e?.message || f,
}));
vi.mock('@/stores/messages.js', () => ({
  showSuccess: vi.fn(), showError: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { showSuccess } from '@/stores/messages.js';
import StockOrderDialog from '@/components/inventory/StockOrderDialog.svelte';

const item = { inventory_item_id: 7, code: 'SHEET-3' };

beforeEach(() => {
  api.get.mockReset(); api.post.mockReset(); showSuccess.mockReset();
  api.post.mockResolvedValue({ po_id: 9, po_number: 'PO-2026-0001' });
});

describe('StockOrderDialog', () => {
  it('pre-fills the quantity and orders immediately when no drafts exist', async () => {
    api.get.mockResolvedValue({ results: [] });
    const onDone = vi.fn();
    const { getByLabelText, getByRole } = render(StockOrderDialog, {
      props: { item, prefillQty: '3', onDone, onCancel: () => {} },
    });
    expect(getByLabelText(/Quantity/).value).toBe('3');
    await fireEvent.click(getByRole('button', { name: 'Order' }));
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/inventory/7/order/', { quantity: '3' }));
    expect(showSuccess).toHaveBeenCalled();
    expect(onDone).toHaveBeenCalled();
  });

  it('reports a zero quantity instead of silently doing nothing', async () => {
    const { getByRole, getByText } = render(StockOrderDialog, {
      props: { item, prefillQty: '0', onDone: () => {}, onCancel: () => {} },
    });
    await fireEvent.click(getByRole('button', { name: 'Order' }));
    expect(getByText('Enter a quantity greater than 0.')).toBeTruthy();
    expect(api.get).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('offers the draft chooser when drafts exist and appends on pick', async () => {
    api.get.mockResolvedValue({ results: [
      { po_id: 4, po_number: 'PO-2026-0004', status: 'draft' },
    ] });
    const { getByRole, findByRole } = render(StockOrderDialog, {
      props: { item, prefillQty: '2', onDone: () => {}, onCancel: () => {} },
    });
    await fireEvent.click(getByRole('button', { name: 'Order' }));
    const appendBtn = await findByRole('button', { name: /PO-2026-0004/ });
    await fireEvent.click(appendBtn);
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/inventory/7/order/', { quantity: '2', po_id: 4 }));
  });

  it('can start a new PO from the chooser', async () => {
    api.get.mockResolvedValue({ results: [
      { po_id: 4, po_number: 'PO-2026-0004', status: 'draft' },
    ] });
    const { getByRole, findByRole } = render(StockOrderDialog, {
      props: { item, prefillQty: '2', onDone: () => {}, onCancel: () => {} },
    });
    await fireEvent.click(getByRole('button', { name: 'Order' }));
    await fireEvent.click(await findByRole('button', { name: 'Start new PO' }));
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/inventory/7/order/', { quantity: '2' }));
  });
});
