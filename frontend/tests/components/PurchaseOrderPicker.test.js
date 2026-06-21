import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByText } from '@testing-library/svelte';
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import PurchaseOrderPicker from '@/components/PurchaseOrderPicker.svelte';

beforeEach(() => api.get.mockReset());

describe('PurchaseOrderPicker', () => {
  it('lists the vendor POs and emits selection', async () => {
    api.get.mockResolvedValue({ results: [{ po_id: 5, po_number: 'PO-1', status: 'issued' }] });
    const onSelect = vi.fn();
    const { container, getByPlaceholderText } = render(PurchaseOrderPicker, {
      props: { businessId: 9, value: null, onSelect },
    });
    await fireEvent.input(getByPlaceholderText(/purchase order/i), { target: { value: 'PO' } });
    const opt = await findByText(container, /PO-1/);
    await fireEvent.click(opt);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ po_id: 5, po_number: 'PO-1' }));
  });
});
